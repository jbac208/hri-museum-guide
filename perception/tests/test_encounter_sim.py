"""The encounter phase end to end (simulation): ids are the tour's ids, clusters come from our perception, the handoff is
a valid start_impression, and without the conversation's layers his tour is unchanged."""
import os

import pytest

pytest.importorskip("numpy")

import run_tour  # noqa: E402
from sdc import schema  # noqa: E402

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
    allowed = {q.text for q in m} | {dialogue.GREETING, dialogue.ACK, "Let's begin with the ship's figurehead."}
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
