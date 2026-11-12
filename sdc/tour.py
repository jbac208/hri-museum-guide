"""Multi-stop tour (blocks 3-5 over a whole tour): stops, between-stop planning, transitions.

One signal layer and one profile store live for the whole tour, so baselines (with the start
impression's seed fading out by stop index SEED_FADE_STOPS), steering credit and profile layers
carry from stop to stop. Each stop gets its own StopController.

Between stops (Perception & decision loop §6):
  1. the stop ends; rescinded layers are removed; plan_next_stop() picks pace, depth, next stop (D1)
  2. P12: if the top two options are close, the robot offers the group a two-way choice and reads
     orientation and gaze for CHOICE_WAIT_S (weighted by w_i, D8); no vote, no direct question
  3. move on: say where to, step_to the next stop at ROBOT_WALK_MPS (ROBOT_WALK_SLOW_MPS if pace is
     slower or someone falls behind -> slow_down(), §4); the signal layer only judges falling behind
  4. wait at the next stop until everyone is within ARRIVE_RADIUS_M (at most WAIT_MAX_S), then start
Privacy: end_tour() discards all per-visitor state; records() must be taken before that.
"""
import math

from . import config as C, content
from .adapter import Frame, StartImpression, Utterance
from .decision import Action, ACTION_KINDS, StopController, plan_next_stop
from . import metrics
from .metrics import EventLog
from .policies import OURS
from .profile import ProfileStore
from .signals import SignalLayer


class Tour:
    def __init__(self, gallery, first_stop, stop_durations, contents=None, scenario="?", policy=OURS):
        self.policy = policy
        self.gallery = gallery
        self.ex = {e["id"]: e for e in gallery["exhibits"]}
        self.names = {e["id"]: e["name"] for e in gallery["exhibits"]}
        self.contents = contents or content.load_all(gallery)
        self.durations = list(stop_durations)
        self.signals = SignalLayer(gallery, first_stop, 0)
        self.profile = ProfileStore(lam=policy.lam)
        self.log = EventLog(scenario, first_stop, gallery["id"], None)
        self.used = set()
        self.visited = [first_stop]
        self.k = 0
        self.mode = "stop"
        self.t = 0.0
        self.tour_log = []
        self._actions = []
        self._ctrl_seen = 0
        self.plans = []
        self.fell_behind = False
        self.frame = None
        self._seen = set()
        self.ctrl = self._new_ctrl(first_stop, 0.0, None, "same")
        self.controllers = [self.ctrl]

    # ------------------------------------------------------------ interface shared with Loop
    @property
    def actions(self):
        return self._actions

    def decision_log(self):
        return [e for c in self.controllers for e in c.log] + self.tour_log

    def records(self):
        return self.log.records(self)

    # ------------------------------------------------------------ helpers
    def _new_ctrl(self, stop, t, pose, depth):
        c = StopController(stop, self.contents[stop], self.gallery, self.profile, t, self.durations[self.k],
                           self.used, robot_pose=pose, stop_index=self.k, depth=depth, policy=self.policy)
        c.dwell_of = lambda tid: (self.signals.v[tid].dwell.value if tid in self.signals.v else None)
        self._ctrl_seen = 0
        return c

    def _act(self, t, kind, args, reason, duration_s=0.0):
        assert kind in ACTION_KINDS
        a = Action(round(t, 2), kind, args, reason, duration_s)
        self._actions.append(a)
        self.tour_log.append({"type": "action", **a.as_dict()})
        return a

    def _note(self, t, what, **kw):
        self.tour_log.append({"type": "note", "t": round(t, 2), "note": what, **kw})

    def _sync(self):
        new = self.ctrl.actions[self._ctrl_seen:]
        self._ctrl_seen = len(self.ctrl.actions)
        self._actions.extend(new)

    def _dispatch(self, events):
        for ev in events:
            started = id(ev) not in self._seen
            self._seen.add(id(ev))
            if started:
                self.log.on_event_start(ev, self.profile.on_event(ev, self.ctrl.stop if self.mode == "stop" else None)
                                        if self.mode == "stop" else [])
            if self.mode == "stop":
                self.ctrl.on_event(ev, started)
            elif ev.kind == "barrier" and ev.detail == "behind":
                self._on_behind(ev, started)

    # ------------------------------------------------------------ main
    def step(self, rec):
        if isinstance(rec, StartImpression):
            self.profile.load_start_impression(rec)
        self._dispatch(self.signals.step(rec))
        if isinstance(rec, Frame):
            self.t, self.frame = rec.t, rec
            self.log.on_frame(rec)
            if self.mode == "stop":
                self.ctrl.update(rec)
                self._sync()
                if self.ctrl.done:
                    self._between(rec.t)
            elif self.mode == "choice":
                self._read_choice(rec)
            elif self.mode == "transition":
                self._transition(rec)
        elif isinstance(rec, Utterance) and self.mode == "stop":
            self.ctrl.on_utterance(rec)
        self._sync()

    def finish(self):
        if self.mode == "stop" and not self.ctrl.done:
            self.ctrl.end_stop(self.t)
            self._sync()
            self.profile.end_stop(self.t)
        self._dispatch(self.signals.finish())
        self._sync()
        if self.mode != "done":
            self._note(self.t, "tour end (stream ended)", stops=self.visited)
        return {"stops": self.visited, "plans": self.plans}

    def run(self, records):
        for r in records:
            self.step(r)
        return self.finish()

    # ------------------------------------------------------------ between stops
    def _between(self, t):
        summary = dict(self.ctrl.summary, fell_behind=self.fell_behind)
        self.profile.end_stop(t)
        plan = plan_next_stop(self.ctrl.stop, self.gallery, self.profile, self.visited, summary, self.policy)
        plan["t"] = round(t, 2)
        plan["after"] = self.ctrl.stop
        self.plans.append(plan)
        self.fell_behind = False
        if plan["next"] is None or self.k + 1 >= len(self.durations):
            self.mode = "done"
            self._note(t, "tour close (owner still open: HANDOFF §8)", stops=self.visited)
            return
        self.plan = plan
        if plan["offer_choice"]:
            a, b = plan["choice"]
            say = self._act(t, "say_to_group", {"text": f"Next we could see the {self.names[a].lower()} "
                                                        f"or the {self.names[b].lower()}.", "id": "between.choice"},
                            "between stops: two close options, offer the group a two-way choice; read movement, "
                            "no vote (P12)", len(f"Next we could see the {a} or the {b}.".split()) / C.TTS_WORDS_PER_S)
            self.choice = {"options": [a, b], "until": t + say.duration_s + C.CHOICE_WAIT_S, "from": t + say.duration_s,
                           "score": {a: 0.0, b: 0.0}}
            self.mode = "choice"
        else:
            self._start_transition(t, plan["next"], plan)

    def _read_choice(self, f):
        ch = self.choice
        if f.t >= ch["from"]:
            for tid, o in f.visitors.items():
                w = self.profile.weight(tid)
                for opt in ch["options"]:
                    e = self.ex[opt]
                    looks = o.attention == f"exhibit:{opt}" or o.attention.startswith(f"feature:{opt}.")
                    bearing = math.atan2(e["y"] - o.y, e["x"] - o.x)
                    facing = abs((o.body_yaw - bearing + math.pi) % (2 * math.pi) - math.pi) <= C.CHOICE_FACING_RAD
                    if looks or facing:
                        ch["score"][opt] += w / 10.0   # weighted seconds
        if f.t >= ch["until"]:
            a, b = ch["options"]
            sa, sb = ch["score"][a], ch["score"][b]
            pick = a if sa >= sb else b
            self._note(f.t, "two-way choice read", scores={k: round(v, 2) for k, v in ch["score"].items()},
                       pick=pick, why=f"weighted seconds facing or looking at each option over CHOICE_WAIT_S="
                                       f"{C.CHOICE_WAIT_S}s (w_i from D8)")
            self.plan["next"] = pick
            self.plan["reasons"].append(f"group turned toward {pick} (weighted seconds {ch['score'][a]:.1f} vs "
                                        f"{ch['score'][b]:.1f}): next {pick} (P12)")
            self._start_transition(f.t, pick, self.plan)

    def _start_transition(self, t, nxt, plan):
        pose = self.ctrl.pose
        e = self.ex[nxt]
        tx, ty = e["x"] + C.ROBOT_STOP_OFFSET[0], e["y"] + C.ROBOT_STOP_OFFSET[1]
        slow = plan["pace"] == "slower"
        speed = C.ROBOT_WALK_SLOW_MPS if slow else C.ROBOT_WALK_MPS
        if slow:
            self._act(t, "slow_down", {}, "pace slower for this move: " + plan["reasons"][0])
        text = f"Let's go and see the {self.names[nxt].lower()}."
        say = self._act(t, "say_to_group", {"text": text, "id": "between.move"}, "between stops: move on, said to the group",
                        len(text.split()) / C.TTS_WORDS_PER_S)
        t0 = t + say.duration_s
        dist = math.hypot(tx - pose[0], ty - pose[1])
        self.move = {"t0": t0, "from": (pose[0], pose[1]), "to": (tx, ty), "speed": speed, "next": nxt, "slow": slow,
                     "arrived": False, "arrive_t": None, "plan": plan}
        yaw = round(math.atan2(ty - pose[1], tx - pose[0]), 3)
        self._act(t0, "turn_body", {"yaw": yaw}, "move on: face the way to the next stop")
        self._act(t0, "step_to", {"x": round(tx, 2), "y": round(ty, 2), "to": nxt, "speed": speed},
                  f"move on to {nxt} at {speed} m/s, the pace of the slowest visitor (§6.5)", dist / speed)
        self.pose = [tx, ty, yaw]
        self._dispatch(self.signals.set_transition(t, nxt))
        self._note(t, "transition start", to=nxt, distance_m=round(dist, 1), speed=speed)
        self.mode = "transition"

    def _on_behind(self, ev, started):
        if started:
            self.fell_behind = True
            self._note(ev.t_detect, "falling behind", track_id=ev.track_id, why=ev.reason)
            m = self.move
            if self.policy.floor_on_moves and not m["slow"] and not m["arrived"]:
                m["slow"] = True
                # re-plan the rest of the walk at the slower speed
                a = next(x for x in reversed(self._actions) if x.kind == "step_to")
                done = max(0.0, ev.t_detect - m["t0"]) * m["speed"]
                total = math.hypot(m["to"][0] - m["from"][0], m["to"][1] - m["from"][1])
                left = max(0.0, total - done)
                a.duration_s = round(max(0.0, ev.t_detect - a.t), 2)
                self._act(ev.t_detect, "slow_down", {}, "someone is falling behind: slow down (floor, §4)")
                fx = m["from"][0] + (m["to"][0] - m["from"][0]) * (done / total if total else 1)
                fy = m["from"][1] + (m["to"][1] - m["from"][1]) * (done / total if total else 1)
                m.update(t0=ev.t_detect, **{"from": (fx, fy)}, speed=C.ROBOT_WALK_SLOW_MPS)
                self._act(ev.t_detect, "step_to", {"x": round(m["to"][0], 2), "y": round(m["to"][1], 2),
                                                   "to": m["next"], "speed": C.ROBOT_WALK_SLOW_MPS},
                          "continue at the slower pace", left / C.ROBOT_WALK_SLOW_MPS)
        else:
            self._note(ev.t1, "caught up", track_id=ev.track_id)

    def _transition(self, f):
        m = self.move
        if not m["arrived"]:
            total = math.hypot(m["to"][0] - m["from"][0], m["to"][1] - m["from"][1])
            if f.t >= m["t0"] + total / m["speed"]:
                m["arrived"], m["arrive_t"] = True, f.t
                self._note(f.t, "robot at next stop: wait until everyone has arrived (§4, §6.5)", stop=m["next"])
            return
        e = self.ex[m["next"]]
        far = [tid for tid, o in f.visitors.items() if math.hypot(o.x - e["x"], o.y - e["y"]) > C.ARRIVE_RADIUS_M]
        waited = f.t - m["arrive_t"]
        if far and waited < C.WAIT_MAX_S and self.policy.floor_on_moves:
            return
        if waited > 0.5:
            self._act(m["arrive_t"], "pause", {"s": round(waited, 1)},
                      "waited at the next stop until everyone arrived before starting (§4)", round(waited, 1))
        if far:
            self._note(f.t, "started without everyone (WAIT_MAX_S)", missing=far, stop=m["next"],
                       why=(f"waited WAIT_MAX_S={C.WAIT_MAX_S}s; late arrivals are left to the exclusion handler (Q17)"
                            if self.policy.floor_on_moves else f"{self.policy.name} baseline doesn't wait for everyone"))
        self.k += 1
        nxt = m["next"]
        self.visited.append(nxt)
        self._dispatch(self.signals.set_stop(nxt, self.k, f.t))
        self.mode = "stop"
        self.ctrl = self._new_ctrl(nxt, f.t, self.pose, m["plan"]["depth"])
        self.controllers.append(self.ctrl)
        self.ctrl.update(f)
        self._sync()

    def end_tour(self):
        """Privacy (Q13): return the log to keep, with visitor speech stripped, then discard all
        per-visitor state (profile layers, credit, baselines) and scrub speech from live events."""
        kept = metrics.redact_speech(self.records())
        for ev in self.signals.events:
            ev.reason = metrics.redact_speech(ev.reason)
        self.signals.v.clear()
        self.profile.end_tour(self.t)
        self.ended = True
        return kept
