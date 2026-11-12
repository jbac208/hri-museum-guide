"""Event log + live measures (task 6).
Run: python3 -m pytest tests  (or python3 tests/test_metrics.py)"""
import json, os, sys, tempfile
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
from sdc import adapter, config as C, content, metrics, mock, scenarios
from sdc.loop import Loop
from sdc.sim import run_closed_loop

GALLERY = json.load(open(os.path.join(HERE, "data", "gallery.json")))
CONTENTS = content.load_all(GALLERY)


def closed(**edit):
    s = scenarios.s1_closed()
    for k, v in edit.items():
        setattr(s, k, v)
    loop, *_ = run_closed_loop(s, GALLERY, lambda scn: Loop(GALLERY, scn.stop, scn.duration_s, contents=CONTENTS,
                                                             scenario=scn.name))
    return loop, loop.records()


LOOP, RECS = closed()
M = RECS[-1]


def test_log_shape():
    assert RECS[0]["type"] == "meta" and M["type"] == "measures"
    types = {r["type"] for r in RECS}
    assert types == {"meta", "track", "event", "profile", "action", "note", "measures"}
    ts = [r["t"] for r in RECS]
    assert ts == sorted(ts)
    tracks = [r for r in RECS if r["type"] == "track"]
    assert abs(len(tracks) - tracks[-1]["t"] * C.LOG_TRACK_HZ) <= 1.5      # the stop may overrun (Q11)


def test_speech_kept_live_and_stripped_at_tour_end():
    """Q13: the live log keeps question text; end_tour() returns a copy without it and wipes state."""
    utterances = [s.text for v in scenarios.s1_one_stop().visitors for s in v.speech]
    loop, live = closed()
    assert any(u in json.dumps(live) for u in utterances)
    kept = loop.end_tour()
    blob = json.dumps(kept) + json.dumps([e.reason for e in loop.signals.events])
    for u in utterances:
        assert u not in blob, u
    assert loop.profile.visitors == {} and loop.signals.v == {}
    assert metrics.measures(kept[:-1]) == {k: v for k, v in kept[-1].items() if k not in ("type", "t")}


def test_measures_from_log_alone():
    with tempfile.TemporaryDirectory() as d:
        p = os.path.join(d, "log.jsonl")
        metrics.write(RECS, p)
        back = [json.loads(l) for l in open(p)]
    assert metrics.measures(back[:-1]) == {k: v for k, v in M.items() if k not in ("type", "t")}


def test_steering_uptake():
    su = M["steering_uptake"]
    assert su["detected"] >= su["acted_on"] > 0
    assert su["share"] == round(su["acted_on"] / su["detected"], 3)
    answered = [a for a in su["acted"] if a["by"].startswith("answered")]
    notes = [r for r in RECS if r["type"] == "note" and r["note"] == "question answered"]
    assert len(answered) == len(notes) >= 4     # each answer credits exactly one question
    questions = [r for r in RECS if r["type"] == "event" and r["kind"] == "point_ask" and "question" in r["reason"]]
    assert len(questions) == 5                   # v2's + v3's four; v3's last comes too late to answer


def test_exclusion_and_p13():
    ex = M["exclusion"]
    assert ex["episodes"] == ex["resolved"] >= 1 and ex["unresolved"] == 0
    assert all(t <= 10 for t in ex["time_to_resolve_s"])
    assert M["p13_unresolved"]["share"] == 0.0


def test_p13_visible_when_unresolved():
    _, recs = closed(join_xy={})
    m = recs[-1]
    assert m["p13_unresolved"]["visitors_with_unresolved"] == ["v2"]
    assert m["p13_unresolved"]["share"] == round(1 / 6, 3)


def test_misread_rate():
    mr = M["misread_rate"]
    assert mr["tested"] >= 1 and mr["rate"] == round(mr["rescinded"] / mr["tested"], 3)


def test_dominance_share():
    d = M["dominance_share"]
    assert d["top_visitor"] == "v3"
    assert d["share"] == round(max(d["acted_per_visitor"].values()) / M["steering_uptake"]["acted_on"], 3)


def test_anonymise():
    anon = metrics.anonymise(RECS)
    blob = json.dumps(anon)
    for tid in ("v1", "v2", "v3", "v4", "v5", "v6"):
        assert f'"{tid}"' not in blob and f"visitor:{tid}" not in blob
    assert '"P1"' in blob and metrics.measures(anon[:-1])["p13_unresolved"]["share"] == 0.0


def test_open_loop_log_works_too():
    scn = scenarios.s1_one_stop()
    loop = Loop(GALLERY, scn.stop, scn.duration_s, contents=CONTENTS, scenario=scn.name)
    loop.run(adapter.from_lines(mock.generate(scn, GALLERY)))
    m = loop.records()[-1]
    assert m["exclusion"]["episodes"] == 1 and m["p13_unresolved"]["share"] == 0.0


if __name__ == "__main__":
    fails = 0
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            try:
                fn(); print("ok  ", name)
            except AssertionError as e:
                fails += 1; print("FAIL", name, e)
    sys.exit(1 if fails else 0)
