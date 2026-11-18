"""Visit-scoped face tracker: IoU plus face-embedding cosine. Ported from Jay's repo
(`HRI-2027-SDC-Museum-Guide-robot`, branch `museum-visual-profile`, `modules/museum/appearance.py`).

Config is a plain dict merged over DEFAULTS (same values as the old `config/museum_appearance.yaml`); nothing is read
from disk. Embeddings live in memory only and are dropped with the track or on clear().
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional, Sequence, Tuple

import numpy as np

Box = Tuple[int, int, int, int]  # x1, y1, x2, y2 in pixels

# reid_min_cos / reid_gap: same-person cosine was checked on 8 views of one person (min 0.42 / mean 0.67 / max 0.87);
# the different-person range was NEVER measured, so 0.6 / 0.1 are unvalidated.
DEFAULTS = {
    "track_iou": 0.3, "track_max_missed": 30,
    "reid_min_cos": 0.6, "reid_gap": 0.1, "reid_ttl": 300, "iou_weight": 0.3, "overlap_ambiguous": 0.2,
    "match_margin": 0.15, "conf_ambiguous": 0.2, "conf_recover": 0.2, "new_track_conf": 0.6,
    "id_fmt": "visitor_{}",          # the encounter sim uses "v{}" so its ids are the tour's ids
}


def _iou(a: Box, b: Box) -> float:
    ix = max(0, min(a[2], b[2]) - max(a[0], b[0]))
    iy = max(0, min(a[3], b[3]) - max(a[1], b[1]))
    inter = ix * iy
    union = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter
    return inter / union if union > 0 else 0.0


@dataclass
class Detection:
    """A face box, optionally with its 512-d face embedding. The embedding is used for in-memory re-association
    only: it is never written to disk and is dropped with the track."""
    box: Box
    emb: Optional[np.ndarray] = None


def _unit(v: np.ndarray) -> np.ndarray:
    v = np.asarray(v, dtype=np.float64)
    return v / (np.linalg.norm(v) + 1e-12)


class VisitTracker:
    """In-memory tracker assigning visit-scoped ids ``visitor_N``; ids are never reused for a
    different person within a visit. Nothing is persisted.

    Association (per frame):
      1. continuity: match detections to live tracks by IoU, combined with embedding
         cosine (iou_weight 0.3, so the face outweighs position) when both sides have one; a pair is a candidate if IoU >= track_iou or
         cosine >= reid_min_cos.
      2. re-association: a still-unmatched detection with an embedding may take back the id of a
         LOST track (gone > track_max_missed frames, kept up to reid_ttl) when its best cosine is
         >= reid_min_cos AND beats the second-best track (lost or live) by >= reid_gap. Otherwise it
         gets a NEW id: a wrongly new id only loses a profile, a wrong merge corrupts one, so ties
         and look-alikes (relatives) fail toward "new person".
    ``track_conf`` (0..1, a heuristic, not a probability) per track: a match whose margin over the runner-up is
    < match_margin is ambiguous and drops it to conf_ambiguous; clean matches recover it by conf_recover per frame;
    a re-associated or new track starts at new_track_conf.

    Limits: a swap the tracker cannot see (no embeddings, people exchange places while occluded)
    is silent; track_conf does not drop. Synthetic embeddings in the tests cannot show how well
    real faces, relatives especially, separate.
    """

    def __init__(self, cfg: Optional[dict] = None):
        c = {**DEFAULTS, **(cfg or {})}
        self._c = c
        self._tracks: Dict[str, dict] = {}
        self._n = 0

    def _new(self, det: Detection, conf: Optional[float] = None) -> str:
        self._n += 1
        tid = self._c["id_fmt"].format(self._n)
        self._tracks[tid] = {"box": det.box, "missed": 0, "streak": 1,
                             "emb": None if det.emb is None else _unit(det.emb),
                             "conf": self._c["new_track_conf"] if conf is None else conf}
        return tid

    def _pair_score(self, t: dict, d: Detection) -> Optional[float]:
        iou = _iou(t["box"], d.box) if t["missed"] <= self._c["track_max_missed"] else 0.0
        cos = None if (t["emb"] is None or d.emb is None) else float(t["emb"] @ _unit(d.emb))
        if iou < self._c["track_iou"] and not (cos is not None and cos >= self._c["reid_min_cos"]):
            return None
        return iou if cos is None else self._c["iou_weight"] * iou + (1 - self._c["iou_weight"]) * max(cos, 0.0)

    def assign_detections(self, dets: Sequence[Detection]) -> List[str]:
        c = self._c
        live = [tid for tid, t in self._tracks.items() if t["missed"] <= c["track_max_missed"]]
        scores = {}
        for tid in live:
            for i, d in enumerate(dets):
                sc = self._pair_score(self._tracks[tid], d)
                if sc is not None:
                    scores[(tid, i)] = sc
        ids: List[Optional[str]] = [None] * len(dets)
        used: Dict[str, int] = {}
        for (tid, i), sc in sorted(scores.items(), key=lambda kv: -kv[1]):
            if tid in used or ids[i] is not None:
                continue
            ids[i], used[tid] = tid, i
        # 2. re-association of leftovers against LOST tracks (need an embedding on both sides)
        for i, d in enumerate(dets):
            if ids[i] is not None:
                continue
            tid = None
            if d.emb is not None:
                cos = sorted(((float(t["emb"] @ _unit(d.emb)), k) for k, t in self._tracks.items()
                              if t["emb"] is not None and k not in used), reverse=True)
                if cos and cos[0][0] >= c["reid_min_cos"] \
                        and self._tracks[cos[0][1]]["missed"] > c["track_max_missed"] \
                        and (len(cos) == 1 or cos[0][0] - cos[1][0] >= c["reid_gap"]):
                    tid = cos[0][1]
            if tid is None:
                ids[i] = self._new(d)
                used[ids[i]] = i
            else:
                t = self._tracks[tid]
                t.update(box=d.box, missed=0, conf=c["new_track_conf"], streak=1)
                ids[i], used[tid] = tid, i
        # confidence + embedding update for continuity matches
        for tid, i in list(used.items()):
            if self._tracks[tid]["missed"] == 0 and (tid, i) not in scores:
                continue                                # new / re-associated this frame
            t, d = self._tracks[tid], dets[i]
            rivals = [sc for (k, j), sc in scores.items() if (k == tid) != (j == i)]
            ambiguous = bool(rivals) and scores[(tid, i)] - max(rivals) < c["match_margin"]
            # overlapping faces with no embedding to tell them apart: position alone cannot be trusted
            ambiguous = ambiguous or any(
                j != i and _iou(d.box, o.box) >= c["overlap_ambiguous"] and (d.emb is None or o.emb is None)
                for j, o in enumerate(dets))
            t["conf"] = c["conf_ambiguous"] if ambiguous else min(1.0, t["conf"] + c["conf_recover"])
            t["box"], t["missed"] = d.box, 0
            t["streak"] += 1                              # consecutive frames this track has been matched
            if d.emb is not None and not ambiguous:
                t["emb"] = _unit(d.emb) if t["emb"] is None else _unit(0.9 * t["emb"] + 0.1 * _unit(d.emb))
        for tid in list(self._tracks):
            if tid not in used:
                t = self._tracks[tid]
                t["missed"] += 1
                t["streak"] = 0
                # a track with no embedding cannot be re-associated, so it dies when it goes stale
                limit = c["track_max_missed"] if t["emb"] is None else max(c["reid_ttl"], c["track_max_missed"])
                if t["missed"] > limit:
                    del self._tracks[tid]
        return ids  # type: ignore[return-value]

    def assign(self, boxes: Sequence[Box]) -> List[str]:
        return self.assign_detections([Detection(tuple(b)) for b in boxes])

    def streak(self, tid: str) -> int:
        return self._tracks[tid]["streak"] if tid in self._tracks else 0

    def confidence(self, tid: str) -> float:
        return self._tracks[tid]["conf"] if tid in self._tracks else 0.0

    def alive(self) -> List[str]:
        """Ids seen recently (not merely remembered for re-association)."""
        return [k for k, t in self._tracks.items() if t["missed"] <= self._c["track_max_missed"]]

    def known(self) -> List[str]:
        return list(self._tracks)

    def clear(self) -> None:
        """Drop every track and embedding (called when the encounter ends)."""
        self._tracks.clear()
