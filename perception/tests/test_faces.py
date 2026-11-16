"""Face source. filter_faces is pure; detect_and_embed loads the real models, so it runs only when torch,
facenet-pytorch, OpenCV and the cached VGGFace2 weights are all present (no network in tests)."""
import os

import pytest

np = pytest.importorskip("numpy")

from perception.faces import filter_faces  # noqa: E402
from perception.tracker import Detection  # noqa: E402

H = 480


def test_filter_faces_drops_small_and_relatively_small_faces():
    visitor = Detection((100, 100, 200, 220))          # 120 px = 25% of the frame
    poster = Detection((400, 10, 440, 60))             # 50 px = 10%: below the absolute floor
    far_back = Detection((300, 100, 360, 190))         # 90 px (19%), but 0.45x the visitor's area: relative floor
    assert filter_faces([visitor, poster, far_back], H) == [visitor]


def test_filter_faces_keeps_similar_sized_faces_and_handles_empty():
    a, b = Detection((0, 0, 100, 120)), Detection((200, 0, 290, 110))
    assert filter_faces([a, b], H) == [a, b]
    assert filter_faces([], H) == []


VGG = os.path.join(os.path.expanduser("~"), ".cache", "torch", "checkpoints", "20180402-114759-vggface2.pt")


@pytest.mark.skipif(not os.path.exists(VGG), reason="VGGFace2 weights not cached (would download)")
def test_detect_and_embed_on_a_blank_frame_finds_nothing():
    pytest.importorskip("cv2"); pytest.importorskip("torch"); pytest.importorskip("facenet_pytorch")
    from perception.faces import load_detect_and_embed
    detect = load_detect_and_embed()
    assert detect(np.zeros((H, 640, 3), np.uint8)) == []
