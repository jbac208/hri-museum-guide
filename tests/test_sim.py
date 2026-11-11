"""Closed-loop sim (task 5): the robot's actions change what visitors do, and the loop sees it.
Run: python3 -m pytest tests  (or python3 tests/test_sim.py)"""
import json, os, sys
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
from sdc import content, scenarios
from sdc.loop import Loop
from sdc.sim import run_closed_loop

GALLERY = json.load(open(os.path.join(HERE, "data", "gallery.json")))
CONTENTS = content.load_all(GALLERY)
SEEDS = range(1, 11)


def run(spec):
    return run_closed_loop(spec, GALLERY, lambda scn: Loop(GALLERY, scn.stop, scn.duration_s, contents=CONTENTS))


def spec(seed=None, **edit):
    s = scenarios.s1_closed()
    if seed is not None:
        s.seed = s.scenario.seed = seed
    for k, v in edit.items():
        setattr(s, k, v)
    return s


LOOP, SIM, LINES, OUT = run(spec())
NOTES = [e for e in LOOP.ctrl.log if e["type"] == "note"]
FRAMES = [l for l in LINES if l["type"] == "frame"]


def test_stream_valid_and_deterministic():
    _, _, lines2, _ = run(spec())                       # run_closed_loop validates every line
    assert lines2 == LINES


def test_frames_follow_the_robot():
    says = [a for a in LOOP.ctrl.actions if a.kind == "say_to_group"]
    for a in says[:5]:
        mid = a.t + a.duration_s / 2
        f = min(FRAMES, key=lambda f: abs(f["t"] - mid))
        assert f["robot"]["speaking"], a
    turns = [a for a in LOOP.ctrl.actions if a.kind == "turn_body"]
    f = next(f for f in FRAMES if f["t"] > turns[-1].t + 0.2)
    assert f["robot"]["yaw"] == turns[-1].args["yaw"]


def test_opening_the_formation_lets_the_child_in():
    ep = [r for r in OUT["summary"]["exclusion_resolved"] if r["track_id"] == "v2"]
    assert ep and ep[0]["time_to_resolve_s"] <= 10
    late = [next(v for v in f["visitors"] if v["track_id"] == "v2") for f in FRAMES if f["t"] > 70]
    assert all(v["in_formation"] and v["los_exhibit"] for v in late)


def test_without_a_reaction_the_episode_stays_unresolved():
    _, _, _, out = run(spec(join_xy={}))
    assert out["summary"]["exclusion_unresolved"] == ["v2"]          # P13 misery is visible
    assert out["plan"]["pace"] == "slower"


def test_child_interrupts_robot_then_gets_floor_and_answer():
    ev = [n for n in NOTES if n["note"] == "exclusion episode start" and "talked_over" in n["barriers"]]
    assert ev and ev[0]["track_id"] == "v2"
    pauses = [a for a in LOOP.ctrl.actions if a.kind == "pause" and "talked over" in a.reason]
    answered = [n for n in NOTES if n["note"] == "question answered" and n["track_id"] == "v2"]
    assert pauses and answered and answered[0]["t"] >= pauses[0].t


def test_resume_restarts_cut_sentence():
    res = [a for a in LOOP.ctrl.actions if a.args.get("resume")]
    for a in res:
        full = next(x for x in LOOP.ctrl.actions if x.args.get("id") == a.args["id"] and x.args.get("cut_at"))
        assert full.args["text"].endswith(a.args["text"]) and a.args["text"][0].isupper()


def test_uptake_follows_hidden_interest():
    hit = miss = fa = cr = 0
    for seed in SEEDS:
        s = spec(seed)
        loop, *_ = run(s)
        for e in loop.ctrl.log:
            if e.get("note") not in ("uptake", "no uptake"):
                continue
            a = CONTENTS["figurehead"].addition(e["addition"])
            match = bool({(x["kind"], x["target"]) for x in a.serves} & s.interests.get(e["track_id"], set()))
            up = e["note"] == "uptake"
            hit += match and up; miss += match and not up; fa += (not match) and up; cr += (not match) and not up
    assert hit / (hit + miss) >= 0.85, (hit, miss)
    assert fa / (fa + cr) <= 0.3, (fa, cr)


def test_misread_is_rescinded():
    """v1 approaches (-> pending depth) but has no hidden interest and doesn't linger."""
    rescinded = 0
    for seed in SEEDS:
        s = spec(seed)
        s.interests["v1"] = set()
        next(v for v in s.scenario.visitors if v.track_id == "v1").windows = []
        loop, *_ = run(s)
        rescinded += any(l["op"] == "rescinded" and l["track_id"] == "v1" for l in loop.profile.log)
    assert rescinded >= 8, rescinded


def test_dominance_damped_every_seed():
    for seed in SEEDS:
        loop, *_ = run(spec(seed))
        w = {t: loop.profile.weight(t) for t in loop.profile.visitors}
        assert min(w, key=w.get) == "v3", (seed, w)


def test_p13_and_caps_every_seed():
    for seed in SEEDS:
        loop, _, _, out = run(spec(seed))
        assert out["summary"]["exclusion_unresolved"] == [], seed
        adds = out["summary"]["additions"]
        assert len(adds) <= 2 and len(set(adds)) == len(adds), seed


if __name__ == "__main__":
    fails = 0
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            try:
                fn(); print("ok  ", name)
            except AssertionError as e:
                fails += 1; print("FAIL", name, e)
    sys.exit(1 if fails else 0)
