"""Content library checks.
Run: python3 -m pytest tests  (or python3 tests/test_content.py)"""
import json, os, sys
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
from sdc import content, scenarios

GALLERY = json.load(open(os.path.join(HERE, "data", "gallery.json")))
ALL = content.load_all(GALLERY)


def test_every_exhibit_valid():
    assert set(ALL) == {e["id"] for e in GALLERY["exhibits"]}
    for ex in ALL.values():
        assert content.validate(ex, GALLERY)


def test_each_feature_has_a_detail_and_each_exhibit_a_depth():
    for e in GALLERY["exhibits"]:
        ex = ALL[e["id"]]
        for f in e["features"]:
            assert any(a.serves_layer("feature_interest", f["id"]) for a in ex.additions), f["id"]
        assert any(a.serves_layer("depth", e["id"]) for a in ex.additions), e["id"]


def test_route_branches_have_previews():
    for stop, nexts in GALLERY["route"]["branches"].items():
        for n in nexts:
            assert any(a.type == "neighbour" and a.serves_layer("exhibit_interest", n)
                       for a in ALL[stop].additions), (stop, n)


def test_lengths_are_short():
    for ex in ALL.values():
        assert all(s.duration_s <= 25 for s in ex.core), ex.id
        assert all(a.duration_s <= 16 for a in ex.additions), [(a.id, a.duration_s) for a in ex.additions]


def test_s1_questions_answered():
    want = {"Is that a lady?": "figurehead.qa.who",
            "Is that the original paint?": "figurehead.qa.paint",
            "How old is it?": "figurehead.qa.age",
            "Who carved it?": "figurehead.qa.carver",
            "Was it on a real ship?": "figurehead.qa.real_ship"}
    for q, qid in want.items():
        assert ALL["figurehead"].answer(q)["id"] == qid, q
    s1_questions = [s.text for v in scenarios.s1_one_stop().visitors for s in v.speech if s.is_question]
    assert set(s1_questions) == set(want)
    assert ALL["figurehead"].answer("Can I touch it?")["id"] == "figurehead.qa.fallback"


def test_cue_times_inside_segment():
    for ex in ALL.values():
        for s in ex.core:
            assert all(0 <= t <= s.duration_s for t, _ in s.cue_times())


def test_d7_lint_catches_singling_out():
    ex = content.load("figurehead")
    ex.additions[0].text = "Your daughter seems to like the carving."
    try:
        content.validate(ex, GALLERY)
    except ValueError:
        return
    raise AssertionError("singling-out text accepted")


if __name__ == "__main__":
    fails = 0
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            try:
                fn(); print("ok  ", name)
            except AssertionError as e:
                fails += 1; print("FAIL", name, e)
    sys.exit(1 if fails else 0)
