"""Encounter phase before Joey's tour (simulation): arrival at a reception -> our perception -> greeting -> 1-2 group
questions -> the robot leads the group to stop 1 -> start_impression -> his tour, unchanged.

    from perception.encounter_sim.run import run
    records, reactions, info = run("s2_multi_stop", llm=FakeLLM())

Clock: the encounter runs at NEGATIVE times and hands over at t = 0, where his stream already puts the start_impression;
the tour's times, log and measures are his. The handoff is the end of the walk to stop 1: at t = 0 the robot and the
visitors stand where his tour sim puts them (his first track row gives the final yaws). Encounter records use his log shapes (track / action / note), so his
make_replay.build() carries them; extra per-visitor track fields (detected, age_band, age_conf, group_status) are
ignored by anything that does not know them.

Robot rules in this driver (placeholders, untuned):
  - the engagement event can fire for the first arrival alone, so the greeting waits until the group has gathered:
    everyone in view has passed the stable gate and has a known companion cluster, and no new face has appeared for
    GATHER_S; the robot then turns to the group and greets everyone (frozen neutral_group row only, D4);
  - questions, acknowledgement and the lead-in are dialogue.py's fixed text, all say_to_group (D7);
  - the walk to stop 1 starts when the lead-in ends: the robot at C.ROBOT_WALK_MPS, the visitors after it one by one at
    scene.APPROACH_MPS (all on the same vector, scene.RECEPTION); perception keeps running on its scripted camera;
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

GATHER_S = 4.0
MAX_WAIT_S = 60.0
LOG_HZ = 5
VISITOR_WORDS_PER_S = 2.5
PAUSE_S = 0.9                  # between lines (slower than the first version's 0.6)
TURN_S = 1.2                   # a visitor's turn to face the exhibit after they arrive


def _speech_s(text, wps):
    return round(max(1.2, len(text.split()) / wps), 2)


def run(name="s2_multi_stop", llm=None, seed=1, pending=True, tour_questions=True):
    """-> (records, sim reactions, info). records = encounter records (t < 0) + his end-of-tour records.
    tour_questions=False: no LLM questions about the tour; the robot leads the group to stop 1 straight after the small talk."""
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
    ice_rng = random.Random(seed + 11)               # icebreakers have their own stream: the LLM prompts (and the recorded run) stay as they were
    been = {v: ice_rng.random() < 0.4 for v in tv}   # hidden truth for "have you been on a tour before"
    fav = {v: next((t for k, t in sorted(tv[v].interests) if k == "exhibit_interest"), None) for v in tv}

    rrx, rry = stop["x"] + C.ROBOT_STOP_OFFSET[0] + scene.RECEPTION[0], stop["y"] + C.ROBOT_STOP_OFFSET[1] + scene.RECEPTION[1]
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
        rx, ry = stop["x"] + C.ROBOT_STOP_OFFSET[0], stop["y"] + C.ROBOT_STOP_OFFSET[1]      # the robot's spot at stop 1
        cx = sum(x for x, _ in walk.spot.values()) / len(walk.spot)
        cy = sum(y for _, y in walk.spot.values()) / len(walk.spot)
        yaw0, yaw_g = -math.pi / 2, round(math.atan2(cy - rry, cx - rrx), 3)           # facing the door, then the group
        acts, speech = [], []
        acts.append({"t": greet_t, "kind": "turn_body", "args": {"yaw": yaw_g},
                     "duration_s": 0.0, "reason": f"encounter: the group has gathered (after the engagement event, everyone in view "
                                                  f"is confirmed and grouped, no new face for {GATHER_S} s): face everyone"})
        clock = greet_t + 0.5

        def say(sid, text, reason):
            nonlocal clock
            d = round(len(text.split()) / C.TTS_WORDS_PER_S, 2)
            acts.append({"t": round(clock, 2), "kind": "say_to_group", "args": {"text": text, "id": sid},
                         "duration_s": d, "reason": reason})
            clock += d + PAUSE_S

        say("encounter.greet", dialogue.GREETING, "encounter: greet the whole group (neutral row: no age-based wording, D4)")
        asked, known, layers, answered, prior = [], Counter(), {v: [] for v in tv}, set(), {}
        say("encounter.intro", dialogue.INTRO, "encounter: introduce the robot to the group (no name, nothing about anyone)")
        for qid, text in dialogue.ICE:
            note(round(clock, 2), "question", qid=qid, how="script", llm_raw=None,
                 why="icebreaker: fixed script, no LLM; to the whole group (D7)")
            say(f"encounter.ice.{qid[4:]}", text, "encounter: icebreaker to the group; no follow-up to anyone who stays quiet (D2)")
            vis = [(v, scene.TALK_P[scene.TALK[v]], been[v], fav[v]) for v in tv]
            said = dialogue.ice_replies(qid, vis, names, ice_rng)
            for tid, text in said:
                clock += ice_rng.uniform(0.6, 1.4)
                d = _speech_s(text, VISITOR_WORDS_PER_S)
                speech.append((round(clock, 2), round(clock + d, 2), tid))
                kept = []
                if qid == "ice_visit" and (pt := dialogue.prior_tour(text)):
                    prior[tid] = pt
                    kept = [f"prior tour: {'yes' if pt == 'yes' else 'first time'}"]
                elif qid == "ice_fav":
                    got = dialogue.favourite(run_tour.GALLERY, text)
                    kept = [f"{k}:{t}" for k, t in got]
                    for k in got:
                        if k not in layers[tid]:
                            layers[tid].append(k)
                note(round(clock, 2), "answer", track_id=tid, qid=qid, text=text, duration_s=d, simulated=True,
                     layers=kept, dropped=[], llm_raw=None)
                clock += d
                answered.add(tid)
            if said:
                clock += 0.4
                say(f"encounter.ice.{qid[4:]}.react", dialogue.ICE_REACT[qid], "encounter: a reaction that fits any answer (no mood or "
                                                                              "history is judged), to the whole group (D7)")
            clock += PAUSE_S
        while tour_questions:
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
                clock += rng.uniform(0.6, 1.4)
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
            clock += PAUSE_S
        if tour_questions:
            say("encounter.ack", dialogue.ACK, "encounter: thank the group (never says who answered, D7)")
        lead_t = round(clock, 2)
        say("encounter.lead", dialogue.LEAD.format(stop["name"].lower()),
            "encounter: invite the group to the first exhibit (hand over to the tour)")
        t_end = round(clock, 1)                      # the walk starts here
        robot_move = scene.Move((rrx, rry), (rx, ry), t_end, C.ROBOT_WALK_MPS)
        vmove = {v: scene.Move(walk.spot[v], walk.slot[v], t_end + 0.8 + 0.35 * i, scene.APPROACH_MPS) for i, v in enumerate(tv)}
        t_final = round(max(max(m.t1 for m in vmove.values()) + TURN_S, robot_move.t1 + 1.5) + 0.3, 1)   # the handoff
        acts.append({"t": round(lead_t + 1.0, 2), "kind": "turn_body", "args": {"yaw": round(robot_move.heading, 3)},
                     "duration_s": 0.0, "reason": "encounter: turn toward the first exhibit while inviting the group"})
        acts.append({"t": t_end, "kind": "step_to", "args": {"x": rx, "y": ry, "to": spec.first_stop, "speed": C.ROBOT_WALK_MPS},
                     "duration_s": round(robot_move.t1 - robot_move.t0, 2),
                     "reason": f"encounter: walk to the first exhibit at {C.ROBOT_WALK_MPS} m/s (C.ROBOT_WALK_MPS); the visitors follow"})

        for t, f in frames:
            step(t, f)
            if t >= t_final:
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
        if v["track_id"] in prior:
            v["prior_tour"] = prior[v["track_id"]]            # extra key: his schema and store ignore it (nothing in his tour reads it yet)
    si["t"] = 0.0
    si["placeholder_fields"] = [f for f in si["placeholder_fields"] if f != "visitors[].responded_to_steer_invite"]
    schema.validate_start_impression(si)
    seed_of = {v["track_id"]: v for v in si["visitors"]}
    spec2 = dataclasses.replace(spec, visitors=[dataclasses.replace(
        v, cluster_id=seed_of[v.track_id]["cluster_id"], age_class=seed_of[v.track_id]["age_class"],
        age_conf=seed_of[v.track_id]["age_conf"]) for v in spec.visitors])
    with replaced_start_impression(lambda his, sim: si):
        tour, sim, tour_lines, _ = run_tour.run(name, spec=spec2)
    tour_records = tour.end_tour()

    # ---- encounter records, shifted so the handoff is t = 0
    sh = lambda t: round(t - t_final, 2)
    first = next(r for r in tour_records if r["type"] == "track")        # his t = 0 row: where everyone ends up
    yaw_end, vyaw_end = first["robot"]["yaw"], {v["id"]: v["body_yaw"] for v in first["visitors"]}
    acts.append({"t": robot_move.t1, "kind": "turn_body", "args": {"yaw": yaw_end}, "duration_s": 0.0,
                 "reason": "encounter: arrived at the first exhibit; turn to the group"})
    face_robot = lambda x, y: math.atan2(rry - y, rrx - x)
    prev = None                                   # monitoring: log each change of who is grouped with whom as perception works it out
    for t, per in samples:
        if t >= t_final:
            break
        groups = {}
        for v, sv in per.items():
            if sv["cluster"]:
                groups.setdefault(sv["cluster"], []).append(v)
        part = sorted(sorted(m) for m in groups.values())
        if part != prev and (part or any(not sv["cluster"] for sv in per.values())):
            note(t, "cluster update", groups=part, unsettled=sorted(v for v, sv in per.items() if not sv["cluster"]),
                 why="monitoring: companions are visitors who arrive together and stay close and move together for a few seconds "
                     "(group.py); a newcomer is unsettled until stable")
            prev = part
    note(greet_t, "clusters confirmed", why="everyone has arrived and every group is settled: this partition goes into the handoff")
    note(t_end, "leave", why="the lead-in is spoken: the robot walks to the first exhibit and the group follows")
    note(0.0, "place", name="Reception", desk=[round(rrx - 1.1, 2), rry, 0.5, 2.0],
         door=[round(cx, 2), round(min(y for _, y in walk.spot.values()) - scene.DOOR_M - 0.6, 2), 2.0])
    note(t_final, "clusters", partition={v["track_id"]: v["cluster_id"] for v in si["visitors"]},
         why="companion clusters at the handoff (proximity + co-movement over time)")
    note(t_final, "handoff", visitors=[{k: v[k] for k in ("track_id", "age_class", "age_conf", "age_band", "p_child",
                                                         "cluster_id", "pending_layers", "responded_to_steer_invite", "prior_tour") if k in v}
                                     for v in si["visitors"]],
         placeholder_fields=si["placeholder_fields"])
    heights = {v: tv[v].height for v in tv}

    def robot_yaw(t):
        y = scene.turn(yaw0, yaw_g, t, greet_t, greet_t + 1.2)
        y = scene.turn(y, robot_move.heading, t, lead_t + 1.0, lead_t + 2.2) if t >= lead_t + 1.0 else y
        return scene.turn(y, yaw_end, t, robot_move.t1, robot_move.t1 + 1.5) if t >= robot_move.t1 else y

    def visitor_at(v, t):
        """(x, y, yaw, attention): at the reception, then following the robot, then turned to the exhibit."""
        mv = vmove[v]
        if t < mv.t0:
            x, y, h = walk.at(v, t)
            return x, y, face_robot(x, y) if h is None else h, "robot" if h is None else "none"
        x, y = mv.at(t)
        yaw = scene.turn(face_robot(*mv.p0), mv.heading, t, mv.t0, mv.t0 + 0.8)
        if t >= mv.t1:
            return x, y, scene.turn(yaw, vyaw_end[v], t, mv.t1, mv.t1 + TURN_S), "robot"
        return x, y, yaw, "none"

    live = random.Random(seed + 7)                # liveliness has its own stream: the answers' rng (and the LLM prompts) stay as they were
    mates = {v: [o for o in tv if o != v and tv[o].cluster_id == tv[v].cluster_id] for v in tv}
    gaze = {v: scene.Gaze(live, mates[v], spec.first_stop) for v in tv}
    recs = []
    for t, per in samples:
        if t >= t_final:
            break
        speaking = {tid for t0, t1, tid in speech if t0 <= t < t1}
        robot_speaking = any(a["kind"] == "say_to_group" and a["t"] <= t < a["t"] + a["duration_s"] for a in acts)
        st_v = {v: visitor_at(v, t) for v in tv}
        rpos = robot_move.at(t)
        target = lambda att, x, y: ((rpos if att == "robot" else (st_v[att[8:]][0], st_v[att[8:]][1]) if att.startswith("visitor:")
                                     else (stop["x"], stop["y"]) if att.startswith("exhibit:") else (x + live.uniform(-1, 1), y - 1.5)))
        vis = []
        for v in tv:
            x, y, face, attn = st_v[v]
            mv = vmove[v]
            mode = ("arrived" if t >= mv.t1 else "walking" if t >= mv.t0 else "talk" if v in speaking else
                    "listen" if speaking else "robot_talks" if robot_speaking else "quiet")
            attn = gaze[v].step(t, mode, next(iter(speaking), None) if mode == "listen" else None)
            tx, ty = target(attn, x, y)
            head = math.atan2(ty - y, tx - x)
            x, y = x + live.gauss(0, 0.03), y + live.gauss(0, 0.03)                # his sim's noise
            face = face + live.gauss(0, 0.05)
            others = [{"x": st_v[o][0], "y": st_v[o][1], "height": heights[o]} for o in tv if o != v]
            s = per.get(v)
            vis.append({"id": v, "x": round(x, 3), "y": round(y, 3), "body_yaw": round(face, 3), "head_yaw": round(head + live.gauss(0, 0.08), 3),
                        "attention": attn, "speaking": v in speaking,
                        "in_formation": mock.FORMATION_RING[0] <= math.dist((x, y), (stop["x"], stop["y"])) <= mock.FORMATION_RING[1],
                        "los_exhibit": math.dist((x, y), (stop["x"], stop["y"])) > mock.FORMATION_RING[1] + 1.0 or       # far away: n/a
                                      mock.line_of_sight({"x": x, "y": y, "height": heights[v]}, (stop["x"], stop["y"]), others),
                        "cluster": (s or {}).get("cluster") or "?", "detected": s is not None,
                        "age_band": s["band"] if s else None, "age_conf": s["conf"] if s else None,
                        "group_status": "known" if s and s["cluster"] else "unknown"})
        bx, by = robot_move.at(t)
        recs.append({"type": "track", "t": sh(t), "robot": {"x": round(bx, 3), "y": round(by, 3), "yaw": round(robot_yaw(t), 3),
                                                            "speaking": robot_speaking}, "visitors": vis})
    recs += [{"type": "action", **a, "t": sh(a["t"])} for a in acts]
    recs += [dict(n, t=sh(n["t"])) for n in notes]
    recs.sort(key=lambda r: r["t"])
    info = {"t_encounter_s": t_final, "leave_t": sh(t_end), "greet_t": sh(greet_t), "event_t": sh(ev.t), "start_impression": si,
            "asked": asked, "layers": {k: v for k, v in layers.items() if v}, "answered": sorted(answered),
            "llm_model": getattr(llm, "model", "?")}
    # One profile per visitor, built in the encounter and updated through the tour: his store loads the seeded layers at the handoff, so
    # their "create" rows say t = 0; here each is dated when the visitor said it, so the log shows them being born in the conversation.
    origin = {}
    for n in notes:
        if n["note"] == "encounter: answer":
            for lay in n["layers"]:
                origin.setdefault((n["track_id"], lay), (sh(n["t"]), n["text"]))
    seeded = "pending layer from the start impression"
    retimed = []
    for r in tour_records:
        o = origin.get((r.get("track_id"), f"{r.get('kind')}:{r.get('target')}"))
        if r["type"] == "profile" and r.get("reason") == seeded and o:
            r = dict(r, t=o[0], reason=f'from the encounter: said "{o[1]}"')
        retimed.append(r)
    tour_records = retimed
    # the tour's visitor questions: his sim scripts their text, his end-of-tour log strips it (Q13); the replay shows and voices it as simulated
    said = [{"type": "note", "t": round(u["t"] - u["duration_s"], 2), "note": "tour: visitor said", "track_id": u["track_id"],
             "text": u["text"], "duration_s": u["duration_s"], "simulated": True} for u in tour_lines if u["type"] == "utterance"]
    return sorted(recs + tour_records + said, key=lambda r: r["t"]), sim.reactions, info
