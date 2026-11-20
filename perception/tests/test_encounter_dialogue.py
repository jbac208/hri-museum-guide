"""The encounter conversation's guards (no numpy, no network): the LLM proposes, code decides."""
import json
import random

from sdc.content import SINGLING_OUT

import run_tour
from perception.encounter_sim import dialogue as dlg
from perception.encounter_sim.llm import FakeLLM

M = dlg.menu(run_tour.GALLERY, "figurehead")
Q = {q.id: q for q in M}


def answer(layers):
    return lambda system, user: json.dumps({"layers": layers})


def item(kind="feature_interest", target="figurehead.paint", conf=0.9, quote="original paint"):
    return {"kind": kind, "target": target, "confidence": conf, "quote": quote}


def test_menu_speech_is_to_the_group_and_closed():
    for q in M:
        assert not SINGLING_OUT.search(q.text)
        assert set(q.cues) == {(k, t) for k, t, _ in q.options}
    assert not any(SINGLING_OUT.search(x) for x in (dlg.GREETING, dlg.INTRO, dlg.ACK, dlg.LEAD.format("ship's figurehead"))
                   + tuple(t for _, t in dlg.ICE) + tuple(dlg.ICE_REACT.values()))


def test_extract_keeps_a_grounded_item():
    got, dropped, _ = dlg.extract(answer([item()]), Q["features"], "The original paint!")
    assert got == [("feature_interest", "figurehead.paint")] and dropped == []


def test_extract_drops_malformed_output_whole():
    for raw in ("not json", '{"layers": "x"}', "[1, 2]", "[LLM error: timeout]"):
        got, dropped, _ = dlg.extract(lambda s, u, raw=raw: raw, Q["features"], "The original paint!")
        assert got == [] and dropped == [("all", "json_or_shape")]


def test_extract_drops_each_bad_item_and_never_repairs_it():
    text = "The original paint!"
    bad = [item(target="figurehead.carving", quote="original"),           # quote does not name the carving
           item(target="sea_chest.lid"),                                    # not an option of this question
           item(conf=0.3),                                                  # below CONFIDENCE_MIN
           item(quote="the paint is original"),                             # not verbatim
           "junk"]
    got, dropped, _ = dlg.extract(answer(bad), Q["features"], text)
    assert got == []
    assert [w for _, w in dropped] == ["quote_does_not_name_it", "not_an_option", "low_conf", "quote_not_in_text", "not_dict"]


def test_opposite_answer_in_the_only_option_is_dropped():
    # what qwen2.5:7b actually returned in the first recording run: "Short is fine." filed as "the full story"
    raw = answer([item("depth", "figurehead", 0.8, "Short is fine.")])
    got, dropped, _ = dlg.extract(raw, Q["depth"], "Short is fine.")
    assert got == [] and dropped == [("depth:figurehead", "quote_does_not_name_it")]
    got, _, _ = dlg.extract(answer([item("depth", "figurehead", 1, "full story")]), Q["depth"], "The full story, please.")
    assert got == [("depth", "figurehead")]


def test_select_is_budgeted_ordered_and_falls_back():
    assert [q.id for q in dlg.allowed(M, [])] == ["depth", "features"]          # open only after a choice question
    assert [q.id for q in dlg.allowed(M, ["depth"])] == ["features", "open"]
    assert dlg.allowed(M, ["depth", "features"]) == []                           # budget 2
    q, how, _ = dlg.select(lambda s, u: '{"next": "open"}', M, [], {})           # not allowed yet
    assert (q.id, how) == ("depth", "fallback")
    q, how, _ = dlg.select(lambda s, u: '{"next": "none"}', M, ["depth"], {})
    assert (q, how) == (None, "llm")
    q, how, _ = dlg.select(lambda s, u: '{"next": "features"}', M, ["depth"], {})
    assert (q.id, how) == ("features", "llm")
    assert dlg.select(FakeLLM(), M, ["depth", "features"], {})[1] == "budget"


def test_llm_outage_falls_back_but_never_raises():
    def down(s, u):
        raise OSError("connection refused")
    assert dlg.select(down, M, [], {})[1] == "fallback"
    assert dlg.extract(down, Q["features"], "The original paint!")[1] == [("all", "json_or_shape")]


def test_reserved_visitor_never_answers_and_replies_follow_hidden_interests():
    vis = [("v3", 0.9, {("feature_interest", "figurehead.paint")}), ("v4", 0.0, {("feature_interest", "figurehead.carving")})]
    names = {"figurehead.paint": "original paint", "figurehead.carving": "carved face"}
    for seed in range(50):
        said = dict(dlg.replies(Q["features"], vis, names, random.Random(seed)))
        assert "v4" not in said
        assert said.get("v3", "The original paint!") == "The original paint!"


def test_fake_llm_extracts_through_the_same_guard():
    got, _, _ = dlg.extract(FakeLLM(), Q["open"], "What about the sailor's sea chest?")
    assert got == [("exhibit_interest", "sea_chest")]


def test_icebreaker_answers_are_read_by_closed_keyword_sets():
    assert dlg.prior_tour("No, this is my first one.") == "no" and dlg.prior_tour("Yes, I've been on a few.") == "yes"
    assert dlg.prior_tour("Hmm, hard to say") is None                                             # unclear: nothing stored
    assert dlg.favourite(run_tour.GALLERY, "I like the navigator's compass.") == [("exhibit_interest", "compass")]
    assert dlg.favourite(run_tour.GALLERY, "Not really, I'm new here.") == []                     # no name, no guess


def test_reserved_visitor_never_answers_an_icebreaker():
    vis = [("v3", 0.9, True, "compass"), ("v4", 0.0, False, None)]
    for seed in range(50):
        for qid, _ in dlg.ICE:
            assert "v4" not in dict(dlg.ice_replies(qid, vis, {"compass": "navigator's compass"}, random.Random(seed)))
