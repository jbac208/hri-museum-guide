"""Multi-stop tour (task 7, s2_multi_stop): stops, choices, transitions, carry-over.
Run: python3 -m pytest tests  (or python3 tests/test_tour.py)"""
import json, os, sys
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
from sdc import config as C, content, scenarios
from sdc.signals import seed_weight
from sdc.sim import run_tour
from sdc.tour import Tour

GALLERY = json.load(open(os.path.join(HERE, "data", "gallery.json")))
CONTENTS = content.load_all(GALLERY)


def run(seed=None):
    spec = scenarios.s2_multi_stop()
    if seed is not None:
        spec.seed = seed
    return run_tour(spec, GALLERY, lambda s: Tour(GALLERY, s.first_stop, s.stop_durations, contents=CONTENTS,
                                                   scenario=s.name))


TOUR, SIM, LINES, OUT = run()
LOG = TOUR.decision_log()
NOTES = [e for e in LOG if e["type"] == "note"]
M = TOUR.records()[-1]


def notes(what):
    return [n for n in NOTES if n["note"] == what]


def test_three_stops_and_close():
    assert OUT["stops"] == ["figurehead", "ship_model", "sea_chest"]
    assert notes("tour close (owner still open: HANDOFF §8)")
    assert [n["stop_index"] for n in notes("stop start")] == [0, 1, 2]


def test_first_choice_by_d1_scores():
    p = OUT["plans"][0]
    assert p["next"] == "ship_model" and not p["offer_choice"]
    assert p["scores"]["ship_model"] > p["scores"]["compass"]


def test_second_choice_is_p12_read_from_movement():
    p = OUT["plans"][1]
    assert p["offer_choice"] and set(p["choice"]) == {"compass", "sea_chest"}
    read = notes("two-way choice read")
    assert read and read[0]["pick"] == "sea_chest" == p["next"]
    offer = [a for a in TOUR.actions if a.args.get("id") == "between.choice"]
    assert len(offer) == 1 and "?" not in offer[0].args["text"]          # an offer, not a question or vote


def test_falling_behind_slows_and_waits():
    fb = notes("falling behind")
    assert fb and fb[0]["track_id"] == "v6"
    slow = [a for a in TOUR.actions if a.kind == "slow_down" and a.t >= fb[0]["t"]]
    wait = [a for a in TOUR.actions if a.kind == "pause" and "everyone arrived" in a.reason]
    assert slow and wait and wait[0].t >= slow[0].t
    nxt = notes("stop start")[2]
    assert nxt["t"] >= wait[0].t + wait[0].duration_s - 0.2                 # the stop starts after the wait


def test_seed_fades_by_third_stop():
    assert seed_weight(0) == C.SEED_WEIGHT_S and seed_weight(1) == C.SEED_WEIGHT_S / 2 and seed_weight(2) == 0
    st = TOUR.signals.v["v1"]
    assert st.glance_rate.prior_weight == 0 and st.dist[True].prior_weight == 0


def test_credit_and_weights_carry_across_stops():
    credits = [p for p in TOUR.profile.log if p["op"] == "credit" and p["track_id"] == "v3"]
    stops = notes("stop start")
    assert any(c["t"] < stops[1]["t"] for c in credits) and any(c["t"] > stops[2]["t"] for c in credits)
    assert TOUR.profile.weight("v3") == min(TOUR.profile.weight(t) for t in TOUR.profile.visitors)


def test_child_excluded_at_stop_two_and_resolved():
    ep = [n for n in notes("exclusion episode start") if "position" in n["barriers"]]
    s2, s3 = notes("stop start")[1]["t"], notes("stop start")[2]["t"]
    assert ep and ep[0]["track_id"] == "v2" and s2 <= ep[0]["t"] < s3
    assert M["p13_unresolved"]["share"] == 0.0


def test_events_dont_leak_across_stops():
    for e in TOUR.signals.events:
        assert e.t1 is not None and e.t1 >= e.t_detect
    for n in notes("transition start"):     # nothing but 'behind' barriers starts during a move
        arr = next(s["t"] for s in notes("stop start") if s["t"] > n["t"])
        during = [e for e in TOUR.signals.events if n["t"] < e.t_detect < arr]
        assert all(e.kind == "barrier" and e.detail == "behind" for e in during), during


def test_no_addition_repeated_and_cap_per_stop():
    adds = [n["addition"] for n in NOTES if n["note"] == "addition"]
    assert len(adds) == len(set(adds))
    for s in TOUR.controllers:
        assert len(s.summary["additions"]) <= C.MAX_ADDITIONS_PER_STOP


def test_measures_per_stop():
    ps = M["steering_uptake"]["per_stop"]
    assert [p["stop"] for p in ps] == OUT["stops"]
    assert sum(p["detected"] for p in ps) == M["steering_uptake"]["detected"]
    assert M["falling_behind"]["who"] == ["v6"]


def test_privacy_end_tour():
    t, *_ = run()
    kept = t.end_tour()
    assert t.profile.visitors == {} and t.profile.layers() == [] and t.signals.v == {}
    assert "[speech]" in json.dumps(kept) and "Whose chest was it?" not in json.dumps(kept)


def test_replay_builds_for_tour():
    import make_replay, re
    html = make_replay.build(TOUR.records(), SIM.reactions)
    d = json.loads(re.search(r"const D = (.*?);\n", html, re.S).group(1).replace("<\\/", "</"))
    assert len([n for n in d["notes"] if n["note"] == "stop start"]) == 3


def test_robust_over_seeds():
    for seed in (2, 3, 4):
        t, _, _, out = run(seed)
        m = t.records()[-1]
        assert len(out["stops"]) == 3, seed
        assert m["p13_unresolved"]["share"] == 0.0, seed


if __name__ == "__main__":
    fails = 0
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            try:
                fn(); print("ok  ", name)
            except AssertionError as e:
                fails += 1; print("FAIL", name, e)
    sys.exit(1 if fails else 0)
