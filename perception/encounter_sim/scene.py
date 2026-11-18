"""The encounter scene: Joey's tour visitors walk up to the robot at stop 1, one after another, before his tour starts.

One arrival script drives two things:
  the camera  his Part 3 fake scene (perception/integration/run_in_scenario.ScenarioCamera: image-plane layout, no
              pixels, scripted age-estimator outputs), except that each face appears at its own start time and grows to
              full size over GROW_S. Our real Encounter code runs on it.
  the map     each visitor walks from the gallery entrance (south of their stop-1 slot) to the slot, arriving at the
              same time as their face reaches full size. The map is NOT projected into the camera: the two are scripted
              separately and agree only in order and timing.
Arrival order is his visitor order (v1..v6), staggered so that each face passes filter_faces in that order: our tracker
then names them v1..v6 by itself (id_fmt "v{}"), and run.py checks that it did.

TALK is our encounter script, not his sim (it has no such field): how likely each visitor is to answer a group question.
Invented values, consistent with his scripts: v3 asks the most questions, v2 interrupts, v6 is tired, v4 is the reserved
visitor and never answers (D2).
"""

from __future__ import annotations

import math

from perception.integration.run_in_scenario import ScenarioCamera
from sdc.sim import _slot_xy

RATE_HZ = 10
GROW_S = 3.0                 # a face grows from half to full size while its visitor walks the last WALK_M
WALK_M = 3.5
GAP_SAME, GAP_NEXT = 1.5, 1.2    # start-time gap to a companion / to the next cluster: faces pass filter_faces in this order
                                 # (the child's smaller face passes ~0.8 s later than an adult's) with no 3 s lull between them
TALK_P = {"high": 0.9, "medium": 0.5, "low": 0.2, "reserved": 0.0}
TALK = {"v1": "medium", "v2": "high", "v3": "high", "v4": "reserved", "v5": "medium", "v6": "low"}


def starts(people):
    """people: [(track_id, age_class, cluster_id)] in his order -> {track_id: walk start time (s)}."""
    out, t = {}, 0.0
    for i, (tid, _, cl) in enumerate(people):
        if i:
            t += GAP_SAME if cl == people[i - 1][2] else GAP_NEXT
        out[tid] = t
    return out


class ArrivalCamera(ScenarioCamera):
    """ScenarioCamera with staggered arrivals: a face is absent before its start time."""

    def __init__(self, people, bands, seed, start_s):
        super().__init__(people, bands, seed)
        self.start_s = start_s

    def frames_until(self, t_end):
        i = 0
        while i / RATE_HZ <= t_end + 1e-9:
            self.t = round(i / RATE_HZ, 3)
            yield self.t, self.frame
            i += 1

    def boxes(self):
        out = {}
        for tid, (cx, w) in self.layout.items():
            dt = self.t - self.start_s[tid]
            if dt < 0:
                continue
            s = 0.5 + 0.5 * min(dt / GROW_S, 1.0)
            w2, h2 = w * s / 2, 1.2 * w * s / 2
            out[tid] = (int(cx - w2), int(self.frame.shape[0] / 2 - h2), int(cx + w2), int(self.frame.shape[0] / 2 + h2))
        return out


class WalkIn:
    """Map positions for the encounter: entrance -> stop-1 slot, timed by the same start times."""

    def __init__(self, spec, gallery, start_s):
        ex = {e["id"]: e for e in gallery["exhibits"]}[spec.first_stop]
        self.slot = {v.track_id: _slot_xy(ex, v.slots.get(0, v.slot)) for v in spec.visitors}
        self.start_s = start_s

    def at(self, tid, t):
        """(x, y, heading or None when standing)."""
        sx, sy = self.slot[tid]
        t0 = self.start_s[tid]
        if t >= t0 + GROW_S:
            return sx, sy, None
        if t < t0:
            # strolling toward the entrance point at 0.6 m/s (for at most 2 s) before the last stretch
            return sx, sy - WALK_M - 0.6 * min(t0 - t, 2.0), math.pi / 2
        u = (t - t0) / GROW_S
        return sx, sy - WALK_M * (1 - u), math.pi / 2
