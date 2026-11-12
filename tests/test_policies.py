"""Baseline policies (task 9): each switch does what it says, and ours is the default.
Run: python3 -m pytest tests  (or python3 tests/test_policies.py)"""
import json, os, sys
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
from sdc import content, policies, scenarios
from sdc.loop import Loop
from sdc.sim import run_closed_loop, run_tour
from sdc.tour import Tour

GALLERY = json.load(open(os.path.join(HERE, "data", "gallery.json")))
CONTENTS = content.load_all(GALLERY)


def s1(policy):
    loop, *_ = run_closed_loop(scenarios.s1_closed(), GALLERY,
                               lambda scn: Loop(GALLERY, scn.stop, scn.duration_s, contents=CONTENTS, policy=policy))
    return loop


def s2(policy):
    tour, *_ = run_tour(scenarios.s2_multi_stop(), GALLERY,
                        lambda s: Tour(GALLERY, s.first_stop, s.stop_durations, contents=CONTENTS, policy=policy))
    return tour


RUNS = {name: s1(p) for name, p in policies.ALL.items()}


def notes(loop, what):
    return [e for e in loop.ctrl.log if e["type"] == "note" and e["note"] == what]


def test_default_is_ours():
    assert Loop(GALLERY, "figurehead", 10, contents=CONTENTS).policy is policies.OURS


def test_only_ours_fixes_exclusion():
    for name, loop in RUNS.items():
        fixes = [a for a in loop.ctrl.actions if a.reason.startswith(("excluded", "still excluded"))]
        unresolved = loop.records()[-1]["p13_unresolved"]["share"]
        if name == "ours":
            assert fixes and unresolved == 0
        else:
            assert not fixes and unresolved > 0, name


def test_one_size_follows_the_script():
    loop = RUNS["one_size"]
    adds = notes(loop, "addition")
    order = [a.id for a in CONTENTS["figurehead"].additions]
    assert [n["addition"] for n in adds] == order[:len(adds)] and all(n["addressed"] == {} for n in adds)
    assert not any(a.reason.startswith("gaze balancing") for a in loop.ctrl.actions)
    assert loop.plan["next"] == GALLERY["route"]["branches"]["figurehead"][0] and not loop.plan["offer_choice"]


def test_engagement_has_no_damping_and_more_additions():
    loop = RUNS["engagement"]
    assert all(loop.profile.weight(t) == 1.0 for t in loop.profile.visitors)
    assert any(a.reason.startswith("gaze on the most engaged") for a in loop.ctrl.actions)
    assert len(notes(loop, "addition")) <= policies.ENGAGEMENT.max_additions


def test_everyone_answers_questions():
    for name, loop in RUNS.items():
        assert len(notes(loop, "question answered")) == 5, name


def test_baselines_dont_wait_on_moves():
    ours, base = s2(policies.OURS), s2(policies.ONE_SIZE)
    assert ours.records()[-1]["falling_behind"]["stops_started_without_everyone"] == 0
    assert base.records()[-1]["falling_behind"]["stops_started_without_everyone"] >= 1
    assert not any(a.kind == "slow_down" for a in base.actions)


if __name__ == "__main__":
    fails = 0
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            try:
                fn(); print("ok  ", name)
            except AssertionError as e:
                fails += 1; print("FAIL", name, e)
    sys.exit(1 if fails else 0)
