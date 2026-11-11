"""Task 1 acceptance on s1_one_stop, plus a robustness check over other mock seeds.
Run: python3 -m pytest tests  (or python3 tests/test_signals.py)"""
import json, os, sys
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
from sdc import adapter, mock, scenarios
from sdc.signals import SignalLayer
import eval_signals

GALLERY = json.load(open(os.path.join(HERE, "data", "gallery.json")))


def run(seed=None):
    scn = scenarios.s1_one_stop()
    if seed is not None:
        scn.seed = seed
    events = SignalLayer(GALLERY, scn.stop).run(adapter.from_lines(mock.generate(scn, GALLERY)))
    return scn, events


SCN, EVENTS = run()
RES = eval_signals.evaluate(EVENTS, SCN.labels)


def of(kind, tid=None):
    return [e for e in EVENTS if e.kind == kind and (tid is None or e.track_id == tid)]


def test_v2_excluded_in_window_fast():
    ex = of("excluded", "v2")
    assert len(ex) == 1, ex
    assert 50 <= ex[0].t_detect <= 55, ex[0]       # inside 50-80, latency <= 5 s
    assert "position" in ex[0].detail


def test_no_excluded_for_anyone_else():
    assert [e.track_id for e in of("excluded")] == ["v2"]


def test_reserved_v4_has_no_events():
    assert [e for e in EVENTS if e.track_id == "v4"] == []


def test_v1_linger_and_approach():
    assert [e.target for e in of("linger", "v1")] == ["figurehead.carving"]
    assert len(of("approach", "v1")) == 1


def test_v3_point_ask_x4():
    assert len(of("point_ask", "v3")) == 4
    assert RES["rows"]["point_ask"]["recall"] == 1.0


def test_v5_drift_v6_fatigue():
    assert [e.target for e in of("drift", "v5")] == ["ship_model"]
    assert len(of("fatigue", "v6")) == 1


def test_all_labels_found():
    assert RES["fn"] == [], RES["fn"]


def test_talked_over_question_is_not_point_ask():
    assert of("point_ask", "v2") == []
    assert any(e.detail == "talked_over" for e in of("barrier", "v2"))


def test_every_event_has_reason():
    assert all(e.reason for e in EVENTS)


def test_robust_over_seeds():
    for seed in range(1, 11):
        scn, evs = run(seed)
        ex = [e for e in evs if e.kind == "excluded"]
        assert [e.track_id for e in ex] == ["v2"] and 50 <= ex[0].t_detect <= 55, (seed, ex)
        assert not [e for e in evs if e.track_id == "v4"], seed
        assert eval_signals.evaluate(evs, scn.labels)["fn"] == [], seed


if __name__ == "__main__":
    fails = 0
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            try:
                fn(); print("ok  ", name)
            except AssertionError as e:
                fails += 1; print("FAIL", name, e)
    sys.exit(1 if fails else 0)
