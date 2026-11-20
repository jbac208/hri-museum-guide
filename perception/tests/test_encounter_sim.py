"""The encounter phase end to end (simulation): ids are the tour's ids, clusters come from our perception, the handoff is
a valid start_impression, and without the conversation's layers his tour is unchanged."""
import math
import os

import pytest

pytest.importorskip("numpy")

import run_tour  # noqa: E402
from sdc import config as C, schema  # noqa: E402

from perception.encounter_sim import dialogue  # noqa: E402
from perception.encounter_sim.llm import FakeLLM, ReplayLLM  # noqa: E402
from perception.encounter_sim.replay import recording_path  # noqa: E402
from perception.encounter_sim.run import run  # noqa: E402


@pytest.fixture(scope="module")
def fake():
    return run("s2_multi_stop", llm=FakeLLM(), seed=1)


def test_handoff_ids_clusters_and_schema(fake):
    recs, _, info = fake
    si = info["start_impression"]
    schema.validate_start_impression(si)
    assert si["t"] == 0.0 and [v["track_id"] for v in si["visitors"]] == ["v1", "v2", "v3", "v4", "v5", "v6"]
    groups = {}
    for v in si["visitors"]:
        groups.setdefault(v["cluster_id"], set()).add(v["track_id"])
    assert sorted(map(sorted, groups.values())) == [["v1"], ["v2", "v3"], ["v4"], ["v5", "v6"]]
    assert [v["age_class"] for v in si["visitors"]] == ["adult", "child", "adult", "adult", "adult", "adult"]


def test_encounter_is_before_the_tour_and_greets_after_the_event(fake):
    recs, _, info = fake
    enc = [r for r in recs if r["type"] in ("track", "action", "note") and str(r.get("note", "")).startswith("encounter")
           or (r["type"] == "action" and str(r["args"].get("id", "")).startswith("encounter."))]
    assert enc and all(r["t"] <= 0 for r in enc)
    assert info["event_t"] < info["greet_t"] < 0


def test_robot_speech_is_only_menu_text_and_quiet_visitors_get_nothing(fake):
    recs, _, info = fake
    m = dialogue.menu(run_tour.GALLERY, "figurehead")
    allowed = ({q.text for q in m} | {dialogue.GREETING, dialogue.INTRO, dialogue.ACK, dialogue.LEAD.format("ship's figurehead")}
               | {t for _, t in dialogue.ICE} | set(dialogue.ICE_REACT.values()))
    says = [r for r in recs if r["type"] == "action" and r["kind"] == "say_to_group" and r["t"] < 0]
    assert says and all(a["args"]["text"] in allowed for a in says)
    assert len([a for a in says if a["args"]["id"].startswith("encounter.q.")]) <= dialogue.BUDGET
    assert "v4" not in info["answered"]                                   # reserved: never answers, never pressed
    si = {v["track_id"]: v for v in info["start_impression"]["visitors"]}
    for tid, v in si.items():
        assert bool(v["pending_layers"]) <= (tid in info["answered"])    # layers only from what was said
        assert v["responded_to_steer_invite"] == (tid in info["answered"])


def test_without_the_conversations_layers_his_tour_is_unchanged():
    recs, _, _ = run("s2_multi_stop", llm=FakeLLM(), seed=1, pending=False)
    tour, _, _, _ = run_tour.run("s2_multi_stop")
    his = tour.end_tour()
    stops = lambda rs: [r["stop"] for r in rs if r["type"] == "note" and r["note"] == "stop start"]
    measures = lambda rs: {k: v for k, v in rs[-1].items() if k != "t"}
    assert stops(recs) == stops(his)
    assert measures(recs) == measures(his)


@pytest.mark.skipif(not os.path.exists(recording_path("s2_multi_stop", 1)), reason="no recorded LLM run")
def test_recorded_llm_run_replays_and_a_changed_prompt_fails_loudly():
    recs, _, info = run("s2_multi_stop", llm=ReplayLLM(recording_path("s2_multi_stop", 1)), seed=1)
    assert info["llm_model"] == "qwen2.5:7b" and info["asked"] == ["depth", "features"]
    dropped = [d for r in recs if r["type"] == "note" and r["note"] == "encounter: answer" for d in r["dropped"]]
    assert "depth:figurehead (quote_does_not_name_it)" in dropped        # the real LLM's error, caught by the guard
    with pytest.raises(KeyError):
        run("s2_multi_stop", llm=ReplayLLM(recording_path("s2_multi_stop", 1)), seed=2)   # other replies, other prompts


def test_the_walk_to_stop_1_is_smooth_and_ends_where_his_tour_starts(fake):
    recs, _, info = fake
    tr = [r for r in recs if r["type"] == "track"]
    enc, first = [r for r in tr if r["t"] < 0], next(r for r in tr if r["t"] >= 0)
    walk = [r for r in enc if r["t"] >= info["leave_t"]]
    assert walk and info["leave_t"] < -5
    assert math.dist((enc[-1]["robot"]["x"], enc[-1]["robot"]["y"]), (first["robot"]["x"], first["robot"]["y"])) < 0.1
    for a, b in zip(enc[-1]["visitors"], first["visitors"]):
        assert math.dist((a["x"], a["y"]), (b["x"], b["y"])) < 0.15                  # his sim adds a little jitter
    speed = lambda p, q, k: math.dist((p[k]["x"], p[k]["y"]), (q[k]["x"], q[k]["y"])) / (q["t"] - p["t"])
    for p, q in zip(enc, enc[1:]):
        assert speed(p, q, "robot") <= C.ROBOT_WALK_MPS + 0.05                       # no teleporting, no sprinting
    for p, q in zip(enc, enc[5:]):                                                    # visitors carry his 3 cm noise: look 1 s apart
        assert all(math.dist((a["x"], a["y"]), (b["x"], b["y"])) / (q["t"] - p["t"]) <= 1.0
                   for a, b in zip(p["visitors"], q["visitors"]))


def test_visitors_are_lively_like_his_tour(fake):
    recs, _, _ = fake
    enc = [r for r in recs if r["type"] == "track" and -120 <= r["t"] < -25]         # the conversation, greeting to the last question: all at the reception
    for tid in ("v1", "v3"):
        vs = [v for r in enc for v in r["visitors"] if v["id"] == tid]
        assert len({v["attention"] for v in vs}) >= 3                                  # robot, companions / gallery ahead, flicker
        assert max(v["head_yaw"] for v in vs) - min(v["head_yaw"] for v in vs) > 1.0
        assert any(v["attention"].startswith("visitor:") for v in vs) or tid == "v1"   # v1 has no companion to look at


def test_companion_groups_are_assigned_step_by_step_as_people_arrive(fake):
    recs, _, info = fake
    enc = [r for r in recs if r["type"] == "track" and r["t"] < 0]
    first_known = {}
    for r in enc:
        for v in r["visitors"]:
            if v["group_status"] == "known":
                first_known.setdefault(v["id"], r["t"])
    assert set(first_known) == {f"v{i}" for i in range(1, 7)}
    assert len({round(t) for t in first_known.values()}) >= 4                     # not all at once
    assert first_known["v1"] < first_known["v3"] < first_known["v6"]                # in arrival order
    assert max(first_known.values()) <= info["greet_t"]                               # everyone settled before the greeting
    ups = [r for r in recs if r["type"] == "note" and r["note"] == "encounter: cluster update"]
    assert len(ups) >= 4 and ups[-1]["groups"] == [["v1"], ["v2", "v3"], ["v4"], ["v5", "v6"]]


def test_the_encounter_opens_with_a_welcome_and_small_talk_before_the_tour_questions(fake):
    recs, _, info = fake
    ids = [r["args"]["id"] for r in recs if r["type"] == "action" and r["kind"] == "say_to_group" and r["t"] < 0]
    assert ids[:2] == ["encounter.greet", "encounter.intro"]
    ice = [i for i in ids if i.startswith("encounter.ice.") and not i.endswith(".react")]
    assert ice == ["encounter.ice.visit", "encounter.ice.day", "encounter.ice.fav"]
    assert max(ids.index(i) for i in ice) < min(ids.index(i) for i in ids if i.startswith("encounter.q."))
    qs = [r for r in recs if r["type"] == "note" and r["note"] == "encounter: question" and str(r["qid"]).startswith("ice_")]
    assert len(qs) == 3 and all(q["how"] == "script" and q["llm_raw"] is None for q in qs)      # no LLM call for small talk
    assert info["asked"] == ["depth", "features"]                                                 # the LLM's budget is untouched
    said = [r for r in recs if r["type"] == "note" and r["note"] == "encounter: answer" and r["qid"] == "ice_day"]
    assert said and all(r["layers"] == [] for r in said)                                          # "how is your day": rapport, nothing stored


def test_small_talk_answers_seed_the_profile_and_the_prior_tour_fact(fake):
    recs, _, info = fake
    si = {v["track_id"]: v for v in info["start_impression"]["visitors"]}
    heard = {r["track_id"]: r["layers"] for r in recs if r["type"] == "note" and r["note"] == "encounter: answer" and r["qid"] == "ice_visit"}
    assert heard and all(si[t].get("prior_tour") in ("yes", "no") for t in heard)
    assert all("prior_tour" not in si[t] for t in si if t not in heard)                            # quiet visitors: nothing assumed
    assert "v4" not in heard                                                                      # reserved
    fav = [(r["track_id"], l) for r in recs if r["type"] == "note" and r["note"] == "encounter: answer" and r["qid"] == "ice_fav"
           for l in r["layers"]]
    for tid, l in fav:
        kind, target = l.split(":")
        assert {"kind": kind, "target": target} in si[tid]["pending_layers"]


def test_the_profile_is_one_record_born_in_the_encounter_and_updated_in_the_tour(fake):
    recs, _, info = fake
    prof = [r for r in recs if r["type"] == "profile" and r.get("layer")]
    seeded = [r for r in prof if r["op"] == "create" and str(r["reason"]).startswith("from the encounter")]
    assert seeded and all(r["t"] < 0 for r in seeded)                                            # dated when it was said
    assert not [r for r in prof if r["op"] == "create" and r["reason"] == "pending layer from the start impression"]
    assert [r["t"] for r in recs] == sorted(r["t"] for r in recs)
    ids = [(r["track_id"], r["kind"], r["target"]) for r in prof if r["op"] == "create"]
    assert len(ids) == len(set(ids))                                                              # nothing is created twice: it is updated
    assert any(r["t"] > 0 and r["layer"] in {x["layer"] for x in seeded} for r in prof if r["op"] != "create")  # a seeded guess is later tested


def test_the_tours_visitor_questions_are_in_the_replay_as_simulated_speech(fake):
    recs, _, _ = fake
    said = [r for r in recs if r["type"] == "note" and r["note"] == "tour: visitor said"]
    assert {"Is that the original paint?", "How many sailors were on it?"} <= {r["text"] for r in said}
    assert all(r["simulated"] and r["t"] > 0 for r in said)
