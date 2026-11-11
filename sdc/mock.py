"""Mock perception generator (stands in for Jay's blocks 1-2 until they're ready).

A scenario scripts each visitor's behaviour over time (positions, what they look at,
posture, speech, pointing). The generator turns that into a schema-v0.1 stream and
derives the geometric fields (line of sight, in formation, overlapped speech, head yaw)
from the scripted state, so they stay consistent with each other.

Open-loop: visitors don't react to the robot. Closed-loop visitor reactions (uptake)
come with the decision layer.
"""
import json
import math
import random
from dataclasses import dataclass, field

from . import schema

PERSON_RADIUS = 0.25          # m, body disc used for occlusion
EYE_DROP = 0.12               # m, eye height below head top
FORMATION_RING = (1.0, 2.6)   # m from exhibit centre counts as "in formation"


@dataclass
class Speech:
    t0: float
    t1: float
    text: str = ""
    is_question: bool = False


@dataclass
class Window:
    """A scripted override active for t0 <= t < t1."""
    t0: float
    t1: float
    attention: str | None = None         # fixed attention target, e.g. "feature:figurehead.carving"
    gaze_mix: dict | None = None         # replaces default mix while active
    robot_glance_s: tuple | None = None  # (min, max) robot-glance duration while active
    body_target: str | None = None       # exhibit id, or "away"
    posture: str | None = None
    pointing_at: str | None = None


@dataclass
class VisitorScript:
    track_id: str
    age_class: str
    height: float
    cluster_id: str
    path: list                                   # [(t, x, y)] keyframes, linear in between
    gaze_mix: dict = field(default_factory=lambda: {"exhibit": 0.6, "robot": 0.3, "companion": 0.1})
    windows: list = field(default_factory=list)
    speech: list = field(default_factory=list)
    age_conf: float = 0.9
    responded_to_steer_invite: bool = False
    pending_layers: list = field(default_factory=list)


@dataclass
class Scenario:
    name: str
    stop: str                         # exhibit id for this stop
    duration_s: float
    robot_pose: tuple                 # (x, y)
    robot_speech: list                # [Speech]
    visitors: list                    # [VisitorScript]
    labels: list                      # ground truth, see LABEL_KINDS
    rate_hz: int = 10
    seed: int = 7


LABEL_KINDS = {"linger", "approach", "point_ask", "drift", "fatigue",
               "bid", "barrier", "excluded", "expect_no_events"}


# ---------------------------------------------------------------- geometry

def _lerp_path(path, t):
    if t <= path[0][0]:
        return path[0][1], path[0][2]
    for (ta, xa, ya), (tb, xb, yb) in zip(path, path[1:]):
        if ta <= t <= tb:
            u = (t - ta) / (tb - ta) if tb > ta else 0.0
            return xa + u * (xb - xa), ya + u * (yb - ya)
    return path[-1][1], path[-1][2]


def _seg_point_dist(ax, ay, bx, by, px, py):
    dx, dy = bx - ax, by - ay
    L2 = dx * dx + dy * dy
    if L2 == 0:
        return math.hypot(px - ax, py - ay), 0.0
    u = ((px - ax) * dx + (py - ay) * dy) / L2
    u_c = max(0.0, min(1.0, u))
    return math.hypot(ax + u_c * dx - px, ay + u_c * dy - py), u


def line_of_sight(viewer, target_xy, others):
    """viewer/others: dicts with x, y, height. Blocked if a person at least as tall
    as the viewer's eyes stands on the segment between viewer and target."""
    eye = viewer["height"] - EYE_DROP
    for o in others:
        d, u = _seg_point_dist(viewer["x"], viewer["y"], target_xy[0], target_xy[1], o["x"], o["y"])
        if 0.05 < u < 0.95 and d < PERSON_RADIUS and o["height"] >= eye - 0.05:
            return False
    return True


def _yaw_to(ax, ay, bx, by):
    return math.atan2(by - ay, bx - ax)


def _wrap(a):
    return (a + math.pi) % (2 * math.pi) - math.pi


# ---------------------------------------------------------------- generator

class _GazeProcess:
    """Samples a sequence of attention targets with natural dwell durations."""
    DUR = {"exhibit": (2.0, 5.0), "robot": (1.0, 2.5), "companion": (0.7, 1.5)}

    def __init__(self, rng, script, companions, features, stop):
        self.rng, self.s, self.companions = rng, script, companions
        self.features, self.stop = features, stop
        self.current, self.until = "none", -1.0

    def _window(self, t):
        """All windows active at t merged; later windows override earlier ones field by field."""
        active = [w for w in self.s.windows if w.t0 <= t < w.t1]
        if not active:
            return None
        merged = Window(t, t)
        for w in active:
            for k, v in vars(w).items():
                if k not in ("t0", "t1") and v is not None:
                    setattr(merged, k, v)
        return merged

    def step(self, t):
        w = self._window(t)
        if w and w.attention:
            # small flicker so fixed attention isn't perfectly clean
            return "none" if self.rng.random() < 0.02 else w.attention
        if t < self.until:
            return self.current
        mix = (w.gaze_mix if w and w.gaze_mix else self.s.gaze_mix)
        kinds, weights = zip(*mix.items())
        kind = self.rng.choices(kinds, weights)[0]
        lo, hi = self.DUR[kind]
        if kind == "robot" and w and w.robot_glance_s:
            lo, hi = w.robot_glance_s
        if kind == "exhibit":
            target = self.rng.choice([f"exhibit:{self.stop}"] + [f"feature:{f}" for f in self.features])
        elif kind == "robot":
            target = "robot"
        else:
            target = f"visitor:{self.rng.choice(self.companions)}" if self.companions else f"exhibit:{self.stop}"
        self.current, self.until = target, t + self.rng.uniform(lo, hi)
        return target


def generate(scn: Scenario, gallery: dict):
    rng = random.Random(scn.seed)
    ex = {e["id"]: e for e in gallery["exhibits"]}
    feat_xy = {f["id"]: (f["x"], f["y"]) for e in gallery["exhibits"] for f in e["features"]}
    stop = ex[scn.stop]
    stop_xy = (stop["x"], stop["y"])
    rx, ry = scn.robot_pose

    clusters = {}
    for v in scn.visitors:
        clusters.setdefault(v.cluster_id, []).append(v.track_id)
    gaze = {v.track_id: _GazeProcess(rng, v, [c for c in clusters[v.cluster_id] if c != v.track_id],
                                     [f["id"] for f in stop["features"]], scn.stop)
            for v in scn.visitors}

    lines = [{"type": "header", "schema_version": schema.SCHEMA_VERSION, "rate_hz": scn.rate_hz,
              "gallery": gallery["id"], "scenario": scn.name}]

    # start impression (what Jay's half would hand over)
    pos0 = {v.track_id: _lerp_path(v.path, 0.0) for v in scn.visitors}
    cx = sum(p[0] for p in pos0.values()) / len(pos0)
    cy = sum(p[1] for p in pos0.values()) / len(pos0)
    lines.append({
        "type": "start_impression", "t": 0.0,
        "visitors": [{
            "track_id": v.track_id, "age_class": v.age_class, "age_conf": v.age_conf,
            "cluster_id": v.cluster_id,
            "baseline_seed": {
                "distance_m": round(math.dist(pos0[v.track_id], stop_xy), 2),
                "robot_glances_per_min": 6.0 if v.age_class == "child" else 4.0,
                "speech_frac": 0.05,
            },
            "pending_layers": v.pending_layers,
            "responded_to_steer_invite": v.responded_to_steer_invite,
        } for v in scn.visitors],
        "group": {"size": len(scn.visitors),
                  "spread_m": round(max(math.dist(p, (cx, cy)) for p in pos0.values()), 2)},
    })

    def speaking_at(speeches, t):
        for s in speeches:
            if s.t0 <= t < s.t1:
                return s
        return None

    events = []  # utterances, emitted at speech end
    for v in scn.visitors:
        for s in v.speech:
            events.append({"type": "utterance", "t": round(s.t1, 2), "track_id": v.track_id,
                           "text": s.text, "is_question": s.is_question,
                           "duration_s": round(s.t1 - s.t0, 2)})

    n = int(scn.duration_s * scn.rate_hz)
    for i in range(n):
        t = round(i / scn.rate_hz, 3)
        robot_sp = speaking_at(scn.robot_speech, t)
        # true state
        state = {}
        for v in scn.visitors:
            x, y = _lerp_path(v.path, t)
            state[v.track_id] = {"x": x, "y": y, "height": v.height}
        cx = sum(s["x"] for s in state.values()) / len(state)
        cy = sum(s["y"] for s in state.values()) / len(state)
        robot_yaw = _yaw_to(rx, ry, cx, cy)

        out = []
        for v in scn.visitors:
            s = state[v.track_id]
            others = [state[o.track_id] for o in scn.visitors if o is not v]
            w = gaze[v.track_id]._window(t)
            att = gaze[v.track_id].step(t)

            # head yaw from attention target
            if att == "robot":
                tx, ty = rx, ry
            elif att.startswith("feature:"):
                tx, ty = feat_xy[att[8:]]
            elif att.startswith("exhibit:"):
                tx, ty = ex[att[8:]]["x"], ex[att[8:]]["y"]
            elif att.startswith("visitor:"):
                o = state[att[8:]]
                tx, ty = o["x"], o["y"]
            else:
                tx, ty = s["x"] + rng.uniform(-1, 1), s["y"] - 1.5  # looking off somewhere
            head = _yaw_to(s["x"], s["y"], tx, ty)

            bt = w.body_target if w and w.body_target else scn.stop
            if bt == "away":
                body = _wrap(_yaw_to(s["x"], s["y"], *stop_xy) + math.pi)
            else:
                body = _yaw_to(s["x"], s["y"], ex[bt]["x"], ex[bt]["y"])

            my_sp = speaking_at(v.speech, t)
            overlapped = False
            if my_sp:
                rivals = [robot_sp] + [speaking_at(o.speech, t) for o in scn.visitors if o is not v]
                overlapped = any(r and r.t0 < my_sp.t0 for r in rivals)

            out.append({
                "track_id": v.track_id,
                "x": round(s["x"] + rng.gauss(0, 0.03), 3),
                "y": round(s["y"] + rng.gauss(0, 0.03), 3),
                "body_yaw": round(_wrap(body + rng.gauss(0, 0.05)), 3),
                "head_yaw": round(_wrap(head + rng.gauss(0, 0.08)), 3),
                "attention": att,
                "speaking": my_sp is not None,
                "overlapped": overlapped,
                "los_exhibit": line_of_sight(s, stop_xy, others),
                "los_robot": line_of_sight(s, (rx, ry), others),
                "in_formation": FORMATION_RING[0] <= math.dist((s["x"], s["y"]), stop_xy) <= FORMATION_RING[1],
                "cluster_id": v.cluster_id,
                "age_class": v.age_class,
                "age_conf": v.age_conf,
                "posture": (w.posture if w and w.posture else "standing"),
                "pointing_at": (w.pointing_at if w and w.pointing_at else None),
                "track_conf": round(min(1.0, max(0.5, rng.gauss(0.95, 0.02))), 3),
            })
        lines.append({"type": "frame", "t": t,
                      "robot": {"x": rx, "y": ry, "yaw": round(robot_yaw, 3), "speaking": robot_sp is not None},
                      "visitors": out})

    # merge utterances into the stream in time order (after the header + impression)
    body = lines[2:] + events
    body.sort(key=lambda o: (o["t"], 0 if o["type"] == "frame" else 1))
    return lines[:2] + body


def write(scn: Scenario, gallery: dict, stream_path, labels_path):
    for lab in scn.labels:
        assert lab["kind"] in LABEL_KINDS, lab
    lines = generate(scn, gallery)
    schema.validate_stream(lines)
    with open(stream_path, "w") as f:
        for o in lines:
            f.write(json.dumps(o, separators=(",", ":")) + "\n")
    with open(labels_path, "w") as f:
        json.dump({"scenario": scn.name, "labels": scn.labels}, f, indent=2)
    return len(lines)
