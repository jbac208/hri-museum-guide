"""Encounter: stable-frame gate, wipe at the end, and the start_impression against Joey's schema and adapter.
The fake camera is scripted; these tests show the wiring, not that real faces behave this way."""
import json
import os
import subprocess
import sys

import pytest

np = pytest.importorskip("numpy")

from sdc import adapter, schema  # noqa: E402

from perception.age import AgeProbs, FakeAgeEstimator  # noqa: E402
from perception.encounter import PLACEHOLDER, PLACEHOLDER_FIELDS, Encounter, build_start_impression  # noqa: E402
from perception.group import UNKNOWN  # noqa: E402
from perception.run_encounter import FakeCamera  # noqa: E402
from perception.tracker import Detection  # noqa: E402

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
FRAME = np.zeros((480, 640, 3), np.uint8)
ADULT = AgeProbs(0.05, 0.93, 0.02)


def fake_run(**kw):
    cam = FakeCamera()
    enc = Encounter(cam.estimator, cam.detect, **kw)
    events = []
    si = enc.run(cam.frames(), on_frame=lambda t, e, ev: ev and events.append(ev))
    return si, events, enc


def scripted(seq, stable_frames=5):
    """seq: one list of Detections per frame. Returns the encounter after stepping through it (no end())."""
    it = iter(seq)
    enc = Encounter(FakeAgeEstimator({f"visitor_{i}": ADULT for i in range(1, 9)}), lambda f: next(it),
                    stable_frames=stable_frames)
    for i in range(len(seq)):
        enc.step(i / 10, FRAME)
    return enc


def emb(seed):
    v = np.random.RandomState(seed).randn(512)
    return v / np.linalg.norm(v)


A = (100, 100, 220, 244)            # 144 px high: passes filter_faces at 480 px


# ── the start_impression ─────────────────────────────────────────────────────────────────

def test_fake_run_fires_once_for_the_group_and_validates():
    si, events, _ = fake_run()
    assert len(events) == 1 and events[0].reason == "group_known"
    schema.validate_start_impression(si)
    schema.validate_line(si)                                            # also as a stream line ("type" present)
    assert [v["track_id"] for v in si["visitors"]] == ["visitor_1", "visitor_2", "visitor_3"]
    assert si["group"]["size"] == 3 and len({v["cluster_id"] for v in si["visitors"]}) == 1


def test_joeys_adapter_reads_it_and_ignores_the_extra_fields():
    si, _, _ = fake_run()
    imp = adapter.parse(si)
    assert set(imp.visitors) == {"visitor_1", "visitor_2", "visitor_3"} and imp.group_size == 3
    assert imp.visitors["visitor_3"].age_class == "child"


def test_age_fields_argmax_real_confidence_and_extra_band_fields():
    si, _, _ = fake_run()
    v = {x["track_id"]: x for x in si["visitors"]}
    assert (v["visitor_1"]["age_band"], v["visitor_1"]["age_class"]) == ("adult", "adult")
    assert (v["visitor_3"]["age_band"], v["visitor_3"]["age_class"]) == ("child", "child")
    teen = v["visitor_2"]
    assert teen["age_band"] == "unsure" and teen["age_class"] == "adult"          # argmax of p_child 0.20 / p_adult 0.35
    assert teen["age_conf"] == teen["p_adult"] < 0.6                                # its own mass, not inflated
    for x in si["visitors"]:
        assert set(x) >= {"age_band", "p_child", "p_adult"}


def test_seed_values_come_from_placeholder_and_unsure_gets_the_neutral_glance_rate():
    si, _, _ = fake_run()
    glances = {v["age_band"]: v["baseline_seed"]["robot_glances_per_min"] for v in si["visitors"]}
    assert glances == {"adult": 4.0, "child": 6.0, "unsure": 5.0}
    for v in si["visitors"]:
        assert v["baseline_seed"]["distance_m"] == PLACEHOLDER["distance_m"]
        assert v["baseline_seed"]["speech_frac"] == PLACEHOLDER["speech_frac"]
        assert v["responded_to_steer_invite"] is PLACEHOLDER["responded_to_steer_invite"]
        assert v["pending_layers"] == []
    assert si["group"]["spread_m"] == PLACEHOLDER["spread_m"]
    assert si["placeholder_fields"] == PLACEHOLDER_FIELDS


def test_every_placeholder_field_is_named():
    si, _, _ = fake_run()
    named = set(si["placeholder_fields"])
    assert named == {"group.spread_m", "visitors[].baseline_seed.distance_m",
                     "visitors[].baseline_seed.robot_glances_per_min", "visitors[].baseline_seed.speech_frac",
                     "visitors[].responded_to_steer_invite"}


def test_unknown_group_context_gives_a_solo_cluster():
    r = {"person_id": "visitor_7", "band": "adult", "confidence": 0.9, "p_child": 0.05, "p_adult": 0.9}
    si = build_start_impression(1.0, [r], lambda pid: UNKNOWN)
    assert si["visitors"][0]["cluster_id"] == "solo_visitor_7" and si["group"]["size"] == 1


def test_fake_run_is_deterministic():
    assert fake_run()[0] == fake_run()[0]


# ── stable-frame gate and filter_faces ───────────────────────────────────────────────────

def test_poster_and_one_frame_face_are_not_in_the_output():
    si, _, _ = fake_run()
    assert "visitor_4" not in {v["track_id"] for v in si["visitors"]}     # the one-frame face got an id, never stable
    assert len(si["visitors"]) == 3                                       # the 24 px poster never got one


def test_visitor_counts_only_after_n_consecutive_frames():
    assert scripted([[Detection(A, emb(1))]] * 4).stable == set()
    assert scripted([[Detection(A, emb(1))]] * 5).stable == {"visitor_1"}
    assert scripted([[Detection(A, emb(1))]] * 7, stable_frames=8).stable == set()


def test_a_broken_streak_does_not_count():
    seq = [[Detection(A, emb(1))]] * 3 + [[]] + [[Detection(A, emb(1))]] * 3      # 3 + gap + 3: never 5 in a row
    assert scripted(seq).stable == set()


def test_a_face_filtered_out_never_becomes_stable():
    tiny = (100, 100, 140, 150)                                                     # 50 px high: below 0.18 x 480
    assert scripted([[Detection(tiny, emb(1))]] * 20).stable == set()


def test_stable_frames_is_configurable_and_too_high_means_no_event():
    si, events, _ = fake_run(stable_frames=1000)
    assert si is None and events == []


# ── lifecycle: nothing kept, nothing written ─────────────────────────────────────────────

def test_end_wipes_embeddings_smoothers_clusters_and_the_gate():
    si, _, enc = fake_run()                                     # run() calls end()
    assert si is not None
    assert enc.pipeline.tracker.known() == [] and enc.pipeline._smoothers == {}
    assert enc.groups.members("group_3") == [] and enc.stable == set() and enc.latest == {}


def test_end_runs_even_when_the_run_fails():
    cam = FakeCamera()
    enc = Encounter(cam.estimator, cam.detect)

    def frames():
        yield from list(cam.frames())[:30]
        raise RuntimeError("camera unplugged")
    with pytest.raises(RuntimeError):
        enc.run(frames())
    assert enc.pipeline.tracker.known() == [] and enc.stable == set()


def test_full_run_in_an_empty_folder_writes_only_the_requested_output(tmp_path):
    work, home = tmp_path / "work", tmp_path / "home"
    work.mkdir(); home.mkdir()
    env = {**os.environ, "PYTHONPATH": REPO, "HOME": str(home), "PYTHONDONTWRITEBYTECODE": "1"}
    r = subprocess.run([sys.executable, "-m", "perception.run_encounter", "--source", "fake", "--out", "si.json"],
                       cwd=work, env=env, capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr
    files = sorted(os.path.relpath(os.path.join(d, f), tmp_path) for d, _, fs in os.walk(tmp_path) for f in fs)
    assert files == [os.path.join("work", "si.json")]                 # nothing else, not even under $HOME
    schema.validate_start_impression(json.loads((work / "si.json").read_text()))


def test_stdout_mode_prints_one_valid_json_line():
    r = subprocess.run([sys.executable, "-m", "perception.run_encounter", "--source", "fake"], cwd=REPO,
                       capture_output=True, text=True, timeout=60)
    assert r.returncode == 0 and len(r.stdout.splitlines()) == 1
    schema.validate_start_impression(json.loads(r.stdout))
