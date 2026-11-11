"""Profile store (block 4): per-visitor profile layers + steering credit. Session only.

A profile layer is a small guess about one visitor (Perception & decision loop §1-2):
  kind      feature_interest (target: feature id) · depth (target: exhibit id) · exhibit_interest (target: exhibit id)
  status    pending -> confirmed | rescinded
  confidence 0..1 (confirmed = 1)

Created by signal events (config.LAYER_FROM_EVENT):
  linger -> pending feature_interest · approach -> pending depth · drift -> pending exhibit_interest
  point_ask -> confirmed feature_interest (or exhibit_interest on the stop if no feature was pointed at)
  Start-impression layers from Jay's half -> pending.
Fatigue, bid, barrier and excluded create no layers (they feed pace and the exclusion handler).

The decision layer (task 4) calls confirm / rescind after the uptake window and add_credit
when it visibly acts on a visitor's signal; weight() is D8's w_i = 1 / (1 + λ k_i).

D6: a rescinded layer is not reopened by more of the same evidence during the stop.
Between stops (end_stop) rescinded layers are removed (§6.1); untested pending ones stay.
end_tour() discards all per-visitor state (privacy).

Every change is returned as a dict with a human-readable `reason`, for the event log.
"""
from dataclasses import dataclass, field
import itertools

from . import config as C


@dataclass
class Layer:
    id: str
    track_id: str
    kind: str
    target: str
    status: str = "pending"
    confidence: float = 0.0
    created_t: float = 0.0
    updated_t: float = 0.0
    evidence: list = field(default_factory=list)   # [(t, source, reason)]

    @property
    def strength(self):
        """Contribution toward s_i(a): confirmed 1, pending PENDING_WEIGHT·confidence, rescinded 0."""
        if self.status == "confirmed":
            return 1.0
        if self.status == "pending":
            return C.PENDING_WEIGHT * self.confidence
        return 0.0


@dataclass
class VisitorProfile:
    track_id: str
    cluster_id: str
    credit: float = 0.0                              # steering credit k_i (D8)
    layers: dict = field(default_factory=dict)       # (kind, target) -> Layer


class ProfileStore:
    def __init__(self, start_impression=None):
        self.visitors = {}
        self.log = []
        self._ids = itertools.count(1)
        if start_impression is not None:
            self.load_start_impression(start_impression)

    # ------------------------------------------------------------ setup
    def load_start_impression(self, si):
        for tid, seed in si.visitors.items():
            self.visitors[tid] = VisitorProfile(tid, seed.cluster_id)
            for pl in seed.pending_layers:
                self._new(tid, pl["kind"], pl["target"], "pending", C.SEED_LAYER_CONF, si.t,
                          "start_impression", "pending layer from the start impression")

    def _visitor(self, tid):
        if tid not in self.visitors:
            self.visitors[tid] = VisitorProfile(tid, cluster_id="?")
        return self.visitors[tid]

    # ------------------------------------------------------------ queries
    def layers(self, tid=None, status=None, kind=None):
        vs = [self.visitors[tid]] if tid else self.visitors.values()
        return [l for v in vs for l in v.layers.values()
                if (status is None or l.status == status) and (kind is None or l.kind == kind)]

    def get(self, layer_id):
        return next((l for l in self.layers() if l.id == layer_id), None)

    def credit(self, tid):
        return self._visitor(tid).credit

    def weight(self, tid):
        """D8: w_i = 1 / (1 + λ·k_i)."""
        return 1.0 / (1.0 + C.LAMBDA_DOMINANCE * self._visitor(tid).credit)

    def cluster(self, cluster_id):
        return [v.track_id for v in self.visitors.values() if v.cluster_id == cluster_id]

    # ------------------------------------------------------------ events -> layers
    def on_event(self, ev, stop):
        """Feed a signal event when it starts. `stop` = current stop's exhibit id. Returns log entries."""
        kind = C.LAYER_FROM_EVENT.get(ev.kind)
        if kind is None:
            return []
        target = ev.target
        if ev.kind == "point_ask":
            if not target:
                kind, target = "exhibit_interest", stop
            return self._confirm_by_ask(ev, kind, target)
        if ev.kind == "approach":
            target = target or stop
        if not target:
            return []
        v = self._visitor(ev.track_id)
        layer = v.layers.get((kind, target))
        conf = C.LAYER_EVENT_CONF[ev.kind]
        if layer is None:
            return self._new(ev.track_id, kind, target, "pending", conf, ev.t_detect, ev.kind,
                             f"pending: {ev.reason}")
        layer.evidence.append((ev.t_detect, ev.kind, ev.reason))
        if layer.status == "rescinded":
            return [self._entry(layer, ev.t_detect, "ignored",
                                f"{ev.kind} again, but layer was rescinded this stop (D6: don't push)")]
        if layer.status == "pending":
            old = layer.confidence
            layer.confidence = 1 - (1 - old) * (1 - conf)
            layer.updated_t = ev.t_detect
            return [self._entry(layer, ev.t_detect, "strengthen",
                                f"more evidence ({ev.kind}): confidence {old:.2f} -> {layer.confidence:.2f}")]
        return [self._entry(layer, ev.t_detect, "evidence", f"{ev.kind} on an already confirmed layer")]

    def _confirm_by_ask(self, ev, kind, target):
        v = self._visitor(ev.track_id)
        layer = v.layers.get((kind, target))
        why = f"confirmed by explicit point/ask: {ev.reason}"
        if layer is None:
            return self._new(ev.track_id, kind, target, "confirmed", 1.0, ev.t_detect, ev.kind, why)
        layer.evidence.append((ev.t_detect, ev.kind, ev.reason))
        if layer.status == "rescinded" and not C.POINT_ASK_REOPENS_RESCINDED:
            return [self._entry(layer, ev.t_detect, "ignored", "point/ask on a rescinded layer")]
        if layer.status == "confirmed":
            return [self._entry(layer, ev.t_detect, "evidence", "another point/ask on a confirmed layer")]
        return self._set(layer, "confirmed", ev.t_detect, why)

    # ------------------------------------------------------------ called by the decision layer
    def confirm(self, layer_id, t, reason):
        """Uptake seen within the window."""
        return self._set(self._layer(layer_id), "confirmed", t, reason)

    def rescind(self, layer_id, t, reason):
        """No uptake within the window (D6)."""
        return self._set(self._layer(layer_id), "rescinded", t, reason)

    def add_credit(self, tid, t, reason, amount=1.0):
        """The robot visibly acted on this visitor's signal (D3, D8)."""
        v = self._visitor(tid)
        v.credit += amount
        e = {"t": t, "op": "credit", "track_id": tid, "credit": v.credit,
             "weight": round(self.weight(tid), 3), "reason": reason}
        self.log.append(e)
        return [e]

    def end_stop(self, t):
        """Between stops (§6.1): rescinded layers are removed; untested pending layers stay."""
        out = []
        for v in self.visitors.values():
            for key, l in list(v.layers.items()):
                if l.status == "rescinded":
                    del v.layers[key]
                    out.append(self._entry(l, t, "remove", "rescinded layer removed between stops"))
        return out

    def end_tour(self, t):
        """Discard all per-visitor state (privacy). Returns only a count."""
        n = len(self.layers())
        self.visitors.clear()
        self.log.clear()
        return {"t": t, "op": "end_tour", "layers_discarded": n}

    # ------------------------------------------------------------ internals
    def _layer(self, layer_id):
        l = self.get(layer_id)
        if l is None:
            raise KeyError(layer_id)
        return l

    def _new(self, tid, kind, target, status, conf, t, source, reason):
        l = Layer(f"L{next(self._ids)}", tid, kind, target, status, conf, t, t, [(t, source, reason)])
        self._visitor(tid).layers[(kind, target)] = l
        return [self._entry(l, t, "create", reason)]

    def _set(self, l, status, t, reason):
        l.status, l.updated_t = status, t
        if status == "confirmed":
            l.confidence = 1.0
        return [self._entry(l, t, status, reason)]

    def _entry(self, l, t, op, reason):
        e = {"t": t, "op": op, "layer": l.id, "track_id": l.track_id, "kind": l.kind, "target": l.target,
             "status": l.status, "confidence": round(l.confidence, 3), "reason": reason}
        self.log.append(e)
        return e
