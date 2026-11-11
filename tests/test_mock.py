"""Checks that the mock stream is valid and that its derived fields match the script.
Run: python3 -m pytest tests  (or python3 tests/test_mock.py)"""
import json, os, sys
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
from sdc import mock, schema, scenarios

GALLERY = json.load(open(os.path.join(HERE, "data", "gallery.json")))
LINES = mock.generate(scenarios.s1_one_stop(), GALLERY)
FRAMES = [o for o in LINES if o["type"] == "frame"]


def vis(frame, tid):
    return next(v for v in frame["visitors"] if v["track_id"] == tid)


def frac(tid, key, t0, t1, value=True):
    fs = [vis(f, tid)[key] == value for f in FRAMES if t0 <= f["t"] < t1]
    return sum(fs) / len(fs)


def test_schema_valid():
    schema.validate_stream(LINES)


def test_child_blocked_then_resolved():
    assert frac("v2", "los_exhibit", 0, 82, False) > 0.95
    assert frac("v2", "in_formation", 0, 82, False) > 0.95
    assert frac("v2", "los_exhibit", 87, 150, True) > 0.95
    assert frac("v2", "in_formation", 87, 150, True) > 0.95


def test_child_talked_over():
    assert frac("v2", "overlapped", 72, 73.5) == 1.0


def test_everyone_else_can_see():
    for tid in ("v1", "v3", "v4", "v6"):
        assert frac(tid, "los_exhibit", 0, 150) > 0.95, tid


def test_reserved_is_quiet():
    assert frac("v4", "speaking", 0, 150) == 0.0
    assert all(vis(f, "v4")["pointing_at"] is None for f in FRAMES)


def test_parent_questions():
    utt = [o for o in LINES if o["type"] == "utterance" and o["track_id"] == "v3"]
    assert len(utt) == 4 and all(u["is_question"] for u in utt)


def test_linger_attention():
    assert frac("v1", "attention", 70, 115, "feature:figurehead.carving") > 0.9


def test_fatigue_posture():
    assert frac("v6", "posture", 110, 150, "leaning") == 1.0


def test_schema_rejects_bad_frame():
    bad = json.loads(json.dumps(FRAMES[0]))
    bad["visitors"][0]["attention"] = "somewhere"
    try:
        schema.validate_line(bad)
    except schema.SchemaError:
        return
    raise AssertionError("bad attention accepted")


if __name__ == "__main__":
    fails = 0
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            try:
                fn(); print("ok  ", name)
            except AssertionError as e:
                fails += 1; print("FAIL", name, e)
    sys.exit(1 if fails else 0)
