"""Signal layer (block 3): perception frames -> per-visitor features -> baseline -> deviation -> events.

Events (Perception & decision loop §2, D10):
  linger     dwell on one feature of the current stop well above the visitor's own baseline dwell
  approach   standing closer to the exhibit than own baseline, while inside the formation
  point_ask  pointing at a feature, or a question (a talked-over question is also a bid + barrier)
  drift      gaze resting on another exhibit (unusual for this visitor)
  fatigue    leaning/sitting, or facing away + looking at nothing + standing still (unusual for this visitor)
  bid        edging inward from outside the formation, repeated short robot glances, or speech that was talked over
  barrier    detail "position": facing the stop but view of the exhibit blocked or outside the formation
             detail "talked_over": speaking while someone who started earlier is still speaking
  excluded   bid AND barrier at the same time (D10); the episode lasts until no barrier is left

Bids, lingers, approaches, drifts and fatigue are judged against the visitor's own baseline (D4).
Barriers are judged absolutely: they describe the situation, not the person.

Online: feed records one at a time (step), in stream order; call finish() at the end.
Thresholds live in sdc/config.py. Each event carries a human-readable `reason`.
"""
import math
from dataclasses import dataclass, field

from . import config as C
from .adapter import Frame, Header, StartImpression, Utterance


@dataclass
class Event:
    kind: str
    track_id: str
    t_detect: float                  # when the layer emitted it (latency is measured from here)
    t0: float                        # when the evidence started
    t1: float | None = None          # end; None while active
    target: str | None = None
    detail: str | None = None
    reason: str = ""

    def as_dict(self):
        return {k: (round(v, 2) if isinstance(v, float) else v) for k, v in vars(self).items()}


def _wrap(a):
    return (a + math.pi) % (2 * math.pi) - math.pi


def seed_weight(stop_index):
    """Weight of the start-impression prior: SEED_WEIGHT_S at the first stop, 0 from stop index SEED_FADE_STOPS."""
    return C.SEED_WEIGHT_S * max(0.0, 1.0 - stop_index / C.SEED_FADE_STOPS)


class Baseline:
    """Running mean seeded by a prior: (w0 * prior + sum) / (w0 + n). `frozen` samples are skipped by callers."""

    def __init__(self, prior=None, prior_weight=0.0):
        self.prior, self.prior_weight = prior, (prior_weight if prior is not None else 0.0)
        self.sum, self.n = 0.0, 0.0

    def add(self, x, w=1.0):
        self.sum += x * w
        self.n += w

    def ready(self, min_n):
        return self.prior_weight > 0 or self.n >= min_n

    @property
    def value(self):
        w = self.prior_weight + self.n
        if w == 0:
            return None
        return ((self.prior or 0.0) * self.prior_weight + self.sum) / w


class Hysteresis:
    """Condition evaluated each tick. On after it has held for on_s; off after it has been false for off_s."""

    def __init__(self, on_s, off_s):
        self.on_s, self.off_s = on_s, off_s
        self.since = None       # start of the current run of true ticks (evidence start)
        self.last_true = None
        self.active = False

    def update(self, t, cond, tick):
        """Returns 'start', 'end' or None."""
        if cond:
            if self.since is None:
                self.since = t - tick
            self.last_true = t
            if not self.active and t - self.since >= self.on_s - 1e-9:
                self.active = True
                return "start"
        else:
            if not self.active:
                self.since = None
            elif t - self.last_true >= self.off_s - 1e-9:
                self.active, self.since = False, None
                return "end"
        return None


@dataclass
class _Visitor:
    seed: object
    # attention, tracked at frame rate with debounce
    att: str = "none"
    att_since: float = 0.0
    cand: str | None = None
    cand_since: float = 0.0
    glances: list = field(default_factory=list)       # completed robot glances [(t0, t1)]
    pointing_since: float | None = None
    pointing_target: str | None = None
    pointing_emitted: bool = False
    overlapped_t: list = field(default_factory=list)  # frame times with overlapped speech
    last_xy: tuple | None = None
    frames: list = field(default_factory=list)        # this tick's observations
    # baselines (created in _init_baselines)
    dist: dict = field(default_factory=dict)          # in_formation(bool) -> Baseline
    dwell: Baseline | None = None
    glance_rate: Baseline | None = None
    other_frac: Baseline | None = None
    posture_frac: Baseline | None = None
    away_frac: Baseline | None = None
    dist_seeded: bool = False
    # rule state
    hyst: dict = field(default_factory=dict)
    active: dict = field(default_factory=dict)        # kind or "barrier:<detail>" -> Event
    last_point_ask: Event | None = None
    point_ask_modes: set = field(default_factory=set)


class SignalLayer:
    def __init__(self, gallery, stop, stop_index=0):
        self.ex = {e["id"]: e for e in gallery["exhibits"]}
        self.feature_exhibit = {f["id"]: e["id"] for e in gallery["exhibits"] for f in e["features"]}
        self.v = {}
        self.events = []
        self.tick = C.SIGNAL_TICK_S
        self.next_tick = None
        self.t_last = 0.0
        self.set_stop(stop, stop_index)

    # ------------------------------------------------------------ public API
    def set_stop(self, stop, stop_index):
        """The decision layer tells the signal layer which exhibit is the current stop."""
        self.stop, self.stop_index = stop, stop_index
        w = seed_weight(stop_index)
        for st in self.v.values():
            for b in [*st.dist.values(), st.glance_rate, st.other_frac, st.posture_frac, st.away_frac]:
                if b is not None and b.prior is not None:
                    b.prior_weight = w

    def step(self, rec):
        """Feed one adapter record. Returns the events that started or ended because of it."""
        out = []
        if isinstance(rec, Header):
            pass
        elif isinstance(rec, StartImpression):
            for tid, seed in rec.visitors.items():
                self.v[tid] = self._new_visitor(seed)
        elif isinstance(rec, Frame):
            if self.next_tick is None:
                self.next_tick = math.floor(rec.t / self.tick) * self.tick + self.tick
            while rec.t >= self.next_tick - 1e-9:
                out += self._run_tick(self.next_tick)
                self.next_tick += self.tick
            out += self._on_frame(rec)
        elif isinstance(rec, Utterance):
            out += self._on_utterance(rec)
        self.t_last = max(self.t_last, getattr(rec, "t", 0.0))
        return out

    def finish(self):
        """Flush the last tick and close every active event at the end of the stream."""
        out = []
        if self.next_tick is not None and any(st.frames for st in self.v.values()):
            out += self._run_tick(self.next_tick)
        for st in self.v.values():
            for ev in st.active.values():
                ev.t1 = self.t_last
                out.append(ev)
            st.active.clear()
        return out

    def run(self, records):
        for r in records:
            self.step(r)
        self.finish()
        return self.events

    # ------------------------------------------------------------ setup
    def _new_visitor(self, seed):
        w = seed_weight(self.stop_index)
        st = _Visitor(seed=seed)
        st.dist = {True: Baseline(), False: Baseline()}   # seed goes to the state of the first tick
        st.dwell = Baseline(C.DWELL_PRIOR_S, C.DWELL_PRIOR_RUNS)
        st.glance_rate = Baseline(seed.robot_glances_per_min, w)
        st.other_frac = Baseline(C.STATE_PRIOR_FRAC, w)
        st.posture_frac = Baseline(C.STATE_PRIOR_FRAC, w)
        st.away_frac = Baseline(C.STATE_PRIOR_FRAC, w)
        st.hyst = {
            "linger": Hysteresis(0.0, C.LINGER_OFF_S),
            "approach": Hysteresis(C.APPROACH_ON_S, C.APPROACH_OFF_S),
            "drift": Hysteresis(C.DRIFT_ON_S, C.DRIFT_OFF_S),
            "fatigue": Hysteresis(C.FATIGUE_ON_S, C.FATIGUE_OFF_S),
            "bid": Hysteresis(0.0, C.BID_OFF_S),
            "barrier:position": Hysteresis(C.BARRIER_ON_S, C.BARRIER_OFF_S),
            "barrier:talked_over": Hysteresis(0.0, C.TALKED_OVER_OFF_S),
        }
        return st

    # ------------------------------------------------------------ helpers
    def _is_stop_target(self, att):
        if att == f"exhibit:{self.stop}":
            return True
        return att.startswith("feature:") and self.feature_exhibit.get(att[8:]) == self.stop

    def _other_exhibit(self, att):
        if att.startswith("exhibit:") and att[8:] != self.stop:
            return att[8:]
        if att.startswith("feature:"):
            e = self.feature_exhibit.get(att[8:])
            if e and e != self.stop:
                return e
        return None

    def _bearing_diff(self, o):
        e = self.ex[self.stop]
        return abs(_wrap(o.body_yaw - math.atan2(e["y"] - o.y, e["x"] - o.x)))

    def _start(self, st, key, kind, t, t0, reason, target=None, detail=None):
        ev = Event(kind, st.seed.track_id, t, t0, target=target, detail=detail, reason=reason)
        st.active[key] = ev
        self.events.append(ev)
        return ev

    def _end(self, st, key, t1):
        ev = st.active.pop(key)
        ev.t1 = t1
        return ev

    # ------------------------------------------------------------ frame rate: attention runs, pointing, overlap
    def _on_frame(self, f):
        out = []
        for tid, o in f.visitors.items():
            st = self.v.get(tid)
            if st is None or o.track_conf < C.MIN_TRACK_CONF:
                continue
            st.frames.append(o)
            self._update_attention(st, o.attention, f.t)
            if o.overlapped:
                st.overlapped_t.append(f.t)
            # pointing
            if o.pointing_at:
                if st.pointing_since is None or o.pointing_at != st.pointing_target:
                    st.pointing_since, st.pointing_target, st.pointing_emitted = f.t, o.pointing_at, False
                if not st.pointing_emitted and f.t - st.pointing_since >= C.POINT_MIN_S - 1e-9:
                    st.pointing_emitted = True
                    out += self._point_ask(st, f.t, st.pointing_since, o.pointing_at,
                                           f"pointing at {o.pointing_at} for ≥ POINT_MIN_S={C.POINT_MIN_S}s", "point")
                elif st.pointing_emitted and st.last_point_ask is not None:
                    st.last_point_ask.t1 = f.t
            else:
                st.pointing_since = None
        return out

    def _update_attention(self, st, att, t):
        if att == st.att:
            st.cand = None
            return
        if att != st.cand:
            st.cand, st.cand_since = att, t
            return
        if t - st.cand_since >= C.ATTENTION_DEBOUNCE_S - 1e-9:
            self._close_run(st, st.att, st.att_since, st.cand_since)
            st.att, st.att_since, st.cand = att, st.cand_since, None

    def _close_run(self, st, att, t0, t1):
        if att == "robot":
            st.glances.append((t0, t1))
        elif self._is_stop_target(att) and "linger" not in st.active:
            st.dwell.add(t1 - t0)

    # ------------------------------------------------------------ utterances
    def _on_utterance(self, u):
        st = self.v.get(u.track_id)
        if st is None or not u.is_question:
            return []
        t_start = u.t - u.duration_s
        overlapped = any(t_start - 0.15 <= t <= u.t for t in st.overlapped_t)
        if overlapped and not C.OVERLAPPED_QUESTION_IS_POINT_ASK:
            return []   # handled as bid + talked-over barrier by the tick rules
        target = st.att[8:] if st.att.startswith("feature:") else None
        how = "question, talked over" if overlapped else "question that got the floor"
        return self._point_ask(st, u.t, t_start, target, f'{how}: "{u.text}"', "question")

    def _point_ask(self, st, t, t0, target, reason, mode):
        """mode: 'point' or 'question'. A point and a question close together are one event;
        two questions are always two events."""
        last = st.last_point_ask
        if (last is not None and t - last.t1 <= C.POINT_ASK_MERGE_S
                and mode not in st.point_ask_modes):
            st.point_ask_modes.add(mode)
            last.t1 = t
            last.reason += f" + {reason}"
            last.target = last.target or target
            return []
        ev = Event("point_ask", st.seed.track_id, t, t0, t1=t, target=target, reason=f"point_ask: {reason}")
        self.events.append(ev)
        st.last_point_ask, st.point_ask_modes = ev, {mode}
        return [ev]

    # ------------------------------------------------------------ tick rules
    def _run_tick(self, t):
        out = []
        for st in self.v.values():
            if st.frames:
                out += self._tick_visitor(st, t)
            st.frames = []
        return out

    def _tick_visitor(self, st, t):
        fs, n, tick = st.frames, len(st.frames), self.tick
        frac = lambda pred: sum(1 for o in fs if pred(o)) / n
        ex = self.ex[self.stop]
        x, y = sum(o.x for o in fs) / n, sum(o.y for o in fs) / n
        dist = math.hypot(x - ex["x"], y - ex["y"])
        speed = math.dist((x, y), st.last_xy) / tick if st.last_xy else 0.0
        st.last_xy = (x, y)
        in_form = frac(lambda o: o.in_formation) >= 0.5
        oriented = frac(lambda o: self._bearing_diff(o) <= C.ORIENTED_TO_STOP_RAD) >= 0.5
        los_exh = frac(lambda o: o.los_exhibit) >= 0.5
        los_rob = frac(lambda o: o.los_robot) >= 0.5
        talked_over = any(o.overlapped for o in fs)
        others = [self._other_exhibit(o.attention) for o in fs]
        other_target = max(set(others) - {None}, key=others.count, default=None)
        looking_other = sum(1 for e in others if e) / n >= 0.5
        posture_tired = frac(lambda o: o.posture in C.FATIGUE_POSTURES) >= 0.5
        away_idle = (frac(lambda o: self._bearing_diff(o) >= C.FACING_AWAY_RAD) >= 0.5
                     and frac(lambda o: o.attention == "none") >= 0.5 and speed < C.STILL_SPEED_MPS)

        if not st.dist_seeded:
            st.dist[in_form] = Baseline(st.seed.distance_m, seed_weight(self.stop_index))
            st.dist_seeded = True
        base_d = st.dist[in_form]
        base_ok = base_d.ready(C.BASELINE_MIN_S)
        bv = base_d.value if base_d.value is not None else float("nan")
        drop = (bv - dist) if base_d.value is not None else 0.0

        # glances in the last window
        w0 = t - C.GLANCE_WINDOW_S
        recent = [g for g in st.glances if g[1] > w0]
        shorts = [g for g in recent if g[1] - g[0] <= C.SHORT_GLANCE_MAX_S]
        onsets = [g for g in st.glances if g[0] > w0] + ([1] if st.att == "robot" and st.att_since > w0 else [])
        rate = len(onsets) * 60.0 / C.GLANCE_WINDOW_S
        onsets_tick = sum(1 for g in st.glances if t - tick < g[0] <= t) + \
            (1 if st.att == "robot" and t - tick < st.att_since <= t else 0)

        out = []

        def drive(key, kind, cond, reason, t0_hint=None, target=None, detail=None):
            h = st.hyst[key]
            r = h.update(t, cond, tick)
            if r == "start":
                out.append(self._start(st, key, kind, t, t0_hint if t0_hint is not None else h.since,
                                       reason, target, detail))
            elif r == "end":
                out.append(self._end(st, key, h.last_true))

        # --- barriers (absolute)
        view_blocked = not los_exh or (C.BARRIER_USE_LOS_ROBOT and not los_rob)
        pos_cond = oriented and (view_blocked or not in_form)
        causes = [c for c, on in (("view blocked", view_blocked), ("outside formation", not in_form)) if on]
        drive("barrier:position", "barrier", pos_cond,
              f"barrier: facing the stop and {' + '.join(causes)} for ≥ BARRIER_ON_S={C.BARRIER_ON_S}s",
              detail="position")
        drive("barrier:talked_over", "barrier", talked_over,
              "barrier: speaking while someone who started earlier is still speaking", detail="talked_over")

        # --- bid (vs own baseline)
        edging = (not in_form and oriented and base_ok and drop >= C.EDGE_MIN_DROP_M)
        glancing = (len(shorts) >= C.GLANCE_MIN_SHORT
                    and rate >= C.GLANCE_RATE_FACTOR * st.glance_rate.value)
        cues = []
        if edging:
            cues.append(f"edging in from outside the formation ({drop:.2f} m closer than own baseline "
                        f"{bv:.2f} m, ≥ EDGE_MIN_DROP_M={C.EDGE_MIN_DROP_M})")
        if glancing:
            cues.append(f"{len(shorts)} short robot glances in {C.GLANCE_WINDOW_S:.0f}s, rate {rate:.0f}/min "
                        f"≥ GLANCE_RATE_FACTOR×own {st.glance_rate.value:.1f}/min")
        if talked_over:
            cues.append("started to speak and was talked over")
        drive("bid", "bid", bool(cues), "bid: " + "; ".join(cues))

        # --- excluded = bid AND barrier; lasts until no barrier is left
        barriers = sorted(k.split(":")[1] for k in st.active if k.startswith("barrier:"))
        if "excluded" not in st.active:
            if "bid" in st.active and barriers:
                out.append(self._start(st, "excluded", "excluded", t, max(st.hyst["bid"].since or t, t - tick),
                                       f"excluded: bid ({st.active['bid'].reason[5:]}) AND barrier ({', '.join(barriers)})",
                                       detail=",".join(barriers)))
        else:
            ev = st.active["excluded"]
            for b in barriers:
                if b not in ev.detail.split(","):
                    ev.detail += f",{b}"
            if not barriers:
                ends = [h.last_true for k, h in st.hyst.items() if k.startswith("barrier:") and h.last_true]
                out.append(self._end(st, "excluded", max(ends) if ends else t))

        # --- linger: one feature, well above own dwell
        run = t - st.att_since
        thr = max(C.LINGER_MIN_S, C.LINGER_FACTOR * st.dwell.value)
        is_feature = st.att.startswith("feature:") and self._is_stop_target(st.att)
        drive("linger", "linger", is_feature and run >= thr,
              f"linger: {run:.0f}s on {st.att[8:]} ≥ max(LINGER_MIN_S={C.LINGER_MIN_S}, "
              f"LINGER_FACTOR={C.LINGER_FACTOR}×own dwell {st.dwell.value:.1f}s)",
              t0_hint=st.att_since, target=st.att[8:] if is_feature else None)

        # --- approach: closer than own in-formation baseline
        appr = in_form and oriented and base_ok and drop >= C.APPROACH_MIN_DROP_M
        drive("approach", "approach", appr,
              f"approach: {drop:.2f} m closer to {self.stop} than own baseline {bv:.2f} m "
              f"(≥ APPROACH_MIN_DROP_M={C.APPROACH_MIN_DROP_M})", target=self.stop)

        # --- drift: gaze on another exhibit, unusual for this visitor
        drift = looking_other and st.other_frac.value < C.STATE_BASELINE_MAX_FRAC
        drive("drift", "drift", drift,
              f"drift: gaze on {other_target} for ≥ DRIFT_ON_S={C.DRIFT_ON_S}s "
              f"(own baseline {st.other_frac.value:.0%} of the time)", target=other_target)

        # --- fatigue
        f_posture = posture_tired and st.posture_frac.value < C.STATE_BASELINE_MAX_FRAC
        f_away = away_idle and st.away_frac.value < C.STATE_BASELINE_MAX_FRAC
        fcues = [c for c, on in (("leaning/sitting", f_posture),
                                 ("facing away, looking at nothing, standing still", f_away)) if on]
        drive("fatigue", "fatigue", bool(fcues),
              f"fatigue: {' + '.join(fcues)} for ≥ FATIGUE_ON_S={C.FATIGUE_ON_S}s")

        # --- baseline updates (skipped while the related signal is active)
        if not (edging or appr or "approach" in st.active):
            base_d.add(dist, tick)
        if "bid" not in st.active:
            st.glance_rate.add(onsets_tick * 60.0 / tick, tick)
        if "drift" not in st.active:
            st.other_frac.add(float(looking_other), tick)
        if "fatigue" not in st.active:
            st.posture_frac.add(float(posture_tired), tick)
            st.away_frac.add(float(away_idle), tick)
        # keep only what the glance window needs
        st.glances = [g for g in st.glances if g[1] > w0 - 1]
        st.overlapped_t = [x for x in st.overlapped_t if x > t - 30]
        return out
