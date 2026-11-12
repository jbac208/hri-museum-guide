"""Logging + live measures (block 8).

Event log: JSONL of tracks and events only (no video, no visitor speech text). Record types:
  meta     scenario, stop, gallery, duration
  track    robot + visitor poses/attention at LOG_TRACK_HZ (what the replay draws)
  event    signal-layer events (t_detect, t0, t1, kind, target, detail, reason), with the layer it fed
  profile  profile-store changes (create / strengthen / confirmed / rescinded / credit / ...)
  action   robot actions with their reasons
  note     decision-layer notes (exclusion episodes, additions + addressed layers, answers, uptake)
  measures the numbers below, computed from the other records

The four live measures (Perception & decision loop §7) + the P13 headline, all from the log alone:
  steering_uptake  acted-on steering signals / detected steering signals (D3). A steering signal
                   (linger, approach, drift, point_ask) is acted on if it was a question that got
                   answered, or its profile layer was addressed by an addition delivered after it.
  exclusion        episodes, how many resolved, time to resolve (D2, D10)
  misread_rate     layers rescinded / layers tested by an addition (D6)
  dominance_share  share of acted-on signals that came from the single most-acted-on visitor (D8)
  p13_unresolved   share of visitors with >= 1 exclusion episode unresolved at stop end (should be 0)

Privacy: question text is redacted from reasons; anonymise() maps track and cluster ids to
neutral labels (P1.., G1..) for anything kept after the tour.
"""
import json
import re

from . import config as C

_QUOTED = re.compile(r'"[^"]*"')


def _redact(o):
    if isinstance(o, str):
        return _QUOTED.sub('"[speech]"', o)
    if isinstance(o, dict):
        return {k: _redact(v) for k, v in o.items()}
    if isinstance(o, list):
        return [_redact(v) for v in o]
    return o


class EventLog:
    def __init__(self, scenario, stop, gallery_id, duration_s):
        self.meta = {"type": "meta", "t": 0.0, "scenario": scenario, "stop": stop,
                     "gallery": gallery_id, "duration_s": duration_s, "track_hz": C.LOG_TRACK_HZ}
        self.tracks = []
        self.event_layer = {}       # id(Event) -> layer id
        self._next_track_t = 0.0

    def on_frame(self, f):
        if f.t + 1e-9 < self._next_track_t:
            return
        self._next_track_t = f.t + 1.0 / C.LOG_TRACK_HZ
        self.tracks.append({
            "type": "track", "t": f.t,
            "robot": {"x": f.robot.x, "y": f.robot.y, "yaw": f.robot.yaw, "speaking": f.robot.speaking},
            "visitors": [{"id": o.track_id, "x": o.x, "y": o.y, "body_yaw": o.body_yaw, "head_yaw": o.head_yaw,
                          "attention": o.attention, "speaking": o.speaking, "in_formation": o.in_formation,
                          "los_exhibit": o.los_exhibit, "cluster": o.cluster_id}
                         for o in f.visitors.values()]})

    def on_event_start(self, ev, profile_entries):
        layer = next((e.get("layer") for e in profile_entries if e.get("layer")), None)
        if layer:
            self.event_layer[id(ev)] = layer

    def records(self, loop):
        """All records, time-ordered, ending with the measures."""
        recs = [self.meta] + self.tracks
        for ev in loop.signals.events:
            recs.append({"type": "event", "t": ev.t_detect, **ev.as_dict(), "layer": self.event_layer.get(id(ev))})
        recs += [{"type": "profile", **e} for e in loop.profile.log]
        recs += [dict(e) for e in loop.decision_log()]
        for plan in loop.plans:
            recs.append({"type": "note", "note": "plan", **plan, "t": plan.get("t", loop.t)})
        recs = [_redact(r) for r in recs]
        if recs[0].get("duration_s") is None:
            recs[0] = dict(recs[0], duration_s=round(max(r["t"] for r in recs), 1))
        recs.sort(key=lambda r: (r["t"], r["type"] != "meta"))
        recs.append({"type": "measures", "t": recs[-1]["t"], **measures(recs)})
        return recs


def measures(records):
    """Compute the live measures from log records alone."""
    notes = [r for r in records if r["type"] == "note"]
    events = [r for r in records if r["type"] == "event"]
    visitors = {v["id"] for r in records if r["type"] == "track" for v in r["visitors"]}

    # D3 steering uptake
    steering = [e for e in events if e["kind"] in C.STEERING_KINDS]
    additions = [n for n in notes if n["note"] == "addition"]
    answers = sorted((n for n in notes if n["note"] == "question answered"), key=lambda n: n["t"])
    used_answers, acted = set(), []
    for e in sorted(steering, key=lambda e: e["t_detect"]):
        by = None
        if e["kind"] == "point_ask" and "question" in e["reason"]:
            for i, n in enumerate(answers):
                if i not in used_answers and n["track_id"] == e["track_id"] and n["t"] >= e["t_detect"] - 0.5:
                    used_answers.add(i)
                    by = f"answered ({n['qa']})"
                    break
        if by is None and e.get("layer"):
            for n in additions:
                if n["t"] >= e["t_detect"] and e["layer"] in n["addressed"].get(e["track_id"], []):
                    by = f"addition {n['addition']}"
                    break
        if by:
            acted.append({"track_id": e["track_id"], "kind": e["kind"], "t": e["t_detect"], "by": by})
    stops = sorted((n["t"], n["stop"]) for n in notes if n["note"] == "stop start")
    stop_of = lambda t: next((s for t0, s in reversed(stops) if t0 <= t + 1e-9), stops[0][1] if stops else None)
    acted_keys = {(a["track_id"], a["kind"], a["t"]) for a in acted}
    per_stop = []
    for _, sid in stops:
        evs = [e for e in steering if stop_of(e["t_detect"]) == sid]
        n_act = sum(1 for e in evs if (e["track_id"], e["kind"], e["t_detect"]) in acted_keys)
        per_stop.append({"stop": sid, "detected": len(evs), "acted_on": n_act,
                         "share": round(n_act / len(evs), 3) if evs else None})
    behind = [n for n in notes if n["note"] == "falling behind"]
    per_visitor = {}
    for a in acted:
        per_visitor[a["track_id"]] = per_visitor.get(a["track_id"], 0) + 1
    top = max(per_visitor, key=per_visitor.get) if per_visitor else None

    # D2/D10 exclusion episodes
    starts = [n for n in notes if n["note"] == "exclusion episode start"]
    resolved = [n for n in notes if n["note"] == "exclusion episode resolved"]
    unresolved = [n for n in notes if n["note"].startswith("P13 misery")]
    ttr = [n["time_to_resolve_s"] for n in resolved]

    # D6 misreads
    prof = [r for r in records if r["type"] == "profile"]
    confirmed_by_uptake = [p for p in prof if p["op"] == "confirmed" and p["reason"].startswith("uptake after")]
    rescinded = [p for p in prof if p["op"] == "rescinded"]
    tested = len(confirmed_by_uptake) + len(rescinded)

    return {
        "steering_uptake": {"detected": len(steering), "acted_on": len(acted),
                            "share": round(len(acted) / len(steering), 3) if steering else None,
                            "acted": acted, "per_stop": per_stop},
        "falling_behind": {"episodes": len(behind), "who": sorted({n["track_id"] for n in behind})},
        "exclusion": {"episodes": len(starts), "resolved": len(resolved), "unresolved": len(unresolved),
                      "time_to_resolve_s": ttr,
                      "mean_time_to_resolve_s": round(sum(ttr) / len(ttr), 2) if ttr else None},
        "misread_rate": {"tested": tested, "rescinded": len(rescinded),
                         "rate": round(len(rescinded) / tested, 3) if tested else None},
        "dominance_share": {"top_visitor": top, "share": round(per_visitor[top] / len(acted), 3) if top else None,
                            "acted_per_visitor": per_visitor},
        "p13_unresolved": {"visitors_with_unresolved": sorted({n["track_id"] for n in unresolved}),
                           "share": round(len({n["track_id"] for n in unresolved}) / len(visitors), 3)
                           if visitors else None},
    }


def anonymise(records):
    """Map track ids and cluster ids to neutral labels, for anything kept after the tour."""
    ids, clusters = {}, {}
    for r in records:
        for v in r.get("visitors", []) if r["type"] == "track" else []:
            ids.setdefault(v["id"], f"P{len(ids) + 1}")
            clusters.setdefault(v["cluster"], f"G{len(clusters) + 1}")
    if not ids:
        return records
    pat = re.compile(r"\b(" + "|".join(map(re.escape, sorted(ids, key=len, reverse=True))) + r")\b")
    cpat = re.compile(r"\b(" + "|".join(map(re.escape, sorted(clusters, key=len, reverse=True))) + r")\b")

    def sub(o):
        if isinstance(o, str):
            return cpat.sub(lambda m: clusters[m.group(1)], pat.sub(lambda m: ids[m.group(1)], o))
        if isinstance(o, dict):
            return {sub(k): sub(v) for k, v in o.items()}
        if isinstance(o, list):
            return [sub(v) for v in o]
        return o
    return [sub(r) for r in records]


def write(records, path):
    with open(path, "w") as f:
        for r in records:
            f.write(json.dumps(r, separators=(",", ":"), ensure_ascii=False) + "\n")
