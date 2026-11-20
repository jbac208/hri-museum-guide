"""The encounter scene: Joey's tour visitors walk into a reception, one after another, meet the robot there, and then
follow it to stop 1, where his tour starts.

One arrival script drives two things:
  the camera  his Part 3 fake scene (perception/integration/run_in_scenario.ScenarioCamera: image-plane layout, no
              pixels, scripted age-estimator outputs), except that each face appears at its own start time and grows to
              full size over GROW_S. Our real Encounter code runs on it.
  the map     the reception is his stop-1 formation moved by RECEPTION (the lobby south of the gallery): each visitor
              walks in from the door at APPROACH_MPS and stops at their spot, arriving at the same time as their face
              reaches full size. The map is NOT projected into the camera: the two are scripted separately and agree
              only in order and timing. Afterwards everyone walks the same vector back (Move), robot first.
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
GROW_S = 3.0                 # a face grows from half to full size while its visitor walks the last APPROACH_MPS * GROW_S m
APPROACH_MPS = 0.8           # an unhurried stroll in (the first version walked 1.2 m/s)
DOOR_M = 4.5                 # the door is this far from a visitor's spot; those not yet due wait there
RECEPTION = (0.0, -7.0)      # the reception formation = his stop-1 formation moved by this vector (m)
GAP_SAME, GAP_NEXT = 2.0, 2.6    # start-time gap to a companion / to the next cluster: faces pass filter_faces in this order
                                 # (the child's smaller face passes ~0.8 s later than an adult's) and stay under GATHER_S (4 s)
                                 # of each other, so the greeting never fires before the next face appears
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
    """Map positions at the reception: door -> spot, timed by the same start times. slot = where his stop 1 puts them."""

    def __init__(self, spec, gallery, start_s):
        ex = {e["id"]: e for e in gallery["exhibits"]}[spec.first_stop]
        self.slot = {v.track_id: _slot_xy(ex, v.slots.get(0, v.slot)) for v in spec.visitors}
        self.spot = {t: (x + RECEPTION[0], y + RECEPTION[1]) for t, (x, y) in self.slot.items()}
        self.start_s = start_s

    def arrives(self, tid):
        return self.start_s[tid] + GROW_S

    def at(self, tid, t):
        """(x, y, heading or None when standing)."""
        sx, sy = self.spot[tid]
        d = min(APPROACH_MPS * (self.arrives(tid) - t), DOOR_M)
        if d <= 0:
            return sx, sy, None
        return sx, sy - d, math.pi / 2


class Move:
    """A straight walk p0 -> p1 at cruise speed v, with `ramp` seconds of constant acceleration at each end."""

    def __init__(self, p0, p1, t0, v, ramp=1.0):
        self.p0, self.p1, self.t0, self.v, self.ramp = p0, p1, t0, v, ramp
        self.d = math.dist(p0, p1)
        assert self.d >= v * ramp, "walk too short for its ramps"
        self.t1 = t0 + self.d / v + ramp
        self.heading = math.atan2(p1[1] - p0[1], p1[0] - p0[0])

    def at(self, t):
        T = self.t1 - self.t0
        u = min(max(t - self.t0, 0.0), T)
        a, v = self.ramp, self.v
        s = v * u * u / (2 * a) if u < a else self.d - v * (T - u) ** 2 / (2 * a) if u > T - a else v * a / 2 + v * (u - a)
        f = s / self.d
        return self.p0[0] + f * (self.p1[0] - self.p0[0]), self.p0[1] + f * (self.p1[1] - self.p0[1])


def turn(a, b, t, t0, t1):
    """Yaw from a to b between t0 and t1 (shortest way round, eased)."""
    u = min(max((t - t0) / (t1 - t0), 0.0), 1.0)
    u = u * u * (3 - 2 * u)
    return a + ((b - a + math.pi) % (2 * math.pi) - math.pi) * u


class Gaze:
    """Where one visitor looks during the encounter: the idea of his mock._GazeProcess (a mix of targets, each held for a
    random dwell time) with the encounter's moments. Targets use his attention strings: "robot", "visitor:<id>",
    "exhibit:<stop>" (the gallery ahead), "none" (looking off, 2 % flicker as in his sim).
    mode: "quiet" (before the greeting), "robot_talks", "listen" (a visitor is speaking), "talk" (this visitor is),
    "walking", "arrived" (his default mix). A new mode re-samples at once. Invented placeholder values, untuned."""

    DUR = {"robot": (1.0, 2.5), "companion": (0.7, 1.5), "ahead": (1.5, 3.5), "speaker": (1.0, 2.5)}
    MIX = {"quiet": {"robot": 0.35, "ahead": 0.4, "companion": 0.25},
           "robot_talks": {"robot": 0.7, "companion": 0.15, "ahead": 0.15},
           "listen": {"speaker": 0.5, "robot": 0.3, "companion": 0.2},
           "talk": {"robot": 0.8, "companion": 0.1, "ahead": 0.1},
           "walking": {"ahead": 0.5, "robot": 0.3, "companion": 0.2},
           "arrived": {"ahead": 0.6, "robot": 0.3, "companion": 0.1}}

    def __init__(self, rng, companions, stop):
        self.rng, self.companions, self.stop = rng, companions, stop
        self.key, self.current, self.until = None, "none", -1.0

    def step(self, t, mode, speaker=None):
        if self.rng.random() < 0.02:
            return "none"
        if (mode, speaker) != self.key:
            self.key, self.until = (mode, speaker), -1.0
        if t < self.until:
            return self.current
        kinds, weights = zip(*self.MIX[mode].items())
        kind = self.rng.choices(kinds, weights)[0]
        target = ("robot" if kind == "robot" else f"visitor:{speaker}" if kind == "speaker" else
                  f"visitor:{self.rng.choice(self.companions)}" if kind == "companion" and self.companions else f"exhibit:{self.stop}")
        self.current, self.until = target, t + self.rng.uniform(*self.DUR[kind])
        return target
