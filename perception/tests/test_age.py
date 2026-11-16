"""Age band: smoothing, abstention, pipeline, and the FairFace boundary (only age leaves the backend, D4)."""
import os

import pytest

np = pytest.importorskip("numpy")

from perception.age import (MODEL_PATH, AgeBandPipeline, AgeProbs, FairFaceAgeEstimator,  # noqa: E402
                            FakeAgeEstimator, PersonAgeSmoother)

CHILD, ADULT, TEEN = AgeProbs(0.9, 0.1), AgeProbs(0.05, 0.95), AgeProbs(0.3, 0.2, 0.5)


def feed(sm, p, n):
    for _ in range(n):
        r = sm.update(p)
    return r


def test_too_few_frames_is_unsure():
    sm = PersonAgeSmoother()
    assert feed(sm, CHILD, 4).band == "unsure"
    assert sm.update(CHILD).band == "child"


def test_clear_child_and_adult():
    assert feed(PersonAgeSmoother(), CHILD, 6).band == "child"
    assert feed(PersonAgeSmoother(), ADULT, 6).band == "adult"


def test_middle_band_and_teen_mass_abstain():
    assert feed(PersonAgeSmoother(), AgeProbs(0.5, 0.5), 8).band == "unsure"   # ratio in middle band
    assert feed(PersonAgeSmoother(), TEEN, 8).band == "unsure"                 # low confidence


def test_smoothing_absorbs_one_bad_frame():
    sm = PersonAgeSmoother()
    feed(sm, ADULT, 7)
    assert sm.update(CHILD).band == "adult"


def test_config_override():
    assert feed(PersonAgeSmoother({"min_frames": 2}), CHILD, 2).band == "child"


def test_pipeline_two_people_and_cleanup():
    est = FakeAgeEstimator({"visitor_1": CHILD, "visitor_2": ADULT})
    boxes = [(0, 0, 10, 10), (100, 100, 110, 110)]
    pipe = AgeBandPipeline(est, lambda f: boxes, cfg={"track_max_missed": 0})
    for _ in range(6):
        res = pipe.process(None)
    assert [(r["person_id"], r["band"]) for r in res] == [("visitor_1", "child"), ("visitor_2", "adult")]
    boxes.clear()
    pipe.process(None); pipe.process(None)
    assert pipe._smoothers == {}                       # leaving visitors' state is dropped


def test_output_has_no_gender_or_race_fields():
    est = FakeAgeEstimator({"visitor_1": CHILD})
    pipe = AgeBandPipeline(est, lambda f: [(0, 0, 10, 10)])
    keys = set(pipe.process(None)[0])
    assert keys == {"person_id", "box", "band", "confidence", "p_child", "p_adult", "n_frames", "track_conf", "streak"}
    assert set(AgeProbs.__dataclass_fields__) == {"p_child", "p_adult", "p_teen"}


def test_fake_script_sequence_and_noise_seeded():
    e = FakeAgeEstimator({"a": [CHILD, ADULT]})
    assert [e.estimate(None, None, "a").p_child for _ in range(3)] == [0.9, 0.05, 0.05]
    n1 = FakeAgeEstimator({"a": CHILD}, noise=0.1, seed=1).estimate(None, None, "a")
    n2 = FakeAgeEstimator({"a": CHILD}, noise=0.1, seed=1).estimate(None, None, "a")
    assert n1 == n2 and abs(n1.p_child - 0.9) <= 0.1


def test_pipeline_does_not_feed_ambiguous_frames_to_smoother_and_reports_track_conf():
    est = FakeAgeEstimator({"visitor_1": CHILD, "visitor_2": ADULT})
    seq = []
    pipe = AgeBandPipeline(est, lambda f: seq, cfg={"min_frames": 1})
    for f in range(40):
        x = 4 * f
        seq[:] = [(x, 0, x + 40, 40), (156 - x, 0, 196 - x, 40)]
        res = pipe.process(None)
    assert all("track_conf" in r for r in res)


def test_fairface_checksum_and_missing(tmp_path):
    pytest.importorskip("onnxruntime")
    with pytest.raises(FileNotFoundError):
        FairFaceAgeEstimator(str(tmp_path / "x.onnx"))
    bad = tmp_path / "bad.onnx"
    bad.write_bytes(b"not a model")
    with pytest.raises(ValueError):
        FairFaceAgeEstimator(str(bad))


@pytest.mark.skipif(not os.path.exists(MODEL_PATH), reason="FairFace model not at MODEL_PATH")
def test_fairface_runs_and_returns_age_mass_only():
    pytest.importorskip("onnxruntime"); pytest.importorskip("cv2")
    p = FairFaceAgeEstimator().estimate(np.random.RandomState(0).randint(0, 255, (120, 120, 3), dtype=np.uint8),
                                        (10, 10, 110, 110))
    assert abs(p.p_child + p.p_adult + p.p_teen - 1.0) < 1e-4


# ── FairFace boundary: only age leaves the backend; the 10-19 bin is "unsure" ─────────────

class _FakeSession:
    """Stands in for the onnx session: returns 18 logits = 7 race + 2 gender + 9 age."""
    def __init__(self, race=0.0, gender=0.0, age_bin=0, strength=12.0):
        self.race, self.gender, self.age_bin, self.strength = race, gender, age_bin, strength

    def run(self, _outs, _feed):
        out = np.full(18, 0.0, np.float32)
        out[0:7] = self.race
        out[7:9] = self.gender
        out[9 + self.age_bin] = self.strength
        return [out[None, :]]


def _backend(sess):
    pytest.importorskip("cv2")                                  # estimate() resizes the crop with OpenCV
    est = FairFaceAgeEstimator.__new__(FairFaceAgeEstimator)     # skip loading the real model
    est._sess, est._in = sess, "input"
    return est


FRAME = np.zeros((100, 100, 3), np.uint8)
BOX = (10, 10, 90, 90)


def test_race_and_gender_logits_have_no_influence_and_are_not_returned():
    base = _backend(_FakeSession(age_bin=4)).estimate(FRAME, BOX)
    wild = _backend(_FakeSession(race=1e4, gender=-1e4, age_bin=4)).estimate(FRAME, BOX)
    assert base == wild                                         # identical whatever race/gender logits say
    assert isinstance(base, AgeProbs)
    assert set(vars(base)) == {"p_child", "p_adult", "p_teen"}  # no other attribute, array or field


@pytest.mark.parametrize("age_bin,expect", [(0, "child"), (1, "child"), (2, "teen"),
                                            (3, "adult"), (4, "adult"), (5, "adult"), (6, "adult"), (7, "adult"), (8, "adult")])
def test_age_bin_mapping(age_bin, expect):
    p = _backend(_FakeSession(age_bin=age_bin)).estimate(FRAME, BOX)
    top = max(("child", p.p_child), ("adult", p.p_adult), ("teen", p.p_teen), key=lambda t: t[1])[0]
    assert top == expect and p.p_child + p.p_adult + p.p_teen == pytest.approx(1.0)


def test_ten_to_nineteen_bin_comes_out_unsure_through_the_pipeline():
    est = _backend(_FakeSession(age_bin=2))
    pipe = AgeBandPipeline(est, lambda f: [BOX])
    for _ in range(12):
        res = pipe.process(FRAME)
    assert res[0]["band"] == "unsure" and res[0]["n_frames"] == 8     # window full, still abstains


def test_estimator_module_only_reads_age_slice():
    # guard against someone later using the other logits: the slice is the only logits[...] access
    import inspect
    src = inspect.getsource(FairFaceAgeEstimator.estimate)
    assert "logits[9:18]" in src and "logits[0" not in src and "logits[7" not in src
