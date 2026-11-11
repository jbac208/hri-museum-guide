"""Block 3-5 wiring: adapter records -> signal layer -> profile store -> decision layer.

Open-loop on mock streams for now (visitors don't react to the robot; task 5 closes the loop).
"""
from . import content
from .adapter import Frame, StartImpression, Utterance
from .decision import StopController, plan_next_stop
from .profile import ProfileStore
from .signals import SignalLayer


class Loop:
    def __init__(self, gallery, stop, duration_s, stop_index=0, contents=None, t_start=0.0):
        self.gallery = gallery
        self.contents = contents or content.load_all(gallery)
        self.signals = SignalLayer(gallery, stop, stop_index)
        self.profile = ProfileStore()
        self.ctrl = StopController(stop, self.contents[stop], gallery, self.profile, t_start, duration_s)
        self.stop, self.visited = stop, [stop]
        self._seen = set()
        self.t = t_start
        self.plan = None

    def _dispatch(self, events):
        for ev in events:
            started = id(ev) not in self._seen
            self._seen.add(id(ev))
            if started:
                self.profile.on_event(ev, self.stop)
            self.ctrl.on_event(ev, started)

    def step(self, rec):
        if isinstance(rec, StartImpression):
            self.profile.load_start_impression(rec)
        self._dispatch(self.signals.step(rec))
        if isinstance(rec, Frame):
            self.t = rec.t
            self.ctrl.update(rec)
        elif isinstance(rec, Utterance):
            self.ctrl.on_utterance(rec)

    def finish(self):
        self._dispatch(self.signals.finish())
        summary = self.ctrl.end_stop(self.t)
        self.profile.end_stop(self.t)
        self.plan = plan_next_stop(self.stop, self.gallery, self.profile, self.visited, summary)
        if self.plan["offer_choice"]:
            names = {e["id"]: e["name"].lower() for e in self.gallery["exhibits"]}
            a, b = self.plan["choice"]
            self.ctrl._act(self.t, "say_to_group", {"text": f"Next we could see the {names[a]} or the {names[b]}.",
                                                    "id": "between.choice"},
                           "between stops: two close options, offer the group a two-way choice (P12)")
        return {"summary": summary, "plan": self.plan}

    def run(self, records):
        for r in records:
            self.step(r)
        return self.finish()
