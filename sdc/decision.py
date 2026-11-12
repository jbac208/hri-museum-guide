"""Decision layer (block 5): turns signal events + profile layers + content into robot actions.

Within a stop (Perception & decision loop §3), the stop controller runs
    arrange -> core -> open space -> respond (sense / respond / check, while time remains) -> done
with these always-on parts:
  exclusion handler  top priority, from t=0. Fix by barrier type (§4): position -> soft glance + turn to
                     open the formation, then step back once if still excluded; talked over -> stop
                     speaking, hold the floor open, gaze to them; falling behind -> slow down and wait.
                     Never a name, never a direct question.
  question answering every question gets a canned answer, said to the group (D7), after a nonverbal
                     acknowledgement, at the end of the sentence being said (a pause ends at once); the
                     rest resumes after. Late questions are answered even if the stop overruns. Answers
                     don't count toward P11. The asker's steering credit goes up (Q11, Q10).
  gaze balancing     gaze moves to the least-looked-at visitor every GAZE_SHIFT_S (D5); core cue words
                     send gaze to the exhibit or feature instead.
In the respond phase:
  addition selector  score(a) = Σ_i w_i · s_i(a), w_i = 1/(1+λ k_i) (D8); s_i(a) = summed strength of
                     i's layers that a serves, capped at 1. Deliver the best unused addition if it
                     reaches ADDITION_THRESHOLD; at most MAX_ADDITIONS_PER_STOP (P11); never repeat one.
                     Facing the companion cluster of the visitor it serves most (§5).
  uptake monitor     for UPTAKE_WINDOW_S after the addition: look at its target, step closer, or ask
                     -> confirm the pending layers it tested; nothing -> rescind them (D6).
  steering credit    k_i += 1 whenever the robot visibly acts on i's signal: answering their question, or
                     delivering an addition driven by their layer (taken up or not) (loop doc §1, D3, D8).
Reserved visitors produce no events, so they get nothing beyond gaze balancing (D2).

Between stops, plan_next_stop() picks pace, depth and the next stop (§6, D1).

Output: Action(t, kind, args, reason). Kinds: say_to_group, gaze_at, turn_body, step_to, pause, slow_down.
"""
import math
from dataclasses import dataclass

from . import config as C
from .content import speech_s

ACTION_KINDS = {"say_to_group", "gaze_at", "turn_body", "step_to", "pause", "slow_down"}


@dataclass
class Action:
    t: float
    kind: str
    args: dict
    reason: str
    duration_s: float = 0.0

    def as_dict(self):
        return {"t": round(self.t, 2), "kind": self.kind, "args": self.args,
                "duration_s": round(self.duration_s, 2), "reason": self.reason}


def _yaw(ax, ay, bx, by):
    return round(math.atan2(by - ay, bx - ax), 3)


def _centroid(obs):
    return sum(o.x for o in obs) / len(obs), sum(o.y for o in obs) / len(obs)


# ---------------------------------------------------------------- addition selector (§5)

def score_addition(a, profile):
    """Returns (score, {track_id: (w_i, s_i, [layers])}) for visitors with s_i(a) > 0."""
    per = {}
    for tid, v in profile.visitors.items():
        layers = [l for l in v.layers.values() if l.strength > 0 and a.serves_layer(l.kind, l.target)]
        if layers:
            per[tid] = (profile.weight(tid), min(1.0, sum(l.strength for l in layers)), layers)
    return sum(w * s for w, s, _ in per.values()), per


def select_addition(exhibit, profile, used):
    """Best unused addition at or above threshold, or None. Ties keep the content file's order."""
    best = None
    for a in exhibit.additions:
        if a.id in used:
            continue
        score, per = score_addition(a, profile)
        if score >= C.ADDITION_THRESHOLD and (best is None or score > best[1] + 1e-9):
            best = (a, score, per)
    return best


# ---------------------------------------------------------------- uptake monitor (D6)

class UptakeWindow:
    """Uptake = a look at the addition's target (a feature, or another exhibit; not the current stop as a
    whole) clearly longer than the visitor's own usual dwell, stepping closer to its exhibit, or asking
    a question, within the window (D6)."""

    def __init__(self, addition, t0, t_end, per, gallery, frame, stop, dwell_of=None):
        self.a, self.t0, self.t_end, self.per = addition, t0, t_end, per
        ex = {e["id"]: e for e in gallery["exhibits"]}
        neighbour = [s["target"] for s in addition.serves if s["kind"] == "exhibit_interest"]
        eid = neighbour[0] if addition.type == "neighbour" and neighbour else addition.exhibit
        self.ex_xy = (ex[eid]["x"], ex[eid]["y"])
        # looking at the current stop as a whole is what everyone does anyway, so it isn't uptake
        self.targets = {addition.look} - {f"exhibit:{stop}"}
        for s in addition.serves:
            if s["kind"] == "feature_interest":
                self.targets.add(f"feature:{s['target']}")
            elif s["target"] != stop:          # another exhibit: looking anywhere at it counts
                self.targets.add(f"exhibit:{s['target']}")
                self.targets |= {f"feature:{f['id']}" for f in ex[s["target"]]["features"]}
        dwell_of = dwell_of or (lambda tid: None)
        self.need = {tid: max(C.UPTAKE_LOOK_S, C.UPTAKE_DWELL_FACTOR * (dwell_of(tid) or 0.0)) for tid in per}
        self.run0, self.last_in, self.best = {}, {}, {tid: 0.0 for tid in per}
        # stepping closer is measured from where they stand once any move already under way has settled
        self.d_ref, self.settled, self.trail = {}, set(), {tid: [] for tid in per}
        self.closer, self.asked = set(), set()

    def _dist(self, o):
        return math.hypot(o.x - self.ex_xy[0], o.y - self.ex_xy[1])

    def on_frame(self, f):
        live = f.t >= self.t0     # the movement trail starts when the addition is chosen, evidence when it's said
        for tid in self.per:
            o = f.visitors.get(tid)
            if o is None:
                continue
            if live and o.attention in self.targets:
                if tid not in self.run0 or f.t - self.last_in[tid] > C.UPTAKE_LOOK_GAP_S:
                    self.run0[tid] = f.t
                self.last_in[tid] = f.t
                self.best[tid] = max(self.best[tid], f.t - self.run0[tid])
            d = self._dist(o)
            tr = self.trail[tid]
            tr.append((f.t, d))
            while tr and tr[0][0] < f.t - 2.0:
                tr.pop(0)
            span = tr[-1][0] - tr[0][0]
            if tid not in self.settled:
                self.d_ref[tid] = d
                if span >= 1.9:   # radial speed from the means of the first and last thirds of the last 2 s
                    k = max(1, len(tr) // 3)
                    v = (sum(x[1] for x in tr[:k]) - sum(x[1] for x in tr[-k:])) / k / (span * 2 / 3)
                    if v <= C.UPTAKE_SETTLE_SPEED_MPS:
                        self.settled.add(tid)
            elif live and self.d_ref[tid] - d >= C.UPTAKE_STEP_M:
                self.closer.add(tid)

    def on_utterance(self, u):
        if u.track_id in self.per and self.t0 <= u.t <= self.t_end:
            self.asked.add(u.track_id)

    def evidence(self, tid):
        why = []
        if self.best.get(tid, 0) >= self.need[tid]:
            why.append(f"looked at it {self.best[tid]:.1f}s in one go (≥ max(UPTAKE_LOOK_S, "
                       f"UPTAKE_DWELL_FACTOR×own dwell) = {self.need[tid]:.1f}s)")
        if tid in self.closer:
            why.append(f"stepped ≥ UPTAKE_STEP_M={C.UPTAKE_STEP_M} m closer")
        if tid in self.asked:
            why.append("asked a question")
        return "; ".join(why)


# ---------------------------------------------------------------- stop controller

class StopController:
    def __init__(self, stop, exhibit, gallery, profile, t_start, duration_s, used_additions=None,
                 robot_pose=None, stop_index=0, depth="same"):
        self.stop, self.ex, self.gallery, self.profile = stop, exhibit, gallery, profile
        e = next(x for x in gallery["exhibits"] if x["id"] == stop)
        self.stop_xy = (e["x"], e["y"])
        self.t_start, self.t_end = t_start, t_start + duration_s
        self.used = used_additions if used_additions is not None else set()
        self.pose = list(robot_pose) if robot_pose else None     # [x, y, yaw], commanded
        self.log = []          # actions and notes, in time order
        self.actions = []
        self.phase, self.core_i, self.open_step = "arrange", 0, 0
        self.arranged = False
        self.busy_until = t_start
        self.speech = None     # (Action, text) currently being said
        self.scheduled = []    # [(t, kind, args, reason, owner Action)]
        self.answers, self.resume_text = [], None
        self.additions_done, self.uptake = 0, None
        self.episodes, self.resolved = {}, []
        self.gaze = None       # (target, since)
        self.gaze_time, self.last_gaze_t = {}, -1e9
        self.repositions = 0
        self.frame = None
        self.steering_signals, self.fatigued = [], set()
        self.done = False
        self.dwell_of = None   # tid -> own mean dwell (s), set by the loop from the signal layer
        self.stop_index, self.depth = stop_index, depth
        self.core = list(exhibit.core)
        self._note(t_start, "stop start", stop=stop, stop_index=stop_index, duration_s=duration_s, depth=depth)

    # ------------------------------------------------------------ output
    def _act(self, t, kind, args, reason, duration_s=0.0):
        assert kind in ACTION_KINDS, kind
        a = Action(round(t, 2), kind, args, reason, duration_s)
        self.actions.append(a)
        self.log.append({"type": "action", **a.as_dict()})
        if kind == "gaze_at":
            self._track_gaze(t, args["target"])
        return a

    def _note(self, t, what, **kw):
        self.log.append({"type": "note", "t": round(t, 2), "note": what, **kw})

    def _track_gaze(self, t, target):
        if self.gaze and self.gaze[0].startswith("visitor:"):
            tid = self.gaze[0][8:]
            self.gaze_time[tid] = self.gaze_time.get(tid, 0.0) + (t - self.gaze[1])
        self.gaze, self.last_gaze_t = (target, t), t

    def _say(self, t, text, reason, looks=(), what=None):
        dur = speech_s(text)
        a = self._act(t, "say_to_group", {"text": text, "id": what}, reason, dur)
        self.speech = (a, text)
        self.busy_until = t + dur
        for offset, look, why in looks:
            self.scheduled.append((t + offset, "gaze_at", {"target": look}, why, a))
        return a

    def _fits(self, t, dur):
        return t + dur <= self.t_end - C.STOP_END_MARGIN_S

    # ------------------------------------------------------------ inputs
    def on_event(self, ev, started):
        if self.done:
            return
        t = ev.t_detect if started else ev.t1
        if ev.kind == "excluded":
            if started:
                self._note(t, "exclusion episode start", track_id=ev.track_id, barriers=ev.detail, why=ev.reason)
                self.episodes[ev.track_id] = {"t0": ev.t_detect, "fixed": set(), "turned_t": None}
                for b in ev.detail.split(","):
                    self._fix(t, ev.track_id, b)
            else:
                ep = self.episodes.pop(ev.track_id, None)
                if ep:
                    self.resolved.append({"track_id": ev.track_id, "t0": ep["t0"], "t1": ev.t1,
                                          "time_to_resolve_s": round(ev.t1 - ep["t0"], 2)})
                    self._note(ev.t1, "exclusion episode resolved", track_id=ev.track_id,
                               time_to_resolve_s=round(ev.t1 - ep["t0"], 2))
        elif ev.kind == "barrier" and started and ev.track_id in self.episodes:
            self._fix(t, ev.track_id, ev.detail)
        elif started and ev.kind in ("linger", "approach", "drift", "point_ask"):
            self.steering_signals.append(ev)
        if started and ev.kind == "fatigue":
            self.fatigued.add(ev.track_id)

    def on_utterance(self, u):
        if self.uptake:
            self.uptake.on_utterance(u)
        if u.is_question and not self.done:
            self.answers.append(u)
            self._make_room_for_answer(u.t)

    def _make_room_for_answer(self, t):
        """Q11: answer at the end of the sentence being said (the rest resumes after the answer);
        a pause (wait time, holding the floor) ends at once."""
        if self.speech and t < self.speech[0].t + self.speech[0].duration_s:
            a, text = self.speech
            words = text.split()
            k = int((t - a.t) * C.TTS_WORDS_PER_S)
            ends = [i for i, w in enumerate(words) if w.endswith((".", "?", "!")) and i >= k]
            if not ends or ends[0] >= len(words) - 1:
                return                                   # already in the last sentence: answer when it ends
            cut = a.t + (ends[0] + 1) / C.TTS_WORDS_PER_S
            a.duration_s = round(cut - a.t, 2)
            a.args["cut_at"] = round(cut, 2)
            a.args["cut_for"] = "question"
            self._sync_log(a)
            self.scheduled = [x for x in self.scheduled if x[4] is not a or x[0] < cut]
            if not self.resume_text:
                self.resume_text = (" ".join(words[ends[0] + 1:]), a.args.get("id"))
            self.busy_until = cut
        elif t < self.busy_until:
            p = next((x for x in reversed(self.actions) if x.kind == "pause" and x.t + x.duration_s > t), None)
            if p is not None:
                p.duration_s = round(max(0.0, t - p.t), 2)
                p.args["ended_for"] = "question"
                self._sync_log(p)
            self.busy_until = t

    def _sync_log(self, a):
        for entry in self.log:
            if entry.get("type") == "action" and entry["t"] == a.t and entry["kind"] == a.kind:
                entry.update(a.as_dict())

    # ------------------------------------------------------------ exclusion handler (§4)
    def _fix(self, t, tid, barrier):
        ep = self.episodes[tid]
        if barrier == "position" and "position" not in ep["fixed"]:
            ep["fixed"].add("position")
            ep["turned_t"] = t
            self._act(t, "gaze_at", {"target": f"visitor:{tid}"},
                      "excluded (bid + position barrier): soft glance toward them, no direct question (D2, §4)")
            o = self.frame.visitors.get(tid) if self.frame else None
            if o is not None and self.pose:
                yaw = _yaw(self.pose[0], self.pose[1], o.x, o.y)
                self.pose[2] = yaw
                self._act(t, "turn_body", {"yaw": yaw},
                          "excluded (position barrier): turn to open the formation toward them (Kuzuoka 2010, §4)")
        elif barrier == "talked_over":
            self._cut_speech(t)
            self._act(t, "pause", {"s": C.PAUSE_FLOOR_S},
                      "excluded (talked over): stop and hold the floor open (Mutlu 2009, §4)", C.PAUSE_FLOOR_S)
            self._act(t, "gaze_at", {"target": f"visitor:{tid}"},
                      "excluded (talked over): gaze to them to hand them the floor (Gillet 2021, §4)")
            self.busy_until = max(self.busy_until, t + C.PAUSE_FLOOR_S)
        elif barrier == "behind" and "behind" not in ep["fixed"]:
            ep["fixed"].add("behind")
            self._act(t, "slow_down", {}, "excluded (falling behind): slow down and wait (§4)")

    def _exclusion_followups(self, t):
        for tid, ep in self.episodes.items():
            o = self.frame.visitors.get(tid) if self.frame else None
            looks_clear = o is not None and o.in_formation and o.los_exhibit   # barrier may be clearing right now
            if (ep["turned_t"] is not None and "step" not in ep["fixed"] and not looks_clear
                    and t - ep["turned_t"] >= C.EXCLUSION_RECHECK_S
                    and self.repositions < C.MAX_REPOSITIONS_PER_STOP and self.pose):
                ep["fixed"].add("step")
                self.repositions += 1
                dx, dy = self.pose[0] - self.stop_xy[0], self.pose[1] - self.stop_xy[1]
                n = math.hypot(dx, dy) or 1.0
                self.pose[0] += C.STEP_BACK_M * dx / n
                self.pose[1] += C.STEP_BACK_M * dy / n
                self._act(t, "step_to", {"x": round(self.pose[0], 2), "y": round(self.pose[1], 2)},
                          f"still excluded {C.EXCLUSION_RECHECK_S:.0f}s after turning: step back "
                          f"{C.STEP_BACK_M} m to widen the formation (once per stop, §3.1)")

    def _cut_speech(self, t):
        if self.speech and t < self.busy_until:
            a, text = self.speech
            words = text.split()
            k = int((t - a.t) * C.TTS_WORDS_PER_S)
            a.duration_s = round(t - a.t, 2)
            a.args["cut_at"] = round(t, 2)
            self._sync_log(a)
            self.scheduled = [s for s in self.scheduled if s[4] is not a]
            # resume from the start of the sentence that was cut
            starts = [0] + [i + 1 for i, w in enumerate(words[:-1]) if w.endswith((".", "?", "!"))]
            s0 = max(i for i in starts if i <= k)
            if k < len(words):
                self.resume_text = (" ".join(words[s0:]), a.args.get("id"))
            self.speech = None
            self.busy_until = t

    # ------------------------------------------------------------ main update (every frame)
    def update(self, f):
        t = f.t
        self.frame = f
        if self.uptake:
            self.uptake.on_frame(f)
            if t >= self.uptake.t_end:
                self._close_uptake(t)
        for s in [s for s in self.scheduled if s[0] <= t]:
            self.scheduled.remove(s)
            if not self.done:
                self._act(s[0], s[1], s[2], s[3])
        if self.done:
            return
        if not self.arranged:
            self._arrange(t)
        if t >= self.t_end and t >= self.busy_until:
            if self.answers:                                   # Q11: a late question is still answered
                self._note(t, "overrun: answering a late question before moving on (Q11)")
                self._answer(t, self.answers.pop(0))
                return
            self.end_stop(t)
            return
        self._exclusion_followups(t)
        if t >= self.busy_until:
            self._next(t)
        self._gaze_balance(t)

    def _arrange(self, t):
        self.arranged = True
        if self.pose is None:
            self.pose = [self.frame.robot.x, self.frame.robot.y, self.frame.robot.yaw]
        vs = list(self.frame.visitors.values())
        if vs:
            cx, cy = _centroid(vs)
            self.pose[2] = _yaw(self.pose[0], self.pose[1], cx, cy)
            self._act(t, "turn_body", {"yaw": self.pose[2]},
                      "arrange: face the group so everyone can see and hear (§3.1)")
        self._act(t, "gaze_at", {"target": f"exhibit:{self.stop}"}, "arrange: rest gaze on the exhibit (Chen 2025)")

    def _next(self, t):
        if self.answers:
            return self._answer(t, self.answers.pop(0))
        if self.resume_text:
            text, what = self.resume_text
            self.resume_text = None
            a = self._say(t, text, "resume what was cut (after an answer or after handing the floor), from a sentence start", what=what)
            a.args["resume"] = True
            return a
        if self.phase == "arrange":
            if t < self.t_start + C.ARRANGE_S:
                return
            self.phase = "core"
        if self.phase == "core":
            if self.core_i == len(self.core) and self.depth == "raised" and not getattr(self, "_deep_done", False):
                self._deep_done = True
                deep = next((a for a in self.ex.additions if a.type == "depth" and a.id not in self.used), None)
                if deep and self._fits(t, deep.duration_s):
                    self.used.add(deep.id)
                    self._say(t, deep.text, "core: default depth raised for this stop (§6.3), same for everyone",
                              [(0.5, deep.look, "depth: look at its target")], deep.id)
                    self.busy_until += C.SEGMENT_GAP_S
                    return
            if self.core_i < len(self.core):
                seg = self.core[self.core_i]
                self.core_i += 1
                if self._fits(t, seg.duration_s):
                    looks = [(dt, c["look"], f"cue word '{c['word']}' (Yamazaki 2009)") for dt, c in seg.cue_times()]
                    self._say(t, seg.text, f"core {self.core_i}/{len(self.core)}: same for everyone", looks, seg.id)
                    self.busy_until += C.SEGMENT_GAP_S
                return
            self.phase = "open"
        if self.phase == "open":
            q = self.ex.open_question
            if self.open_step == 0:
                self.open_step = 1
                self._act(t, "pause", {"s": C.OPEN_WAIT_S}, "open space: wait time before the question (D2)",
                          C.OPEN_WAIT_S)
                self.busy_until = t + C.OPEN_WAIT_S
                return
            if self.open_step == 1:
                self.open_step = 2
                self._say(t, q["text"], "open space: one open question to the whole group (D2)",
                          [(0.3, q["look"], "open question: look at what it asks about")], f"{self.stop}.open")
                return
            if self.open_step == 2:
                self.open_step = 3
                self._act(t, "pause", {"s": q["wait_s"]}, "open space: wait time for answers (D2)", q["wait_s"])
                self.busy_until = t + q["wait_s"]
                return
            self.phase = "respond"
            self._note(t, "phase respond")
        if self.phase == "respond" and self.uptake is None and self.additions_done < C.MAX_ADDITIONS_PER_STOP:
            self._try_addition(t)

    def _answer(self, t, u):
        qa = self.ex.answer(u.text)
        self._act(t, "gaze_at", {"target": f"visitor:{u.track_id}"},
                  "acknowledge a question nonverbally before answering (D7)")
        self._say(t + C.ACK_GAZE_S, qa["text"], f"answer ({qa['id']}), said to the group (D7)",
                  [(0.5, qa["look"], "answer: look at what it is about")], qa["id"])
        self.profile.add_credit(u.track_id, t, f"question answered ({qa['id']})", C.CREDIT_PER_ACTED_SIGNAL)
        self._note(t, "question answered", track_id=u.track_id, qa=qa["id"], asked_t=round(u.t, 2),
                   wait_s=round(t + C.ACK_GAZE_S - u.t, 2))

    def _try_addition(self, t):
        best = select_addition(self.ex, self.profile, self.used)
        if best is None:
            return
        a, score, per = best
        dur = C.ACK_GAZE_S + a.duration_s
        if not self._fits(t, dur):
            return
        top = max(per, key=lambda tid: per[tid][0] * per[tid][1])
        terms = " + ".join(f"{w:.2f}·{s:.2f} ({tid})" for tid, (w, s, _) in sorted(per.items()))
        reason = f"addition {a.id}: score {score:.2f} = {terms} ≥ ADDITION_THRESHOLD={C.ADDITION_THRESHOLD}"
        self._act(t, "gaze_at", {"target": f"visitor:{top}"},
                  "acknowledge nonverbally before an addition (D7)")
        cl = self.profile.visitors[top].cluster_id
        members = [self.frame.visitors[m] for m in self.profile.cluster(cl) if m in self.frame.visitors]
        if members and self.pose:
            cx, cy = _centroid(members)
            self.pose[2] = _yaw(self.pose[0], self.pose[1], cx, cy)
            self._act(t, "turn_body", {"yaw": self.pose[2]},
                      f"deliver facing the whole companion cluster {cl} (§5, vom Lehn 2001)")
        say = self._say(t + C.ACK_GAZE_S, a.text, reason, [(0.5, a.look, "addition: look at its target")], a.id)
        self.used.add(a.id)
        self.additions_done += 1
        for tid in sorted(per):
            self.profile.add_credit(tid, say.t, f"signal acted on: addition {a.id} delivered", C.CREDIT_PER_ACTED_SIGNAL)
        self._note(say.t, "addition", addition=a.id, score=round(score, 3),
                   addressed={tid: [l.id for l in layers] for tid, (_, _, layers) in per.items()})
        self.uptake = UptakeWindow(a, say.t, say.t + a.duration_s + C.UPTAKE_WINDOW_S, per, self.gallery, self.frame,
                                   self.stop, self.dwell_of)

    def _close_uptake(self, t, complete=True):
        w, self.uptake = self.uptake, None
        for tid, (_, _, layers) in w.per.items():
            pending = [l for l in layers if l.status == "pending"]
            why = w.evidence(tid)
            if why:
                for l in pending:
                    self.profile.confirm(l.id, t, f"uptake after {w.a.id}: {why}")
                self._note(t, "uptake", track_id=tid, addition=w.a.id, why=why,
                           confirmed=[l.id for l in pending])
            elif complete:
                for l in pending:
                    self.profile.rescind(l.id, t, f"no uptake within UPTAKE_WINDOW_S after {w.a.id} (D6)")
                self._note(t, "no uptake", track_id=tid, addition=w.a.id, rescinded=[l.id for l in pending])
            else:
                self._note(t, "uptake window cut by stop end: layers stay pending", track_id=tid, addition=w.a.id)

    def _gaze_balance(self, t):
        if t - self.last_gaze_t < C.GAZE_SHIFT_S or any(s[0] - t < 1.0 for s in self.scheduled):
            return
        current = self.gaze[0] if self.gaze else None
        cands = [tid for tid in self.frame.visitors if f"visitor:{tid}" != current]
        if not cands:
            return
        tid = min(cands, key=lambda v: (self.gaze_time.get(v, 0.0), self.profile.credit(v), v))
        self._act(t, "gaze_at", {"target": f"visitor:{tid}"},
                  "gaze balancing: least looked-at visitor so far (D5, Gillet 2021)")

    # ------------------------------------------------------------ stop end
    def end_stop(self, t):
        if self.done:
            return self.summary
        if self.uptake:
            self._close_uptake(t, complete=t >= self.uptake.t_end)
        self.done = True
        for tid, ep in self.episodes.items():
            self._note(t, "P13 misery: exclusion episode unresolved at stop end", track_id=tid)
        self.summary = {
            "stop": self.stop, "t_end": round(t, 2),
            "additions": [a.args["id"] for a in self.actions if a.kind == "say_to_group" and not a.args.get("resume")
                          and str(a.args.get("id", "")).startswith(f"{self.stop}.add.")],
            "exclusion_resolved": self.resolved,
            "exclusion_unresolved": sorted(self.episodes),
            "fatigued": sorted(self.fatigued),
            "steering_signals": len(self.steering_signals),
        }
        self._note(t, "stop end", **{k: v for k, v in self.summary.items() if k != "stop"})
        return self.summary


# ---------------------------------------------------------------- between stops (§6)

def _serves_exhibit(layer, eid):
    if layer.kind == "feature_interest":
        return layer.target.startswith(eid + ".")
    return layer.target == eid


def plan_next_stop(stop, gallery, profile, visited, summary):
    """Pace, depth and next stop. Next stop: the route option with the best weighted score over
    confirmed layers (same weights as §5). There is no per-option exclusion filter (Joey, 2026-11-12:
    not core to the concept); D1's floor is kept within stops by the exclusion handler (P13).
    Returns a dict with reasons."""
    reasons = []
    n = max(1, len(profile.visitors))
    share_tired = len(summary["fatigued"]) / n
    behind = bool(summary["exclusion_unresolved"]) or bool(summary.get("fell_behind"))
    if share_tired >= C.PACE_FATIGUE_SHARE or behind:
        pace = "slower"
        if share_tired >= C.PACE_FATIGUE_SHARE:
            reasons.append(f"pace slower: {share_tired:.0%} of the group showed fatigue (≥ PACE_FATIGUE_SHARE={C.PACE_FATIGUE_SHARE})")
        elif summary.get("fell_behind"):
            reasons.append("pace slower: someone fell behind on the last move (floor, §6.2)")
        else:
            reasons.append("pace slower: someone is still excluded at stop end (floor, §6.2)")
    else:
        pace = "same"
        reasons.append(f"pace same: {share_tired:.0%} showed fatigue (< PACE_FATIGUE_SHARE)")
    deep = sum(1 for v in profile.visitors.values()
               if any(l.kind == "depth" and l.status == "confirmed" for l in v.layers.values()))
    depth = "raised" if deep / n > C.DEPTH_RAISE_SHARE else "same"
    reasons.append(f"depth {depth}: {deep}/{n} have a confirmed depth layer (raise if > DEPTH_RAISE_SHARE)")

    options = [o for o in gallery["route"]["branches"].get(stop, []) if o not in visited]
    if not options:
        return {"next": None, "pace": pace, "depth": depth, "scores": {}, "offer_choice": False,
                "reasons": reasons + ["no further stops on the route: tour close"]}
    scores = {}
    for o in options:
        s = 0.0
        for tid, v in profile.visitors.items():
            si = min(1.0, sum(1.0 for l in v.layers.values() if l.status == "confirmed" and _serves_exhibit(l, o)))
            s += profile.weight(tid) * si
        scores[o] = round(s, 3)
    ranked = sorted(options, key=lambda o: (-scores[o], options.index(o)))
    nxt = ranked[0]
    close = len(ranked) > 1 and scores[ranked[0]] - scores[ranked[1]] <= C.NEXT_STOP_CLOSE
    if close:
        reasons.append(f"weighted confirmed-interest scores {scores}: top two within NEXT_STOP_CLOSE="
                       f"{C.NEXT_STOP_CLOSE}, so offer a two-way choice between {ranked[0]} and {ranked[1]} (P12)")
    else:
        reasons.append(f"next {nxt}: best weighted confirmed-interest score {scores} (D1, D8)")
    return {"next": nxt, "pace": pace, "depth": depth, "scores": scores, "offer_choice": close,
            "choice": ranked[:2] if close else None, "reasons": reasons}
