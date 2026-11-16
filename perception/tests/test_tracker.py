"""Tracker: ids, embeddings, margin rule, track confidence. Synthetic embeddings: they show the logic works, not that
real faces separate."""
import pytest

np = pytest.importorskip("numpy")

from perception.tracker import Detection, VisitTracker  # noqa: E402


def emb(seed, noise=0.05, rng=None):
    r = np.random.RandomState(seed)
    v = r.randn(512)
    if rng is not None:
        v = v + noise * rng.randn(512) * np.linalg.norm(v) / np.sqrt(512) * 4
    return v / np.linalg.norm(v)


def mix(a, b, w):
    v = w * a + (1 - w) * b
    return v / np.linalg.norm(v)


A_BOX, B_BOX = (0, 0, 40, 40), (50, 0, 90, 40)


def test_tracker_ids_stable_new_and_not_reused():
    t = VisitTracker({"track_max_missed": 1})
    a, b = (0, 0, 10, 10), (100, 100, 110, 110)
    assert t.assign([a, b]) == ["visitor_1", "visitor_2"]
    assert t.assign([(1, 1, 11, 11), (101, 100, 111, 110)]) == ["visitor_1", "visitor_2"]
    t.assign([]); t.assign([])                       # both exceed max_missed -> dropped
    assert t.alive() == []
    assert t.assign([a]) == ["visitor_3"]


def test_exchange_places_swaps_ids_silently_without_embeddings():
    """A and B swap spots between frames (e.g. while occluded). Boxes alone cannot tell: the ids follow the
    SPOTS, so A is now called visitor_2, and track_conf does not drop, the swap is silent."""
    t = VisitTracker()
    t.assign([A_BOX, B_BOX])
    ids = t.assign([B_BOX, A_BOX])            # det0 is person A (now standing where B was), det1 is person B
    assert ids == ["visitor_2", "visitor_1"]  # wrong: A should still be visitor_1
    assert t.confidence("visitor_1") >= 0.6 and t.confidence("visitor_2") >= 0.6


def test_embeddings_keep_ids_when_people_exchange_places():
    ea, eb = emb(1), emb(2)
    t = VisitTracker()
    t.assign_detections([Detection(A_BOX, ea), Detection(B_BOX, eb)])
    ids = t.assign_detections([Detection(B_BOX, ea), Detection(A_BOX, eb)])   # same exchange, faces known
    assert ids == ["visitor_1", "visitor_2"]
    assert t.confidence("visitor_1") >= 0.6 and t.confidence("visitor_2") >= 0.6


def _cross(with_emb):
    ea, eb = emb(1), emb(2)
    t = VisitTracker()
    ids_seq, confs = [], []
    for f in range(40):
        x = 4 * f
        a, b = (x, 0, x + 40, 40), (156 - x, 0, 196 - x, 40)       # A goes right, B goes left, they overlap mid-way
        dets = [Detection(a, ea if with_emb else None), Detection(b, eb if with_emb else None)]
        ids = t.assign_detections(dets)
        ids_seq.append(ids)
        confs.append((t.confidence(ids[0]), t.confidence(ids[1])))
    return ids_seq, confs


def test_crossing_with_embeddings_keeps_ids_and_confidence():
    ids_seq, confs = _cross(True)
    assert all(ids == ["visitor_1", "visitor_2"] for ids in ids_seq)
    assert min(min(c) for c in confs) >= 0.5


def test_crossing_without_embeddings_is_flagged_ambiguous():
    ids_seq, confs = _cross(False)
    assert min(min(c) for c in confs) < 0.5          # the tracker knows it is unsure around the crossing


def test_reassociation_returns_old_id_for_same_face():
    ea, eb = emb(1), emb(2)
    rng = np.random.RandomState(0)
    t = VisitTracker({"track_max_missed": 2})
    t.assign_detections([Detection(A_BOX, ea), Detection(B_BOX, eb)])
    for _ in range(4):
        t.assign_detections([])                      # both leave long enough to be "lost"
    assert t.alive() == [] and set(t.known()) == {"visitor_1", "visitor_2"}
    ids = t.assign_detections([Detection((200, 100, 240, 140), emb(1, rng=rng))])    # A returns elsewhere
    assert ids == ["visitor_1"]
    assert t.confidence("visitor_1") == pytest.approx(0.6)


def test_margin_rule_lookalike_gets_new_id():
    """Relatives stand-in: the returning face is nearly equidistant from two lost tracks."""
    ea, eb = emb(1), emb(2)
    t = VisitTracker({"track_max_missed": 1})
    t.assign_detections([Detection(A_BOX, ea), Detection(B_BOX, eb)])
    for _ in range(3):
        t.assign_detections([])
    rel = mix(ea, eb, 0.5)                           # cosine ~0.71 to both, gap ~0 < reid_gap
    assert float(rel @ ea) > 0.6 and float(rel @ eb) > 0.6 and abs(float(rel @ ea) - float(rel @ eb)) < 0.1
    assert t.assign_detections([Detection((100, 0, 140, 40), rel)]) == ["visitor_3"]


def test_margin_rule_clear_winner_reuses_and_low_cosine_is_new():
    ea, eb = emb(1), emb(2)
    t = VisitTracker({"track_max_missed": 1})
    t.assign_detections([Detection(A_BOX, ea), Detection(B_BOX, eb)])
    for _ in range(3):
        t.assign_detections([])
    assert t.assign_detections([Detection((100, 0, 140, 40), mix(ea, eb, 0.85))]) == ["visitor_1"]
    t2 = VisitTracker({"track_max_missed": 1, "reid_min_cos": 0.9})
    t2.assign_detections([Detection(A_BOX, ea)])
    for _ in range(3):
        t2.assign_detections([])
    assert t2.assign_detections([Detection((100, 0, 140, 40), mix(ea, eb, 0.6))]) == ["visitor_2"]    # cosine ~0.83 < 0.9


def test_new_face_resembling_a_live_track_is_not_merged_into_a_lost_one():
    ea, eb = emb(1), emb(2)
    t = VisitTracker({"track_max_missed": 1})
    t.assign_detections([Detection(A_BOX, ea), Detection(B_BOX, eb)])
    t.assign_detections([Detection(B_BOX, eb)])      # A missing, B stays live
    t.assign_detections([Detection(B_BOX, eb)])
    t.assign_detections([Detection(B_BOX, eb)])
    sibling_of_b = mix(eb, ea, 0.8)                  # close to live B (0.8-ish) and to lost A
    ids = t.assign_detections([Detection(B_BOX, eb), Detection((120, 0, 160, 40), sibling_of_b)])
    assert ids[0] == "visitor_2" and ids[1] == "visitor_3"


def test_streak_counts_consecutive_frames_and_resets_on_a_gap():
    t = VisitTracker()
    for _ in range(3):
        t.assign([A_BOX])
    assert t.streak("visitor_1") == 3
    t.assign([])
    assert t.streak("visitor_1") == 0
    t.assign([A_BOX])
    assert t.streak("visitor_1") == 1


def test_clear_drops_everything():
    t = VisitTracker()
    t.assign_detections([Detection(A_BOX, emb(1))])
    t.clear()
    assert t.known() == []
