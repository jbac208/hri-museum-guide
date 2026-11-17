"""Level 1 integration: our perception's start_impression inside Joey's scenarios (test scaffolding, not product code).

    python3 -m perception.integration.run_in_scenario [--seeds 20] [--out perception/integration/results.md]

For each scenario (s1_one_stop open loop with labels; s1_closed and s2_multi_stop closed loop) and seed:
  1. a fake encounter scene built from his visitors (count, age class, cluster): they stand in front of the robot
     before the tour; our real Encounter (filter_faces, tracker, gate, clusters, engagement) runs on it;
  2. our ids are mapped to his (visitor_k -> vN) by matching boxes at the event (scaffolding only);
  3. his start_impression line is replaced by ours and his own code runs unchanged:
       open loop:   sdc.mock.generate -> line 2 replaced -> SignalLayer -> eval_signals.evaluate
       closed loop: sdc.sim.Sim.start_lines patched in this process only (restored in a finally) ->
                    sdc.sim.run_closed_loop / run_tour with the factories compare_policies uses.
Nothing in sdc/ or his root scripts is edited. His thresholds are untouched.

Fake-scene assumptions (they decide our clusters; see perception/README.md):
  frame 1280 x 400 px; left to right in his visitor order (v1..v6; companions are adjacent in it);
  adult face 80 px wide (height 1.2 x width), child face 0.85 x that; companions GAP_IN = 0.3 face widths apart,
  clusters GAP_OUT = 2.5 face widths apart; everyone walks up together (faces grow from 0.5x to full size in 3 s)
  and then stands still; per-person seeded embeddings with small per-frame noise.
"""

from __future__ import annotations

import argparse
import contextlib
import random
import statistics
import sys

import numpy as np

import compare_policies as cp                       # Joey's root script: run_s1/run_s2 factories, row, summarise, table
import eval_signals                                 # Joey's root script: evaluate, match
from sdc import adapter, mock, scenarios, schema, sim as sdc_sim
from sdc.loop import Loop
from sdc.policies import OURS
from sdc.signals import SignalLayer
from sdc.tour import Tour

from perception.age import AgeProbs
from perception.encounter import Encounter
from perception.tracker import Detection, _iou

FRAME_H, FRAME_W, RATE_HZ, DURATION_S = 400, 1280, 10, 20.0
ADULT_W, CHILD_SCALE = 80, 0.85
GAP_IN, GAP_OUT = 0.3, 2.5
PROBS = {"adult": AgeProbs(0.05, 0.93, 0.02), "child": AgeProbs(0.88, 0.08, 0.04),
         "unsure": AgeProbs(0.20, 0.35, 0.45)}       # unsure: same mass as the teenager in run_encounter.FakeCamera


# ---------------------------------------------------------------- fake encounter scene

class ScenarioCamera:
    """people: [(his_id, age_class, cluster_id)] left to right. bands: his_id -> what the age estimator reports
    (adult | child | unsure). Also acts as the age estimator: it reports PROBS[band] (seeded jitter) for whichever
    scripted face a box belongs to."""

    def __init__(self, people, bands, seed):
        self.people, self.bands = people, bands
        self.rng, self.jitter = np.random.RandomState(seed), random.Random(seed)
        self.embs = {}
        self.layout = {}                                      # his_id -> (x centre, full face width)
        x = 0.0
        for i, (tid, age, cl) in enumerate(people):
            w = ADULT_W * (CHILD_SCALE if age == "child" else 1.0)
            if i:
                x += (GAP_IN if cl == people[i - 1][2] else GAP_OUT) * ADULT_W
            self.layout[tid] = (x + w / 2, w)
            x += w
            v = np.random.RandomState(seed * 100 + i).randn(512)
            self.embs[tid] = v / np.linalg.norm(v)
        shift = (FRAME_W - x) / 2
        assert shift > 0, "scene wider than the frame"
        self.layout = {k: (cx + shift, w) for k, (cx, w) in self.layout.items()}
        self.frame = np.zeros((FRAME_H, FRAME_W, 3), np.uint8)
        self.t = 0.0

    def frames(self):
        for i in range(int(DURATION_S * RATE_HZ)):
            self.t = round(i / RATE_HZ, 3)
            yield self.t, self.frame

    def boxes(self):
        s = 0.5 + 0.5 * min(self.t / 3.0, 1.0)
        out = {}
        for tid, (cx, w) in self.layout.items():
            w2, h2 = w * s / 2, 1.2 * w * s / 2
            out[tid] = (int(cx - w2), int(FRAME_H / 2 - h2), int(cx + w2), int(FRAME_H / 2 + h2))
        return out

    def detect(self, frame):
        out = []
        for tid, b in self.boxes().items():
            e = self.embs[tid] + 0.05 * self.rng.randn(512) / np.sqrt(512)
            out.append(Detection(b, e / np.linalg.norm(e)))
        return out

    def his_id_for(self, box):
        return max(self.boxes().items(), key=lambda kv: _iou(kv[1], box))[0]

    def estimate(self, frame, box, key=None):
        p = PROBS[self.bands[self.his_id_for(box)]]
        d = self.jitter.uniform(-0.03, 0.03)
        pc = min(max(p.p_child + d, 0.0), 1.0 - p.p_teen)
        return AgeProbs(pc, max(1.0 - p.p_teen - pc, 0.0), p.p_teen)


def our_impression(his_si, bands, seed):
    """Run our Encounter on the fake scene for his visitors; return (start_impression with his ids, notes)."""
    people = [(v["track_id"], v["age_class"], v["cluster_id"]) for v in his_si["visitors"]]
    cam = ScenarioCamera(people, bands, seed)
    at_event = {}

    def on_frame(t, enc, ev):
        if ev is not None:
            at_event.update({pid: cam.his_id_for(r["box"]) for pid, r in enc.latest.items()})

    si = Encounter(cam, cam.detect).run(cam.frames(), on_frame)
    if si is None:
        raise RuntimeError(f"no engagement event in the fake scene (seed {seed})")
    mapped = [at_event[v["track_id"]] for v in si["visitors"]]
    if len(set(mapped)) != len(mapped):
        raise RuntimeError(f"id mapping not one-to-one: {mapped}")
    for v, his in zip(si["visitors"], mapped):
        v["track_id"] = his
    notes = {"t_event": si["t"], "missing": sorted({p[0] for p in people} - set(mapped)),
             "clusters": {v["track_id"]: v["cluster_id"] for v in si["visitors"]}}
    schema.validate_start_impression(si)
    return si, notes


# ---------------------------------------------------------------- splice

@contextlib.contextmanager
def replaced_start_impression(make):
    """Inside the block, every Sim/TourSim built by Joey's drivers emits make(his_start_impression, sim) instead of
    his own start_impression line. Restored in a finally, also when the run raises."""
    orig = sdc_sim.Sim.start_lines

    def patched(self):
        header, his = orig(self)
        return [header, make(his, self)]

    sdc_sim.Sim.start_lines = patched
    try:
        yield
    finally:
        sdc_sim.Sim.start_lines = orig


def run_s1_open(make, seed):
    """s1_one_stop, open loop: his mock stream with line 2 replaced. Returns (eval result, events)."""
    scn = scenarios.s1_one_stop()
    scn.seed = seed
    lines = mock.generate(scn, cp.GALLERY)
    assert lines[1]["type"] == "start_impression"
    lines[1] = make(lines[1], None)
    schema.validate_stream(lines)
    events = SignalLayer(cp.GALLERY, scn.stop).run(adapter.from_lines(lines))
    return eval_signals.evaluate(events, scn.labels), events


def run_s1_closed(seed):
    """Same as compare_policies.run_s1 (policy ours), but also returns the events."""
    spec = scenarios.s1_closed()
    spec.seed = spec.scenario.seed = seed
    loop, *_ = sdc_sim.run_closed_loop(spec, cp.GALLERY, lambda scn: Loop(
        cp.GALLERY, scn.stop, scn.duration_s, contents=cp.CONTENTS, scenario=scn.name, policy=OURS))
    return loop.records()[-1], loop.signals.events


def run_s2(seed):
    """Same as compare_policies.run_s2 (policy ours), but also returns the events."""
    spec = scenarios.s2_multi_stop()
    spec.seed = seed
    tour, *_ = sdc_sim.run_tour(spec, cp.GALLERY, lambda s: Tour(
        cp.GALLERY, s.first_stop, s.stop_durations, contents=cp.CONTENTS, scenario=s.name, policy=OURS))
    m = tour.records()[-1]
    m["_stops"] = tour.visited
    return m, tour.signals.events


# ---------------------------------------------------------------- conditions

PEOPLE_AGES = {"v1": "adult", "v2": "child", "v3": "adult", "v4": "adult", "v5": "adult", "v6": "adult"}


def conditions():
    """name -> bands override (None = Joey's own start impression)."""
    c = {"A": None, "B": {}}
    for tid, age in PEOPLE_AGES.items():
        if age == "adult":
            c[f"C-{tid}"] = {tid: "child"}
    c["C2"] = {"v2": "adult"}
    c["D"] = {"v2": "unsure"}
    c["D-all"] = {tid: "unsure" for tid in PEOPLE_AGES}
    # diagnostics that split effect (i): ours with one field per visitor copied back from his impression
    c["B+his distance_m"] = {"_his": "distance_m"}
    c["B+his cluster_id"] = {"_his": "cluster_id"}
    return c


def maker(override, seed, notes_out):
    """The splice function for one condition and seed (None = pass his line through)."""
    def make(his, _sim):
        if override is None:
            return his
        bands = {v["track_id"]: v["age_class"] for v in his["visitors"]}
        bands |= {k: v for k, v in override.items() if not k.startswith("_")}
        si, notes = our_impression(his, bands, seed)
        field = override.get("_his")
        if field:                                       # diagnostic only: placeholder_fields is then not exact
            hv = {v["track_id"]: v for v in his["visitors"]}
            for v in si["visitors"]:
                if field == "distance_m":
                    v["baseline_seed"]["distance_m"] = hv[v["track_id"]]["baseline_seed"]["distance_m"]
                else:
                    v[field] = hv[v["track_id"]][field]
        notes_out.append(notes)
        return si
    return make


def first_detections(events):
    """(track_id, kind) -> (count, first t_detect)."""
    out = {}
    for e in events:
        n, t = out.get((e.track_id, e.kind), (0, None))
        out[(e.track_id, e.kind)] = (n + 1, e.t_detect if t is None else min(t, e.t_detect))
    return out


# ---------------------------------------------------------------- report

def _pr_row(res):
    r = {}
    for k, row in res["rows"].items():
        if row["labels"]:
            r[f"{k} precision"] = row["precision"] if row["precision"] is not None else 0.0
            r[f"{k} recall"] = row["recall"]
    r["v4 (reserved) events"] = len(res["quiet_events"])
    return r


def _label_latency(res):
    """(track_id, kind) -> {"lat": latencies of matched labels, None per missed label, "extra": [t_detect of
    detections matching no label]}."""
    out = {}
    get = lambda k: out.setdefault(k, {"lat": [], "extra": []})
    for l, e in res["pairs"]:
        get((l["track_id"], l["kind"]))["lat"].append(e.t_detect - l["t0"])
    for l in res["fn"]:
        get((l["track_id"], l["kind"]))["lat"].append(None)
    for e in res["fp"]:
        get((e.track_id, e.kind))["extra"].append(e.t_detect)
    return out


def _fmt_t(vals):
    vals = [v for v in vals if v is not None]
    return f"{statistics.mean(vals):.1f} s" if vals else "–"


def event_diffs(ref, test, seeds, labelled=False):
    """ref/test: {seed: per-seed detail}. Lines for every (visitor, kind) whose events differ."""
    lines = []
    keys = sorted({k for s in seeds for k in ref[s]} | {k for s in seeds for k in test[s]})
    for k in keys:
        if labelled:
            empty = {"lat": [], "extra": []}
            a = [x for s in seeds for x in ref[s].get(k, empty)["lat"]]
            b = [x for s in seeds for x in test[s].get(k, empty)["lat"]]
            xa = [x for s in seeds for x in ref[s].get(k, empty)["extra"]]
            xb = [x for s in seeds for x in test[s].get(k, empty)["extra"]]
            ma, mb = sum(x is None for x in a), sum(x is None for x in b)
            la, lb = [x for x in a if x is not None], [x for x in b if x is not None]
            if ma != mb or len(xa) != len(xb) or (la and lb and abs(statistics.mean(la) - statistics.mean(lb)) >= 0.5):
                extra = lambda xs: f", {len(xs)} unlabelled detection(s)" + (f" at mean {_fmt_t(xs)}" if xs else "")
                lines.append(f"{k[0]} {k[1]}: matched {len(la)}/{len(a)} labels, latency {_fmt_t(la)}{extra(xa)} → "
                             f"matched {len(lb)}/{len(b)}, latency {_fmt_t(lb)}{extra(xb)}")
        else:
            fa = [ref[s].get(k) for s in seeds]
            fb = [test[s].get(k) for s in seeds]
            na, nb = sum(x is not None for x in fa), sum(x is not None for x in fb)
            ca = sum(x[0] for x in fa if x)
            cb = sum(x[0] for x in fb if x)
            ta, tb = [x[1] for x in fa if x], [x[1] for x in fb if x]
            shift = (statistics.mean(tb) - statistics.mean(ta)) if ta and tb else None
            if na != nb or ca != cb or (shift is not None and abs(shift) >= 0.5):
                lines.append(f"{k[0]} {k[1]}: fired in {na}/{len(seeds)} seeds ({ca} events), first at {_fmt_t(ta)} → "
                             f"{nb}/{len(seeds)} seeds ({cb} events), first at {_fmt_t(tb)}"
                             + (f" (shift {shift:+.1f} s)" if shift is not None else ""))
    return lines or ["(no visitor's events differ)"]


def run_all(n_seeds):
    seeds = list(range(1, n_seeds + 1))
    conds = conditions()
    out = {}
    for scen in ("s1_one_stop", "s1_closed", "s2_multi_stop"):
        rows, detail, notes = {}, {}, {}
        for name, override in conds.items():
            rows[name], detail[name], notes[name] = [], {}, []
            for seed in seeds:
                make = maker(override, seed, notes[name])
                if scen == "s1_one_stop":
                    res, _ = run_s1_open(make, seed)
                    rows[name].append(_pr_row(res))
                    detail[name][seed] = _label_latency(res)
                else:
                    with replaced_start_impression(make):
                        m, events = (run_s1_closed if scen == "s1_closed" else run_s2)(seed)
                    r = cp.row(m)
                    if scen == "s2_multi_stop":
                        r["route"] = " → ".join(m["_stops"])
                    rows[name].append(r)
                    detail[name][seed] = first_detections(events)
        out[scen] = (rows, detail, notes)
        print(f"{scen}: done", file=sys.stderr)
    return seeds, conds, out


def report(seeds, conds, out):
    n = len(seeds)
    md = [f"# Level 1 integration results: our start impression in Joey's scenarios",
          "",
          f"Generated by `python3 -m perception.integration.run_in_scenario --seeds {n}` (policy `ours`, seeds 1–{n}, "
          "mean [min–max] via `compare_policies.summarise`). Simulated visitors: this shows how our start impression "
          "changes Joey's loop on his scripted visitors, nothing about real visitors.",
          "",
          "Conditions: **A** his own start impression · **B** ours, ages right · **C-vN** ours, adult vN read as a "
          "child (glance seed 4 → 6) · **C2** ours, the child v2 read as an adult (6 → 4) · **D** ours, v2 unsure "
          "(seed 5.0) · **D-all** ours, all six unsure (5.0). Diagnostics: **B+his distance_m** / **B+his cluster_id** = "
          "B with that one field per visitor copied back from his impression, to split effect (i).",
          "",
          "Effects, kept apart: (i) our placeholder seeds and clusters = **B vs A**; (ii) age errors = **C-\\*, C2 vs B**; "
          "(iii) unsure = **D, D-all vs B**.",
          ""]
    rows, _, notes = out["s1_closed"]
    ex = notes["B"][0]
    md += ["## Our encounter on the fake scene", "",
           f"Seed 1, condition B: event at t = {ex['t_event']} s; missing from our impression: "
           f"{ex['missing'] or 'nobody'}; our clusters: {ex['clusters']} (his: v1 c1 · v2, v3 c2 · v4 c3 · v5, v6 c4).",
           ""]
    all_notes = [x for scen in out.values() for c, ns in scen[2].items() for x in ns]
    missing = sorted({m for x in all_notes for m in x["missing"]})
    cluster_sets = sorted({tuple(sorted(x["clusters"].items())) for x in all_notes})
    md += [f"Across all {len(all_notes)} encounters: visitors ever missing: {missing or 'none'}; "
           f"distinct cluster assignments: {len(cluster_sets)}.", ""]
    for i, cs in enumerate(cluster_sets):
        md.append(f"- assignment {i + 1}: {dict(cs)}")
    md.append("")

    effects = [("(i) placeholder seeds and clusters (+ two diagnostics that copy one field back from his impression)",
                ["A", "B", "B+his distance_m", "B+his cluster_id"], "A"),
               ("(ii) age errors", ["B"] + [c for c in conds if c.startswith("C")], "B"),
               ("(iii) unsure", ["B", "D", "D-all"], "B")]
    for scen, title in (("s1_one_stop", "s1_one_stop: signal layer vs labels (open loop)"),
                        ("s1_closed", "s1_closed: one stop, closed loop"),
                        ("s2_multi_stop", "s2_multi_stop: three stops, closed loop")):
        rows, detail, _ = out[scen]
        md += [f"## {title}", ""]
        for eff, names, ref in effects:
            summ = {c: cp.summarise([{k: v for k, v in r.items() if k != "route"} for r in rows[c]]) for c in names}
            keys = list(summ[names[0]])
            md += [cp.table(f"{eff}", summ, keys), ""]
            if scen == "s2_multi_stop":
                md += ["Routes: " + "; ".join(f"{c}: " + ", ".join(sorted({r['route'] for r in rows[c]})) for c in names), ""]
            for c in names:
                if c == ref:
                    continue
                md += [f"Per-visitor events, {c} vs {ref}" + (" (labelled: matched labels and latency from label start)"
                                                               if scen == "s1_one_stop" else
                                                               " (no labels: seeds where the event fired, event count, "
                                                               "mean first detection time)") + ":", ""]
                md += [f"- {l}" for l in event_diffs(detail[ref], detail[c], seeds, labelled=scen == "s1_one_stop")]
                md.append("")
    return "\n".join(md) + "\n"


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--seeds", type=int, default=20)
    ap.add_argument("--out", help="write the markdown report here (default: print)")
    a = ap.parse_args(argv)
    md = report(*run_all(a.seeds))
    if a.out:
        with open(a.out, "w") as f:
            f.write(md)
    else:
        print(md)
    return 0


if __name__ == "__main__":
    sys.exit(main())
