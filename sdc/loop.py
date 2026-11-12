"""Block 3-5 wiring: adapter records -> signal layer -> profile store -> decision layer.

Open-loop on mock streams for now (visitors don't react to the robot; task 5 closes the loop).
"""
from . import content
from . import metrics
from .metrics import EventLog
from .adapter import Frame, StartImpression, Utterance
from .decision import StopController, plan_next_stop
from .policies import OURS
from .profile import ProfileStore
from .signals import SignalLayer


class Loop:
    def __init__(self, gallery, stop, duration_s, stop_index=0, contents=None, t_start=0.0, scenario="?",
                 policy=OURS):
        self.policy = policy
        self.gallery = gallery
        self.log = EventLog(scenario, stop, gallery["id"], duration_s)
        self.contents = contents or content.load_all(gallery)
        self.signals = SignalLayer(gallery, stop, stop_index)
        self.profile = ProfileStore(lam=policy.lam)
        self.ctrl = StopController(stop, self.contents[stop], gallery, self.profile, t_start, duration_s,
                                   policy=policy)
        self.ctrl.dwell_of = lambda tid: (self.signals.v[tid].dwell.value if tid in self.signals.v else None)
        self.stop, self.visited = stop, [stop]
        self._seen = set()
        self.t = t_start
        self.plan = None

    def _dispatch(self, events):
        for ev in events:
            started = id(ev) not in self._seen
            self._seen.add(id(ev))
            if started:
                self.log.on_event_start(ev, self.profile.on_event(ev, self.stop))
            self.ctrl.on_event(ev, started)

    def step(self, rec):
        if isinstance(rec, StartImpression):
            self.profile.load_start_impression(rec)
        self._dispatch(self.signals.step(rec))
        if isinstance(rec, Frame):
            self.t = rec.t
            self.log.on_frame(rec)
            self.ctrl.update(rec)
        elif isinstance(rec, Utterance):
            self.ctrl.on_utterance(rec)

    def finish(self):
        summary = self.ctrl.end_stop(self.t)          # first: stream end is not a resolution
        self._dispatch(self.signals.finish())
        self.profile.end_stop(self.t)
        self.plan = plan_next_stop(self.stop, self.gallery, self.profile, self.visited, summary, self.policy)
        if self.plan["offer_choice"]:
            names = {e["id"]: e["name"].lower() for e in self.gallery["exhibits"]}
            a, b = self.plan["choice"]
            self.ctrl._act(max(self.t, self.ctrl.busy_until), "say_to_group", {"text": f"Next we could see the {names[a]} or the {names[b]}.",
                                                    "id": "between.choice"},
                           "between stops: two close options, offer the group a two-way choice (P12)")
        return {"summary": summary, "plan": self.plan}

    def run(self, records):
        for r in records:
            self.step(r)
        return self.finish()

    def records(self):
        """The event log (tracks + events, no video) with the live measures as its last record."""
        return self.log.records(self)

    @property
    def actions(self):
        return self.ctrl.actions

    def decision_log(self):
        return self.ctrl.log

    @property
    def plans(self):
        return [self.plan] if self.plan else []

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
