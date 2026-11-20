"""The video's schedule: every spoken line plays at 1x, the quiet stretches of the tour are sped up (needs the encounter sim: numpy)."""
import pytest

pytest.importorskip("numpy")

from perception.encounter_sim import video  # noqa: E402
from perception.encounter_sim.llm import FakeLLM  # noqa: E402
from perception.encounter_sim.run import run  # noqa: E402


def test_every_line_is_at_1x_and_the_quiet_tour_is_faster():
    recs, _, _ = run("s2_multi_stop", llm=FakeLLM(), seed=1)
    ev = video.speech_events(recs)
    assert any(who == "robot" and a > 0 for a, _, _, who in ev) and any(who != "robot" and a > 0 for a, _, _, who in ev)   # tour: both sides
    ts = video.schedule(recs, 10)
    assert all(video.at_1x(ts, 10, a, b + 0.4) is not None for a, b, _, _ in ev)
    steps = [b - a for a, b in zip(ts, ts[1:])]
    assert max(steps) > 0.35 and len(ts) / 10 < recs[-1]["t"] - ts[0]                           # sped up where it is quiet, shorter than real time


def test_the_robot_walks_to_stop_1_straight_after_the_small_talk():
    recs, _, info = run("s2_multi_stop", llm=FakeLLM(), seed=1, tour_questions=False)
    says = [r for r in recs if r["type"] == "action" and r["kind"] == "say_to_group" and r["t"] < 0]
    ids = [r["args"]["id"] for r in says]
    assert ids[-2:] == ["encounter.ice.fav.react", "encounter.lead"] and not [i for i in ids if i.startswith("encounter.q.") or i == "encounter.ack"]
    assert info["asked"] == []
    walk = next(r for r in recs if r["type"] == "action" and r["kind"] == "step_to" and r["t"] < 0)
    assert 0 < walk["t"] - says[-1]["t"] < 6                                                     # the walk starts when the lead-in is spoken
    ts = video.schedule(recs, 10)
    assert all(b - a < 0.11 for a, b in zip(ts, ts[1:]) if b < 0) and 0.0 in ts                  # one continuous 1x stretch, no cut
    from perception.encounter_sim.replay import captions
    assert not [c for c in captions(recs) if "Two questions about this tour" in c["text"]]
