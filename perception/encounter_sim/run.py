"""Encounter phase before Joey's tour (simulation): arrival -> our perception -> greeting -> 1-2 group questions ->
start_impression -> his tour, unchanged.

    from perception.encounter_sim.run import run
    records, reactions, info = run("s2_multi_stop", llm=FakeLLM())

Clock: the encounter runs at NEGATIVE times and hands over at t = 0, where his stream already puts the start_impression;
the tour's times, log and measures are his. Encounter records use his log shapes (track / action / note), so his
make_replay.build() carries them; extra per-visitor track fields (detected, age_band, age_conf, group_status) are
ignored by anything that does not know them.

Robot rules in this driver (placeholders, untuned):
  - the engagement event can fire for the first arrival alone, so the greeting waits until the group has gathered:
    everyone in view has passed the stable gate and has a known companion cluster, and no new face has appeared for
    GATHER_S; the robot then turns to the group and greets everyone (frozen neutral_group row only, D4);
  - questions, acknowledgement and the lead-in are dialogue.py's fixed text, all say_to_group (D7);
  - the start_impression is taken at the handoff, not at the event: at the event, companions are not yet grouped.
Handoff: ids must be exactly his visitors with his age classes, or the run fails (no relabelling). distance_m and the
other seed values stay perception's placeholders (encounter.PLACEHOLDER); pending_layers come only from what visitors
said; responded_to_steer_invite = answered at least one question (his loop does not read it).
"""

from __future__ import annotations

import dataclasses
import math
import random
from collections import Counter

import run_tour                                   # Joey's root script: run(spec=...), GALLERY
from sdc import config as C, mock, scenarios, schema

from perception.encounter import Encounter
from perception.integration.run_in_scenario import replaced_start_impression

from . import dialogue, scene

GATHER_S = 3.0
MAX_WAIT_S = 60.0
LOG_HZ = 5
VISITOR_WORDS_PER_S = 2.5


def _speech_s(text, wps):
    return round(max(1.2, len(text.split()) / wps), 2)


def run(name="s2_multi_stop", llm=None, seed=1, pending=True):
    """-> (records, sim reactions, info). records = encounter records (t < 0) + his end-of-tour records."""
    llm = llm or __import__("perception.encounter_sim.llm", fromlist=["FakeLLM"]).FakeLLM()
    gallery = run_tour.GALLERY
    spec = scenarios.TOUR[name]()
    tv = {v.track_id: v for v in spec.visitors}
    people = [(v.track_id, v.age_class, v.cluster_id) for v in spec.visitors]
    st = scene.starts(people)
    cam = scene.ArrivalCamera(people, {p: a for p, a, _ in people}, seed, st)
    walk = scene.WalkIn(spec, gallery, st)
    ex = {e["id"]: e for e in gallery["exhibits"]}
    stop = ex[spec.first_stop]
    names = {e["id"]: e["name"].lower() for e in gallery["exhibits"]}
    names |= {f["id"]: f["name"].lower() for e in gallery["exhibits"] for f in e["features"]}
    m = dialogue.menu(gallery, spec.first_stop)
    rng = random.Random(seed)

    enc = Encounter(cam, cam.detect, cfg={"age": {"id_fmt": "v{}"}})
    samples, first, seen, notes = [], {}, {}, []
    ev = None

    def note(t, what, **kw):
        notes.append({"type": "note", "t": t, "note": "encounter: " + what, **kw})

    def step(t, f):
        nonlocal ev
        e = enc.step(t, f)
        for p in enc.latest:
            seen.setdefault(p, t)
        for p in sorted(enc.stable - set(first)):
            first[p] = t
            note(t, "detected", track_id=p, why=f"passed the stable-frame gate ({enc.stable_frames} frames)")
        if e is not None and ev is None:
            ev = e
            note(t, "engagement", persons=list(e.person_ids), reason=e.reason, group_id=e.group_id)
        if round(t * LOG_HZ, 6) == int(round(t * LOG_HZ, 6)):
            per = {}
            for p in enc.stable:
                r, c = enc.latest.get(p), enc.groups.context(p)
                if r:
                    per[p] = {"band": r["band"], "conf": round(r["confidence"], 2),
                              "cluster": c.group_id if c.status == "known" else None}
            samples.append((t, per))

    frames = cam.frames_until(MAX_WAIT_S + 120)
    try:
        greet_t = None
        for t, f in frames:
            step(t, f)
            present = set(enc.latest)
            if (ev is not None and present <= enc.stable and t - max(seen.values()) >= GATHER_S
                    and all(enc.groups.context(p).status == "known" for p in present)):
                greet_t = t
                break
            if t > MAX_WAIT_S:
                raise RuntimeError(f"seed {seed}: no engagement event or the group never settled by {MAX_WAIT_S} s")
        enc.engagement.exchange_started(sorted(enc.stable), greet_t)

        # ---- the conversation (its timing does not depend on perception)
        rx, ry = stop["x"] + C.ROBOT_STOP_OFFSET[0], stop["y"] + C.ROBOT_STOP_OFFSET[1]
        cx = sum(x for x, _ in walk.slot.values()) / len(walk.slot)
        cy = sum(y for _, y in walk.slot.values()) / len(walk.slot)
        acts, speech = [], []
        acts.append({"t": greet_t, "kind": "turn_body", "args": {"yaw": round(math.atan2(cy - ry, cx - rx), 3)},
                     "duration_s": 0.0, "reason": f"encounter: the group has gathered (after the engagement event, everyone in view "
                                                  f"is confirmed and grouped, no new face for {GATHER_S} s): face everyone"})
        clock = greet_t + 0.5

        def say(sid, text, reason):
            nonlocal clock
            d = round(len(text.split()) / C.TTS_WORDS_PER_S, 2)
            acts.append({"t": round(clock, 2), "kind": "say_to_group", "args": {"text": text, "id": sid},
                         "duration_s": d, "reason": reason})
            clock += d + 0.6

        say("encounter.greet", dialogue.GREETING, "encounter: greet the whole group (neutral row: no age-based wording, D4)")
        asked, known, layers, answered = [], Counter(), {v: [] for v in tv}, set()
        while True:
            q, how, raw = dialogue.select(llm, m, asked, known)
            note(round(clock, 2), "question", qid=q.id if q else None, how=how, llm_raw=raw,
                 why="LLM picked from the allowed menu ids" if how == "llm" else
                     "budget used up" if how == "budget" else "LLM output not an allowed id: first allowed id")
            if q is None:
                break
            asked.append(q.id)
            say(f"encounter.q.{q.id}", q.text, f"encounter: {q.type} question to the group (menu '{q.id}', "
                                               f"{len(asked)}/{dialogue.BUDGET}); no follow-up to anyone who stays quiet (D2)")
            vis = [(v, scene.TALK_P[scene.TALK[v]], tv[v].interests) for v in tv]
            for tid, text in dialogue.replies(q, vis, names, rng):
                clock += rng.uniform(0.3, 1.0)
                d = _speech_s(text, VISITOR_WORDS_PER_S)
                speech.append((round(clock, 2), round(clock + d, 2), tid))
                got, dropped, raw = dialogue.extract(llm, q, text)
                note(round(clock, 2), "answer", track_id=tid, qid=q.id, text=text, duration_s=d, simulated=True,
                     layers=[f"{k}:{t}" for k, t in got], dropped=[f"{i} ({w})" for i, w in dropped], llm_raw=raw)
                clock += d
                answered.add(tid)
                for k in got:
                    if k not in layers[tid]:
                        layers[tid].append(k)
                        known[k] += 1
            clock += 0.6
        say("encounter.ack", dialogue.ACK, "encounter: thank the group (never says who answered, D7)")
        say("encounter.lead", f"Let's begin with the {stop['name'].lower()}.", "encounter: hand over to the tour")
        t_end = round(clock, 1)

        for t, f in frames:
            step(t, f)
            if t >= t_end:
                break
        si = enc.start_impression(ev)
    finally:
        enc.end()

    # ---- handoff
    got_ids = [v["track_id"] for v in si["visitors"]]
    if got_ids != list(tv):
        raise RuntimeError(f"seed {seed}: encounter ids {got_ids} are not the tour's {list(tv)}")
    for v in si["visitors"]:
        if v["age_class"] != tv[v["track_id"]].age_class:
            raise RuntimeError(f"seed {seed}: {v['track_id']} read as {v['age_class']}, script says "
                               f"{tv[v['track_id']].age_class}: wrong person or wrong band")
        v["pending_layers"] = [{"kind": k, "target": t} for k, t in layers[v["track_id"]]] if pending else []
        v["responded_to_steer_invite"] = v["track_id"] in answered
    si["t"] = 0.0
    si["placeholder_fields"] = [f for f in si["placeholder_fields"] if f != "visitors[].responded_to_steer_invite"]
    schema.validate_start_impression(si)
    seed_of = {v["track_id"]: v for v in si["visitors"]}
    spec2 = dataclasses.replace(spec, visitors=[dataclasses.replace(
        v, cluster_id=seed_of[v.track_id]["cluster_id"], age_class=seed_of[v.track_id]["age_class"],
        age_conf=seed_of[v.track_id]["age_conf"]) for v in spec.visitors])
    with replaced_start_impression(lambda his, sim: si):
        tour, sim, _, _ = run_tour.run(name, spec=spec2)
    tour_records = tour.end_tour()

    # ---- encounter records, shifted so the handoff is t = 0
    sh = lambda t: round(t - t_end, 2)
    note(t_end, "clusters", partition={v["track_id"]: v["cluster_id"] for v in si["visitors"]},
         why="companion clusters at the handoff (proximity + co-movement over time)")
    note(t_end, "handoff", visitors=[{k: v[k] for k in ("track_id", "age_class", "age_conf", "age_band", "p_child",
                                                         "cluster_id", "pending_layers", "responded_to_steer_invite")}
                                     for v in si["visitors"]],
         placeholder_fields=si["placeholder_fields"])
    heights = {v: tv[v].height for v in tv}
    recs = []
    for t, per in samples:
        if t >= t_end:
            break
        speaking = {tid for t0, t1, tid in speech if t0 <= t < t1}
        robot_speaking = any(a["kind"] == "say_to_group" and a["t"] <= t < a["t"] + a["duration_s"] for a in acts)
        pos = {v: walk.at(v, t) for v in tv}
        vis = []
        for v in tv:
            x, y, heading = pos[v]
            face = heading if heading is not None else math.atan2(ry - y, rx - x)
            others = [{"x": pos[o][0], "y": pos[o][1], "height": heights[o]} for o in tv if o != v]
            s = per.get(v)
            vis.append({"id": v, "x": round(x, 3), "y": round(y, 3), "body_yaw": round(face, 3), "head_yaw": round(face, 3),
                        "attention": "robot" if heading is None else "none", "speaking": v in speaking,
                        "in_formation": mock.FORMATION_RING[0] <= math.dist((x, y), (stop["x"], stop["y"])) <= mock.FORMATION_RING[1],
                        "los_exhibit": mock.line_of_sight({"x": x, "y": y, "height": heights[v]}, (stop["x"], stop["y"]), others),
                        "cluster": (s or {}).get("cluster") or "?", "detected": s is not None,
                        "age_band": s["band"] if s else None, "age_conf": s["conf"] if s else None,
                        "group_status": "known" if s and s["cluster"] else "unknown"})
        yaw0 = math.atan2(cy - 3.5 - ry, cx - rx)       # before the turn: toward where people come in
        recs.append({"type": "track", "t": sh(t), "robot": {"x": rx, "y": ry, "yaw": round(yaw0, 3),
                                                            "speaking": robot_speaking}, "visitors": vis})
    recs += [{"type": "action", **a, "t": sh(a["t"])} for a in acts]
    recs += [dict(n, t=sh(n["t"])) for n in notes]
    recs.sort(key=lambda r: r["t"])
    info = {"t_encounter_s": t_end, "greet_t": sh(greet_t), "event_t": sh(ev.t), "start_impression": si,
            "asked": asked, "layers": {k: v for k, v in layers.items() if v}, "answered": sorted(answered),
            "llm_model": getattr(llm, "model", "?")}
    return recs + tour_records, sim.reactions, info
