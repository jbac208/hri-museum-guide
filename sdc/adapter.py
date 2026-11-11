"""The one place block 3 reads the perception stream (interface v0.1).

Everything downstream uses these dataclasses, never raw JSON keys, so a field
change in the interface only touches this file.
"""
import json
from dataclasses import dataclass, field


@dataclass
class Header:
    schema_version: str
    rate_hz: float
    gallery: str
    scenario: str


@dataclass
class VisitorSeed:
    track_id: str
    age_class: str
    age_conf: float
    cluster_id: str
    distance_m: float
    robot_glances_per_min: float
    speech_frac: float
    pending_layers: list
    responded_to_steer_invite: bool


@dataclass
class StartImpression:
    t: float
    visitors: dict                 # track_id -> VisitorSeed
    group_size: int
    group_spread_m: float


@dataclass
class Obs:
    """One visitor in one frame."""
    track_id: str
    x: float
    y: float
    body_yaw: float
    head_yaw: float
    attention: str
    speaking: bool
    overlapped: bool
    los_exhibit: bool
    los_robot: bool
    in_formation: bool
    cluster_id: str
    age_class: str
    posture: str
    pointing_at: str | None
    track_conf: float


@dataclass
class Robot:
    x: float
    y: float
    yaw: float
    speaking: bool


@dataclass
class Frame:
    t: float
    robot: Robot
    visitors: dict = field(default_factory=dict)   # track_id -> Obs


@dataclass
class Utterance:
    t: float                       # end of speech
    track_id: str
    text: str
    is_question: bool
    duration_s: float


def parse(o: dict):
    typ = o["type"]
    if typ == "header":
        return Header(o["schema_version"], o["rate_hz"], o["gallery"], o["scenario"])
    if typ == "start_impression":
        vs = {}
        for v in o["visitors"]:
            s = v["baseline_seed"]
            vs[v["track_id"]] = VisitorSeed(
                v["track_id"], v["age_class"], v["age_conf"], v["cluster_id"],
                s["distance_m"], s["robot_glances_per_min"], s["speech_frac"],
                list(v["pending_layers"]), v["responded_to_steer_invite"])
        return StartImpression(o["t"], vs, o["group"]["size"], o["group"]["spread_m"])
    if typ == "frame":
        r = o["robot"]
        f = Frame(o["t"], Robot(r["x"], r["y"], r["yaw"], r["speaking"]))
        for v in o["visitors"]:
            f.visitors[v["track_id"]] = Obs(
                v["track_id"], v["x"], v["y"], v["body_yaw"], v["head_yaw"], v["attention"],
                v["speaking"], v["overlapped"], v["los_exhibit"], v["los_robot"], v["in_formation"],
                v["cluster_id"], v["age_class"], v["posture"], v.get("pointing_at"), v["track_conf"])
        return f
    if typ == "utterance":
        return Utterance(o["t"], o["track_id"], o["text"], o["is_question"], o["duration_s"])
    raise ValueError(f"unknown line type {typ!r}")


def read(path):
    """Yield parsed records from a JSONL stream, in file order."""
    with open(path) as fh:
        for line in fh:
            line = line.strip()
            if line:
                yield parse(json.loads(line))


def from_lines(lines):
    """Same as read(), for already-parsed dicts (e.g. mock.generate output)."""
    for o in lines:
        yield parse(o)
