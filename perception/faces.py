"""Face source: facenet-pytorch MTCNN boxes + InceptionResnetV1 (VGGFace2) 512-d embeddings, and filter_faces.

Detection and embedding only. There is no enrolment, gallery, naming, save or load: the embeddings go to the tracker
for in-memory re-association and nothing else. Replaces the museum code's use of ChatBox's FaceIdentifier.identify_all.

First use of InceptionResnetV1(pretrained="vggface2") downloads ~110 MB of weights into the torch cache
(~/.cache/torch/checkpoints/20180402-114759-vggface2.pt) if they are not there yet. That is the only file this module
can cause to be written.
"""

from __future__ import annotations

from typing import Callable, List

from .tracker import Detection

MIN_PROB = 0.90       # MTCNN face probability below this is dropped (same as identify_all)


def load_detect_and_embed(scale: float = 0.5, max_faces: int = 4, device: str = "cpu") -> Callable:
    """Load the models once and return ``detect_and_embed(frame_bgr) -> [Detection]`` (boxes in full-frame pixels,
    unit-norm embeddings). ``scale`` downsizes the frame for MTCNN only."""
    import cv2
    import numpy as np
    import torch
    from facenet_pytorch import MTCNN, InceptionResnetV1
    from PIL import Image

    mtcnn = MTCNN(image_size=160, margin=20, keep_all=True, device=device, post_process=True)
    resnet = InceptionResnetV1(pretrained="vggface2", device=device).eval()

    def detect_and_embed(frame_bgr) -> List[Detection]:
        h, w = frame_bgr.shape[:2]
        small = cv2.resize(frame_bgr, (int(w * scale), int(h * scale))) if scale != 1.0 else frame_bgr
        img = Image.fromarray(cv2.cvtColor(small, cv2.COLOR_BGR2RGB))
        boxes, probs = mtcnn.detect(img)
        if boxes is None:
            return []
        keep = [i for i in range(len(boxes)) if probs[i] is not None and probs[i] >= MIN_PROB][:max_faces]
        if not keep:
            return []
        faces = mtcnn.extract(img, boxes[keep], None)        # aligned crops of exactly the kept boxes
        with torch.no_grad():
            embs = resnet(faces.to(device)).cpu().numpy()
        out = []
        for b, e in zip(boxes[keep], embs):
            out.append(Detection(tuple(int(v / scale) for v in b), e / (np.linalg.norm(e) + 1e-8)))
        return out

    return detect_and_embed


def filter_faces(dets: List[Detection], frame_h: int, min_frac: float = 0.5, min_height_frac: float = 0.18) -> List[Detection]:
    """Drop background faces (posters, robot heads). Two rules, both site-calibration knobs:
    absolute: face height must be >= min_height_frac of the frame height (so a small background face is never
              promoted just because the visitor looked down and left the frame);
    relative: face area must be >= min_frac of the largest remaining face.
    Defaults were measured in Jay's lab (robot head <= 16% of the frame height, a seated visitor >= 19%).
    Ceiling: a real second person standing far back is ignored too."""
    big_enough = [d for d in dets if (d.box[3] - d.box[1]) >= min_height_frac * frame_h]
    area = lambda d: (d.box[2] - d.box[0]) * (d.box[3] - d.box[1])
    big = max((area(d) for d in big_enough), default=0)
    return [d for d in big_enough if area(d) >= min_frac * big]
