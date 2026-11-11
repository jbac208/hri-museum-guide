"""Profile store on s1_one_stop + unit checks.
Run: python3 -m pytest tests  (or python3 tests/test_profile.py)"""
import json, os, sys
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
from sdc import adapter, config as C, mock, scenarios
from sdc.adapter import StartImpression, VisitorSeed
from sdc.profile import ProfileStore
from sdc.signals import Event, SignalLayer

GALLERY = json.load(open(os.path.join(HERE, "data", "gallery.json")))
SCN = scenarios.s1_one_stop()
RECS = list(adapter.from_lines(mock.generate(SCN, GALLERY)))
EVENTS = SignalLayer(GALLERY, SCN.stop).run(RECS)
SI = next(r for r in RECS if isinstance(r, StartImpression))


def s1_store():
    ps = ProfileStore(SI)
    for ev in sorted(EVENTS, key=lambda e: e.t_detect):
        ps.on_event(ev, SCN.stop)
    return ps


def keyset(ps, tid):
    return {(l.kind, l.target, l.status) for l in ps.layers(tid)}


def test_s1_layers():
    ps = s1_store()
    assert keyset(ps, "v1") == {("feature_interest", "figurehead.carving", "pending"),
                                ("depth", "figurehead", "pending")}
    assert keyset(ps, "v3") == {("feature_interest", "figurehead.paint", "confirmed"),
                                ("exhibit_interest", "figurehead", "confirmed")}
    assert keyset(ps, "v5") == {("exhibit_interest", "ship_model", "pending")}
    assert keyset(ps, "v2") == {("exhibit_interest", "figurehead", "confirmed")}   # Q3: talked-over question
    for tid in ("v4", "v6"):                    # reserved; fatigue makes no layer
        assert ps.layers(tid) == [], tid


def test_every_change_has_reason():
    ps = s1_store()
    assert ps.log and all(e["reason"] for e in ps.log)


def test_cluster_from_start_impression():
    assert sorted(s1_store().cluster("c2")) == ["v2", "v3"]


def _ev(kind, tid="v1", t=1.0, target="figurehead.carving"):
    return Event(kind, tid, t, t, t1=t, target=target, reason=f"test {kind}")


def test_repeat_evidence_strengthens_pending():
    ps = ProfileStore(SI)
    ps.on_event(_ev("linger"), "figurehead")
    ps.on_event(_ev("linger", t=20), "figurehead")
    (l,) = ps.layers("v1")
    c = C.LAYER_EVENT_CONF["linger"]
    assert l.status == "pending" and abs(l.confidence - (1 - (1 - c) ** 2)) < 1e-9
    assert abs(l.strength - C.PENDING_WEIGHT * l.confidence) < 1e-9


def test_confirm_rescind_and_d6():
    ps = ProfileStore(SI)
    ps.on_event(_ev("linger"), "figurehead")
    (l,) = ps.layers("v1")
    ps.rescind(l.id, 5.0, "no uptake in window")
    assert l.status == "rescinded" and l.strength == 0
    ps.on_event(_ev("linger", t=30), "figurehead")          # same evidence again: not reopened (D6)
    assert l.status == "rescinded" and ps.log[-1]["op"] == "ignored"
    ps.end_stop(40.0)                                        # removed between stops
    assert ps.layers("v1") == []
    ps.on_event(_ev("linger", t=50), "ship_model")
    assert ps.layers("v1")[0].status == "pending"


def test_point_ask_confirms():
    ps = ProfileStore(SI)
    ps.on_event(_ev("linger"), "figurehead")
    (l,) = ps.layers("v1")
    ps.on_event(_ev("point_ask", t=3), "figurehead")
    assert l.status == "confirmed" and l.confidence == 1.0 and l.strength == 1.0


def test_credit_and_weight_d8():
    ps = ProfileStore(SI)
    assert ps.weight("v3") == 1.0
    for i in range(4):
        ps.add_credit("v3", float(i), "answered question")
    assert ps.credit("v3") == 4
    assert abs(ps.weight("v3") - 1 / (1 + C.LAMBDA_DOMINANCE * 4)) < 1e-9
    assert ps.weight("v3") < ps.weight("v4") == 1.0


def test_seed_layers_pending():
    seed = VisitorSeed("v9", "adult", 0.9, "c9", 2.0, 4.0, 0.05,
                       [{"kind": "feature_interest", "target": "figurehead.paint"}], False)
    ps = ProfileStore(StartImpression(0.0, {"v9": seed}, 1, 0.0))
    (l,) = ps.layers("v9")
    assert l.status == "pending" and l.confidence == C.SEED_LAYER_CONF


def test_end_tour_discards_everything():
    ps = s1_store()
    ps.add_credit("v3", 100.0, "x")
    out = ps.end_tour(150.0)
    assert out["layers_discarded"] > 0
    assert ps.visitors == {} and ps.log == [] and ps.layers() == []


if __name__ == "__main__":
    fails = 0
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            try:
                fn(); print("ok  ", name)
            except AssertionError as e:
                fails += 1; print("FAIL", name, e)
    sys.exit(1 if fails else 0)
