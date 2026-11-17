"""Level 2 check (run once): also take track_conf, age_class, age_conf and cluster_id per frame from ours; geometry
stays on Joey's mock. Our pipeline does not see his tour frames (they have no images), so each visitor's values are
the ones our encounter produced (track_conf = our tracker's value at the event), written into every frame.
Compares against Level 1 condition B, seed by seed: are measures and events identical?

    python3 -m perception.integration.level2_check [--seeds 20]
"""

from __future__ import annotations

import argparse
import contextlib
import sys

from sdc import sim as sdc_sim

from perception.integration import run_in_scenario as R


def overwrite(line, per):
    if line["type"] == "frame":
        for v in line["visitors"]:
            v.update(per[v["track_id"]])
    return line


def b_with_frame_values(seed, per):
    """Condition B's splice; also fills `per` with our values for every visitor's frames."""
    def make(his, _sim):
        notes = []
        si = R.maker({}, seed, notes)(his, _sim)
        per.update({v["track_id"]: {"track_conf": notes[0]["track_conf"][v["track_id"]], "age_class": v["age_class"],
                                    "age_conf": v["age_conf"], "cluster_id": v["cluster_id"]} for v in si["visitors"]})
        return si
    return make


@contextlib.contextmanager
def frames_from_ours(per):
    orig = sdc_sim.Sim.step
    sdc_sim.Sim.step = lambda self, t: [overwrite(l, per) for l in orig(self, t)]
    try:
        yield
    finally:
        sdc_sim.Sim.step = orig


def run_one(scen, seed):
    """(Level 1 B result, Level 2 result), each (measures or None, events)."""
    per = {}
    if scen == "s1_one_stop":
        b = R.run_s1_open(R.maker({}, seed, []), seed)[1]
        make = b_with_frame_values(seed, per)
        scn = R.scenarios.s1_one_stop()
        scn.seed = seed
        lines = R.mock.generate(scn, R.cp.GALLERY)
        lines[1] = make(lines[1], None)
        lines = [overwrite(l, per) for l in lines]
        R.schema.validate_stream(lines)
        return (None, b), (None, R.SignalLayer(R.cp.GALLERY, scn.stop).run(R.adapter.from_lines(lines))), per
    run = R.run_s1_closed if scen == "s1_closed" else R.run_s2
    with R.replaced_start_impression(R.maker({}, seed, [])):
        b = run(seed)
    with R.replaced_start_impression(b_with_frame_values(seed, per)), frames_from_ours(per):
        l2 = run(seed)                           # run_closed_loop / run_tour validate every line
    return b, l2, per


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--seeds", type=int, default=20)
    a = ap.parse_args(argv)
    same, total, confs = 0, 0, set()
    for scen in ("s1_one_stop", "s1_closed", "s2_multi_stop"):
        for seed in range(1, a.seeds + 1):
            (mb, eb), (m2, e2), per = run_one(scen, seed)
            ok = mb == m2 and [e.as_dict() for e in eb] == [e.as_dict() for e in e2]
            same, total = same + ok, total + 1
            confs |= {round(p["track_conf"], 3) for p in per.values()}
            if not ok:
                print(f"{scen} seed {seed}: DIFFERS from Level 1 B")
    print(f"Level 2 vs Level 1 condition B: identical measures and events in {same}/{total} runs "
          f"(3 scenarios x {a.seeds} seeds). track_conf values written: {sorted(confs)}")
    return 0 if same == total else 1


if __name__ == "__main__":
    sys.exit(main())
