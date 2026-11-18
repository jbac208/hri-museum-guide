"""Level 1 integration scaffolding: the splice changes nothing when it passes Joey's own line through, the patch is
always undone, and our impression covers exactly his visitors."""
import pytest

pytest.importorskip("numpy")

import compare_policies as cp  # noqa: E402
from sdc import mock, scenarios, schema, sim as sdc_sim  # noqa: E402
from sdc.policies import OURS  # noqa: E402

from perception.integration import run_in_scenario as R  # noqa: E402

PASS = R.maker(None, 1, [])


@pytest.mark.parametrize("seed", [1, 2])
def test_condition_a_reproduces_his_s1_closed_numbers_exactly(seed):
    with R.replaced_start_impression(PASS):
        ours, _ = R.run_s1_closed(seed)
    assert ours == cp.run_s1(OURS, seed)


def test_condition_a_reproduces_his_s2_numbers_exactly():
    with R.replaced_start_impression(PASS):
        ours, _ = R.run_s2(1)
    assert ours == cp.run_s2(OURS, 1)


def test_condition_a_reproduces_his_open_loop_evaluation():
    res, events = R.run_s1_open(PASS, 7)
    scn = scenarios.s1_one_stop()
    plain = R.SignalLayer(cp.GALLERY, scn.stop).run(R.adapter.from_lines(mock.generate(scn, cp.GALLERY)))
    assert [e.as_dict() for e in events] == [e.as_dict() for e in plain]


def test_start_lines_is_restored_even_when_the_run_raises():
    orig = sdc_sim.Sim.start_lines
    with pytest.raises(RuntimeError):
        with R.replaced_start_impression(PASS):
            assert sdc_sim.Sim.start_lines is not orig
            raise RuntimeError("run failed")
    assert sdc_sim.Sim.start_lines is orig


def test_our_impression_covers_exactly_his_visitors_and_validates():
    his = mock.generate(scenarios.s1_one_stop(), cp.GALLERY)[1]
    bands = {v["track_id"]: v["age_class"] for v in his["visitors"]}
    si, notes = R.our_impression(his, bands, 1)
    schema.validate_start_impression(si)
    assert sorted(v["track_id"] for v in si["visitors"]) == sorted(bands) and notes["missing"] == []
    got = {v["track_id"]: v["age_band"] for v in si["visitors"]}
    assert got == bands                                          # the scripted ages come through our age pipeline


def test_spliced_closed_loop_stream_validates_and_carries_our_impression():
    notes = []
    with R.replaced_start_impression(R.maker({}, 1, notes)):
        m, _ = R.run_s1_closed(1)                                # run_closed_loop validates every line and the stream
    assert notes and notes[0]["missing"] == [] and m["type"] == "measures"


def test_distance_sweep_true_equals_a_and_bias_reaches_every_visitor():
    from perception.integration import distance_sweep as D
    conds = D.conditions()
    res_a, ev_a = R.run_s1_open(D.maker(conds["A"], 3, []), 3)
    res_t, ev_t = R.run_s1_open(D.maker(conds["true"], 3, []), 3)
    assert [e.as_dict() for e in ev_t] == [e.as_dict() for e in ev_a]
    applied = []
    R.run_s1_open(D.maker(conds["-0.3 m"], 3, applied), 3)
    assert sorted(t for t, _, _ in applied) == sorted(R.PEOPLE_AGES)
    assert all(abs(s - (d - 0.3)) < 1e-6 for _, d, s in applied)
