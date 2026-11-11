"""Decision layer on s1_one_stop (open loop) + unit checks for selector, uptake and planner.
Run: python3 -m pytest tests  (or python3 tests/test_decision.py)"""
import json, os, re, sys
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
from sdc import adapter, config as C, content, mock, scenarios
from sdc.adapter import Frame, Obs, Robot, StartImpression, Utterance
from sdc.decision import ACTION_KINDS, StopController, UptakeWindow, plan_next_stop, score_addition, select_addition
from sdc.loop import Loop
from sdc.profile import ProfileStore
from sdc.signals import Event

GALLERY = json.load(open(os.path.join(HERE, "data", "gallery.json")))
CONTENTS = content.load_all(GALLERY)
SCN = scenarios.s1_one_stop()
RECS = list(adapter.from_lines(mock.generate(SCN, GALLERY)))
SI = next(r for r in RECS if isinstance(r, StartImpression))
LOOP = Loop(GALLERY, SCN.stop, SCN.duration_s, contents=CONTENTS)
OUT = LOOP.run(RECS)
ACTS = LOOP.ctrl.actions
NOTES = [e for e in LOOP.ctrl.log if e["type"] == "note"]


def says():
    return [a for a in ACTS if a.kind == "say_to_group"]


def test_actions_valid_with_reasons():
    assert ACTS and all(a.kind in ACTION_KINDS and a.reason for a in ACTS)


def test_v2_exclusion_fixed_fast_and_quietly():
    ex = next(n for n in NOTES if n["note"] == "exclusion episode start")
    assert ex["track_id"] == "v2"
    fixes = [a for a in ACTS if "excluded" in a.reason]
    first = [a for a in fixes if a.t == ex["t"]]
    assert {a.kind for a in first} == {"gaze_at", "turn_body"}
    assert any(a.kind == "pause" and "talked over" in a.reason for a in fixes)
    assert sum(1 for a in ACTS if a.kind == "step_to") <= C.MAX_REPOSITIONS_PER_STOP
    assert not any(a.kind == "say_to_group" for a in fixes)               # never a direct question


def test_p13_no_unresolved_episode():
    assert OUT["summary"]["exclusion_unresolved"] == []
    assert [r["track_id"] for r in OUT["summary"]["exclusion_resolved"]] == ["v2"]


def test_reserved_v4_only_gaze_balancing():
    for a in ACTS:
        if a.args.get("target") == "visitor:v4":
            assert a.reason.startswith("gaze balancing"), a
    assert LOOP.profile.credit("v4") == 0 and LOOP.profile.layers("v4") == []


def test_additions_capped_and_unique():
    adds = [a.args["id"] for a in says() if ".add." in str(a.args["id"])]
    assert 1 <= len(adds) <= C.MAX_ADDITIONS_PER_STOP and len(set(adds)) == len(adds)


def test_every_question_answered_incl_talked_over():
    answered = [n["track_id"] for n in NOTES if n["note"] == "question answered"]
    assert sorted(answered) == ["v2", "v3", "v3", "v3", "v3"]


def test_speech_is_curated_and_to_the_group():
    ex = CONTENTS[SCN.stop]
    allowed = {s.text for s in ex.core} | {a.text for a in ex.additions} | {q["text"] for q in ex.qa} | \
              {ex.open_question["text"], ex.qa_fallback["text"]}
    for a in says():
        assert not re.search(r"\bv\d+\b", a.args["text"]), a
        if a.args["id"] == "between.choice" or "resume" in a.reason:
            continue
        assert a.args["text"] in allowed, a.args["text"]


def test_dominance_damped():
    w = {tid: LOOP.profile.weight(tid) for tid in LOOP.profile.visitors}
    assert min(w, key=w.get) == "v3" and w["v3"] < 0.5


def test_gaze_reaches_everyone():
    gazed = {a.args["target"][8:] for a in ACTS if a.kind == "gaze_at" and a.args["target"].startswith("visitor:")}
    assert gazed == {v.track_id for v in SCN.visitors}


def test_plan_has_next_stop():
    assert OUT["plan"]["next"] in GALLERY["route"]["branches"]["figurehead"]


# ---------------------------------------------------------------- unit checks

def _ev(kind, tid, target, t=1.0):
    return Event(kind, tid, t, t, t1=t, target=target, reason=f"test {kind}")


def test_selector_d8_and_no_repeat():
    ps = ProfileStore(SI)
    ps.on_event(_ev("point_ask", "v1", "figurehead.carving"), "figurehead")
    ps.on_event(_ev("point_ask", "v3", "figurehead.paint"), "figurehead")
    for i in range(4):
        ps.add_credit("v3", float(i), "test")
    ex = CONTENTS["figurehead"]
    a, score, per = select_addition(ex, ps, used=set())
    assert a.id == "figurehead.add.carving_detail"          # v3 steered a lot, so v1's interest wins
    assert select_addition(ex, ps, used={a.id, "figurehead.add.making_depth"})[0].id != a.id


def _frame(t, att, x=0.0, y=-2.3):
    o = Obs("v4", x, y, 1.57, 1.57, att, False, False, True, True, True, "c3", "adult", "standing", None, 0.95)
    return Frame(t, Robot(-2.2, -0.3, 0.0, False), {"v4": o})


def test_uptake_confirms_or_rescinds():
    a = CONTENTS["figurehead"].addition("figurehead.add.paint_detail")
    for att, want in (("feature:figurehead.paint", "confirmed"), ("none", "rescinded")):
        ps = ProfileStore(SI)
        ps.on_event(Event("linger", "v4", 0, 0, target="figurehead.paint", reason="test"), "figurehead")
        _, per = score_addition(a, ps)
        w = UptakeWindow(a, 0.0, 12.0, per, GALLERY, _frame(0.0, att))
        for i in range(121):
            w.on_frame(_frame(i / 10, att))
        ctrl = StopController("figurehead", CONTENTS["figurehead"], GALLERY, ps, 0.0, 60.0)
        ctrl.uptake = w
        ctrl._close_uptake(12.0)
        (l,) = ps.layers("v4")
        assert l.status == want and (ps.credit("v4") > 0) == (want == "confirmed")


def test_uptake_by_question():
    a = CONTENTS["figurehead"].addition("figurehead.add.paint_detail")
    ps = ProfileStore(SI)
    ps.on_event(Event("linger", "v4", 0, 0, target="figurehead.paint", reason="test"), "figurehead")
    _, per = score_addition(a, ps)
    w = UptakeWindow(a, 0.0, 12.0, per, GALLERY, _frame(0.0, "none"))
    w.on_utterance(Utterance(5.0, "v4", "Why red?", True, 1.0))
    assert "asked" in w.evidence("v4")


def test_planner_d1_and_pace():
    ps = ProfileStore(SI)
    ps.on_event(_ev("point_ask", "v5", None), "ship_model")    # confirmed exhibit_interest:ship_model
    summ = {"fatigued": ["v4", "v6"], "exclusion_unresolved": []}
    p = plan_next_stop("figurehead", GALLERY, ps, ["figurehead"], summ)
    assert p["next"] == "ship_model" and not p["offer_choice"] and p["pace"] == "slower"
    p = plan_next_stop("figurehead", GALLERY, ProfileStore(SI), ["figurehead"], {"fatigued": [], "exclusion_unresolved": []})
    assert p["offer_choice"] and p["pace"] == "same"


if __name__ == "__main__":
    fails = 0
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            try:
                fn(); print("ok  ", name)
            except AssertionError as e:
                fails += 1; print("FAIL", name, e)
    sys.exit(1 if fails else 0)
