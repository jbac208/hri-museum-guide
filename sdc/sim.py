"""Closed-loop visitor simulator (task 5): scripted visitors who also react to the robot.

Each tick the sim builds a schema-v0.1 frame (mock.World) from the visitors' scripts, using the
robot pose and speech the decision layer actually commanded, so line of sight, formation and
"talked over" follow the robot. The loop consumes the frame; the sim then reads the new actions
and edits the visitors' scripts live:

  addition said    each visitor with a matching hidden interest takes it up with P_UPTAKE_MATCH
                   (looks at its target for LOOK_S; for depth also steps STEP_M closer); others
                   react with P_UPTAKE_OTHER. No reaction -> the loop should rescind (a misread).
  formation opened the robot glances/turns toward an excluded visitor who has a `join_xy`: with
                   P_JOIN they walk there (into the formation) after JOIN_DELAY_S.
  speech           visitors' questions are SimSpeech with a mode: "at" (fixed time), "gap" (waits
                   until the robot is quiet; polite adults) or "interrupt" (starts INTERRUPT_AFTER_S
                   into the robot's next utterance; the child). Utterances are emitted at speech end.

The sim is a test harness, not part of the robot, so its parameters live here, not in config.py.
Hidden interests are the sim's ground truth; the robot never sees them.
"""
import json
import random
from dataclasses import dataclass, field

from . import adapter, schema
from .mock import Scenario, Speech, Window, World, _lerp_path, utterance_line

P_UPTAKE_MATCH = 0.85
P_UPTAKE_OTHER = 0.05
REACT_DELAY_S = (1.0, 2.5)
LOOK_S = (7.0, 10.0)
STEP_M = 0.35
STEP_S = 2.0
P_JOIN = 1.0
JOIN_DELAY_S = (1.0, 3.0)
JOIN_MOVE_S = 3.0
INTERRUPT_AFTER_S = 1.0
GAP_QUIET_S = 0.5


@dataclass
class SimSpeech:
    not_before: float
    duration_s: float
    text: str
    is_question: bool = True
    mode: str = "gap"            # at | gap | interrupt
    done: bool = False


@dataclass
class SimSpec:
    scenario: Scenario           # scripted behaviour (paths, gaze windows, posture); speech comes from `speech`
    interests: dict = field(default_factory=dict)   # track_id -> {(kind, target)}  hidden ground truth
    join_xy: dict = field(default_factory=dict)     # track_id -> (x, y) they move to when the formation opens
    speech: dict = field(default_factory=dict)      # track_id -> [SimSpeech]
    seed: int = 11


class Sim:
    def __init__(self, spec: SimSpec, gallery):
        self.spec, self.scn = spec, spec.scenario
        self.world = World(self.scn, gallery, random.Random(self.scn.seed))
        self.rng = random.Random(spec.seed)
        self.v = {v.track_id: v for v in self.scn.visitors}
        for v in self.scn.visitors:
            v.speech = []        # all visitor speech is reactive in the sim
        self.pose = [self.scn.robot_pose[0], self.scn.robot_pose[1], None]
        self.robot_says = []     # say_to_group Actions (duration may shrink if cut)
        self.pending_utt = []    # (t_end, track_id, Speech)
        self.joined = set()
        self.reactions = []      # log of what the sim made visitors do (for tests / the replay)

    # ------------------------------------------------------------ robot state from actions
    def _robot_speech(self, t):
        for a in self.robot_says:
            if a.t <= t < a.t + a.duration_s:
                return Speech(a.t, a.t + a.duration_s)
        return None

    def _robot_quiet_for(self, t, s):
        return all(not (a.t - s <= t and t < a.t + a.duration_s + s) for a in self.robot_says)

    def on_action(self, a, t_now):
        if a.kind == "say_to_group":
            self.robot_says.append(a)
            aid = str(a.args.get("id") or "")
            if ".add." in aid and not a.args.get("resume"):
                self._react_to_addition(a, aid)
        elif a.kind == "turn_body":
            self.pose[2] = a.args["yaw"]
        elif a.kind == "step_to":
            self.pose[0], self.pose[1] = a.args["x"], a.args["y"]
            if "widen the formation" in a.reason:
                for tid in self.spec.join_xy:
                    self._react_to_opening(tid, a.t)
        elif a.kind == "gaze_at" and a.reason.startswith("excluded (bid + position"):
            self._react_to_opening(a.args["target"][8:], a.t)

    def _move(self, tid, t0, xy, dur):
        v = self.v[tid]
        x, y = _lerp_path(v.path, t0)
        v.path = [k for k in v.path if k[0] < t0] + [(t0, x, y), (t0 + dur, xy[0], xy[1])]

    def _react_to_opening(self, tid, t):
        if tid in self.joined or tid not in self.spec.join_xy or self.rng.random() >= P_JOIN:
            return
        self.joined.add(tid)
        t0 = t + self.rng.uniform(*JOIN_DELAY_S)
        self._move(tid, t0, self.spec.join_xy[tid], JOIN_MOVE_S)
        self.reactions.append({"t": round(t0, 2), "track_id": tid, "reaction": "joins the formation"})

    def _react_to_addition(self, a, aid):
        from .content import load   # content lookup only to read `serves`/`look` of the addition
        exhibit = load(aid.split(".add.")[0])
        add = exhibit.addition(aid)
        serves = {(s["kind"], s["target"]) for s in add.serves}
        for tid, v in self.v.items():
            match = bool(serves & self.spec.interests.get(tid, set()))
            if self.rng.random() >= (P_UPTAKE_MATCH if match else P_UPTAKE_OTHER):
                if match:
                    self.reactions.append({"t": a.t, "track_id": tid, "reaction": f"ignores {aid} (despite interest)"})
                continue
            t0 = a.t + self.rng.uniform(*REACT_DELAY_S)
            look = add.look
            v.windows.append(Window(t0, t0 + self.rng.uniform(*LOOK_S), attention=look))
            what = f"looks at {look}"
            if add.type == "depth":
                x, y = _lerp_path(v.path, t0)
                ex = self.world.stop_xy
                d = ((x - ex[0]) ** 2 + (y - ex[1]) ** 2) ** 0.5 or 1.0
                self._move(tid, t0, (x - STEP_M * (x - ex[0]) / d, y - STEP_M * (y - ex[1]) / d), STEP_S)
                what += f", steps {STEP_M} m closer"
            self.reactions.append({"t": round(t0, 2), "track_id": tid,
                                   "reaction": f"takes up {aid}: {what}" + ("" if match else " (no hidden interest)")})

    # ------------------------------------------------------------ visitor speech
    def _trigger_speech(self, t):
        rsp = self._robot_speech(t)
        for tid, items in self.spec.speech.items():
            for s in items:
                if s.done or t < s.not_before or any(x.t0 <= t < x.t1 for x in self.v[tid].speech):
                    continue
                go = (s.mode == "at"
                      or (s.mode == "gap" and self._robot_quiet_for(t, GAP_QUIET_S))
                      or (s.mode == "interrupt" and rsp is not None and t - rsp.t0 >= INTERRUPT_AFTER_S))
                if go:
                    s.done = True
                    sp = Speech(t, t + s.duration_s, s.text, s.is_question)
                    self.v[tid].speech.append(sp)
                    self.v[tid].windows.append(Window(t, sp.t1, attention="robot"))
                    self.pending_utt.append((sp.t1, tid, sp))
                break   # one pending item per visitor at a time, in order

    # ------------------------------------------------------------ stream
    def start_lines(self):
        return self.world.start_lines()

    def step(self, t):
        self._trigger_speech(t)
        lines = [self.world.frame(t, (self.pose[0], self.pose[1]), self.pose[2], self._robot_speech(t))]
        for item in sorted([u for u in self.pending_utt if u[0] <= t + 1e-9], key=lambda u: u[0]):
            self.pending_utt.remove(item)
            lines.append(utterance_line(item[1], item[2]))
        return lines


def run_closed_loop(spec, gallery, loop_factory, validate=True):
    """Drive sim and loop together. loop_factory(scenario) -> Loop. Returns (loop, sim, lines, result)."""
    sim = Sim(spec, gallery)
    scn = spec.scenario
    loop = loop_factory(scn)
    lines = []

    def feed(line):
        if validate:
            schema.validate_line(line)
        lines.append(line)
        loop.step(adapter.parse(line))

    for line in sim.start_lines():
        feed(line)
    k = 0
    for i in range(int(scn.duration_s * scn.rate_hz)):
        t = round(i / scn.rate_hz, 3)
        for line in sim.step(t):
            feed(line)
        for a in loop.ctrl.actions[k:]:
            sim.on_action(a, t)
        k = len(loop.ctrl.actions)
    result = loop.finish()
    if validate:
        schema.validate_stream(lines)
    return loop, sim, lines, result


def write_stream(lines, path):
    with open(path, "w") as f:
        for o in lines:
            f.write(json.dumps(o, separators=(",", ":")) + "\n")
