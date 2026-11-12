"""Replay visualiser build (task 8): one self-contained HTML with the log embedded.
Run: python3 -m pytest tests  (or python3 tests/test_replay.py)"""
import json, os, re, sys, tempfile
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
import make_replay
from sdc import metrics

RECS, SIM = make_replay.records_for("s1_closed")
HTML = make_replay.build(RECS, SIM)


def embedded(html):
    m = re.search(r"const D = (.*?);\n", html, re.S)
    return json.loads(m.group(1).replace("<\\/", "</"))


def test_self_contained():
    assert "/*DATA*/" not in HTML
    assert not re.search(r'<(script|link)[^>]+(src|href)=["\']https?:', HTML)   # no network
    assert HTML.count("</script>") == 1                                         # data can't close the tag
    assert len(HTML) < 3_000_000


def test_data_round_trip():
    d = embedded(HTML)
    assert d["meta"]["scenario"] == "s1_closed"
    assert len(d["tracks"]) == sum(1 for r in RECS if r["type"] == "track")
    assert d["measures"] == RECS[-1] and d["sim"]
    assert {e["kind"] for e in d["events"]} >= {"excluded", "barrier", "bid", "point_ask"}


def test_from_saved_anonymised_log():
    with tempfile.TemporaryDirectory() as tmp:
        p = os.path.join(tmp, "log.jsonl")
        metrics.write(metrics.anonymise(RECS), p)
        d = embedded(make_replay.build([json.loads(l) for l in open(p)]))
    ids = {v["id"] for r in d["tracks"] for v in r["visitors"]}
    assert ids == {f"P{i}" for i in range(1, 7)} and d["sim"] == []


def test_open_loop_builds():
    recs, sim = make_replay.records_for("s1_one_stop")
    assert sim == [] and embedded(make_replay.build(recs))["meta"]["scenario"] == "s1_one_stop"


if __name__ == "__main__":
    fails = 0
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            try:
                fn(); print("ok  ", name)
            except AssertionError as e:
                fails += 1; print("FAIL", name, e)
    sys.exit(1 if fails else 0)
