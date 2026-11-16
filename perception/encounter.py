"""Initial encounter (Jay's block 1): run perception until the engagement event, then build ONE start_impression that
passes sdc.schema.validate_start_impression (interface v0.1).

Per frame: detect -> filter_faces -> track + age band -> stable-frame gate -> companion clusters -> engagement.
A visitor enters the output only after `stable_frames` consecutive matched frames. Face embeddings and all per-visitor
state live in memory only and are wiped by end(); run() always calls it, also on error.

Fields the code cannot measure come only from PLACEHOLDER and are named in the output's `placeholder_fields`.
See perception/INTERFACE_NOTES.md for what each would take to measure.
"""

from __future__ import annotations

from typing import Callable, Iterable, Optional

from sdc import schema

from .age import AgeBandPipeline
from .engagement import EngagementEngine
from .faces import filter_faces
from .group import GroupContext, GroupTracker

STABLE_FRAMES = 5

# NOT MEASURED. Values copied from Joey's mock (sdc/mock.py World.start_lines; spread_m is its s1_one_stop value) so
# his loop behaves as in his own simulations. distance_m and robot_glances_per_min matter: his signal layer counts the
# seed like SEED_WEIGHT_S (30 s) of observation at the first stop.
PLACEHOLDER = {
    "distance_m": 2.2,                      # metres to the EXHIBIT; the camera only gives an uncalibrated face-box ratio
    "robot_glances_per_min": {"adult": 4.0, "child": 6.0, "unsure": 5.0},   # no head-pose model; unsure = midpoint
    "speech_frac": 0.05,                    # no audio
    "responded_to_steer_invite": False,     # no steering invitation exists
    "spread_m": 1.96,                       # image plane only, no metric positions
}
PLACEHOLDER_FIELDS = [
    "group.spread_m",
    "visitors[].baseline_seed.distance_m",
    "visitors[].baseline_seed.robot_glances_per_min",
    "visitors[].baseline_seed.speech_frac",
    "visitors[].responded_to_steer_invite",
]


def build_start_impression(t: float, results: list, context: Callable[[str], GroupContext]) -> dict:
    """results: pipeline dicts of the visitors to include. Validated against Joey's schema before it is returned."""
    P = PLACEHOLDER
    visitors = []
    for r in results:
        pid, band = r["person_id"], r["band"]
        ctx = context(pid)
        visitors.append({
            "track_id": pid,
            # schema v0.1 has no "unsure": emit the more likely class with its own mass (question for Joey)
            "age_class": "child" if r["p_child"] > r["p_adult"] else "adult",
            "age_conf": round(r["confidence"], 3),
            # unknown context: a cluster of one, so no companionship is claimed
            "cluster_id": ctx.group_id if ctx.status == "known" else f"solo_{pid}",
            "baseline_seed": {"distance_m": P["distance_m"],
                              "robot_glances_per_min": P["robot_glances_per_min"][band],
                              "speech_frac": P["speech_frac"]},
            "pending_layers": [],                   # interests are never guessed from appearance
            "responded_to_steer_invite": P["responded_to_steer_invite"],
            # extra fields (the validator and sdc/adapter.py ignore them)
            "age_band": band, "p_child": round(r["p_child"], 3), "p_adult": round(r["p_adult"], 3),
        })
    si = {"type": "start_impression", "t": round(t, 3), "visitors": visitors,
          "group": {"size": len(visitors), "spread_m": P["spread_m"]},
          "placeholder_fields": list(PLACEHOLDER_FIELDS)}
    schema.validate_start_impression(si)
    return si


def _num(pid: str) -> int:
    return int(pid.rsplit("_", 1)[1])


class Encounter:
    """detect_fn(frame) -> [Detection]; estimator: FairFaceAgeEstimator or FakeAgeEstimator.
    cfg: optional {"age": {...}, "group": {...}, "engagement": {...}} merged over each module's DEFAULTS.
    face_filter: keyword arguments for filter_faces (site calibration)."""

    def __init__(self, estimator, detect_fn: Callable, *, stable_frames: int = STABLE_FRAMES,
                 cfg: Optional[dict] = None, face_filter: Optional[dict] = None):
        cfg, ff = cfg or {}, face_filter or {}
        self.stable_frames = stable_frames
        self.pipeline = AgeBandPipeline(estimator, lambda f: filter_faces(detect_fn(f), f.shape[0], **ff), cfg.get("age"))
        self.groups = GroupTracker({"stable_frames": stable_frames, **(cfg.get("group") or {})})
        self.engagement = EngagementEngine(self.groups.context, self.groups.members, cfg.get("engagement"))
        self.stable: set = set()       # ids that passed the gate; kept for the encounter
        self.latest: dict = {}         # id -> this frame's pipeline result
        self.frame_h = 0

    def step(self, t: float, frame):
        """One frame. Returns the EngageEvent if it fired on this frame, else None."""
        self.frame_h = frame.shape[0]
        res = self.pipeline.process(frame)
        self.latest = {r["person_id"]: r for r in res}
        self.stable |= {r["person_id"] for r in res if r["streak"] >= self.stable_frames}
        self.groups.update(t, res)
        obs = [{"person_id": r["person_id"], "box": r["box"], "track_conf": r["track_conf"],
                "eligible": r["person_id"] in self.stable} for r in res]
        ev = self.engagement.update(t, self.frame_h, obs)
        return ev[0] if ev else None

    def start_impression(self, ev) -> dict:
        """Every stable visitor in view at the event, not only the event's members: the impression describes the
        whole group in front of the robot (a nearby bystander included, see INTERFACE_NOTES)."""
        vs = sorted((r for pid, r in self.latest.items() if pid in self.stable), key=lambda r: _num(r["person_id"]))
        return build_start_impression(ev.t, vs, self.groups.context)

    def end(self) -> None:
        """Wipe tracks, embeddings, age smoothers, clusters and the gate."""
        self.pipeline.clear()
        self.groups.clear()
        self.stable.clear()
        self.latest = {}

    def run(self, frames: Iterable, on_frame: Optional[Callable] = None) -> Optional[dict]:
        """frames: (t, frame) pairs. Returns the start_impression at the first engagement event, or None if the frames
        run out first. on_frame(t, encounter, event) is called after every frame (progress output)."""
        try:
            for t, frame in frames:
                ev = self.step(t, frame)
                if on_frame:
                    on_frame(t, self, ev)
                if ev is not None:
                    return self.start_impression(ev)
            return None
        finally:
            self.end()
