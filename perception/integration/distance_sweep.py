"""Distance error sweep (simulation only): how accurate must a per-visitor distance_m seed be?

    python3 -m perception.integration.distance_sweep [--seeds 20] [--out perception/integration/distance_sweep.md]

Every condition is Level 1 "B + his distance_m" (our start impression, with his true distance_m copied in) plus an
error on EVERY visitor's distance_m: a constant bias (+-0.1, +-0.3, +-0.5 m) or random error (normal, std 0.3 m,
drawn per visitor from random.Random(seed), so it is the same in all three scenarios of a seed). "true" = no error,
which equals A (his own start impression) in every measure (perception/integration/results.md). Nothing else changes:
no frame geometry is produced, sdc/ and his thresholds are untouched.
"""

from __future__ import annotations

import argparse
import random
import statistics
import sys

from perception.integration import run_in_scenario as R

BIASES = (-0.5, -0.3, -0.1, 0.1, 0.3, 0.5)
NOISE_STD = 0.3


def noise(seed, tids):
    rng = random.Random(seed)
    return {t: rng.gauss(0.0, NOISE_STD) for t in sorted(tids)}


def conditions():
    """name -> err(seed, track_ids) -> {track_id: error in m} (None = A, his own start impression)."""
    c = {"A": None, "true": lambda seed, tids: {t: 0.0 for t in tids}}
    for b in BIASES:
        c[f"{b:+.1f} m"] = lambda seed, tids, b=b: {t: b for t in tids}
    c[f"noise σ={NOISE_STD}"] = noise
    return c


def maker(err_for, seed, applied):
    """Splice: B + his distance_m, plus err_for(seed, track_ids). `applied` collects (track_id, true, seeded)."""
    if err_for is None:
        return lambda his, _sim: his
    inner = R.maker({"_his": "distance_m"}, seed, [])

    def make(his, sim):
        si = inner(his, sim)
        err = err_for(seed, [v["track_id"] for v in si["visitors"]])
        for v in si["visitors"]:
            d = v["baseline_seed"]["distance_m"]
            v["baseline_seed"]["distance_m"] = round(d + err[v["track_id"]], 3)
            if v["baseline_seed"]["distance_m"] <= 0:
                raise RuntimeError(f"seed {seed}: {v['track_id']} distance_m {d} + {err[v['track_id']]:.2f} <= 0")
            applied.append((v["track_id"], d, v["baseline_seed"]["distance_m"]))
        R.schema.validate_start_impression(si)
        return si
    return make


def run_all(n_seeds):
    seeds = list(range(1, n_seeds + 1))
    conds = conditions()
    out = {}
    for scen in ("s1_one_stop", "s1_closed", "s2_multi_stop"):
        rows, detail, applied = {}, {}, {}
        for name, err_for in conds.items():
            rows[name], detail[name], applied[name] = [], {}, []
            for seed in seeds:
                make = maker(err_for, seed, applied[name])
                if scen == "s1_one_stop":
                    res, _ = R.run_s1_open(make, seed)
                    rows[name].append(R._pr_row(res))
                    detail[name][seed] = R._label_latency(res)
                else:
                    with R.replaced_start_impression(make):
                        m, events = (R.run_s1_closed if scen == "s1_closed" else R.run_s2)(seed)
                    rows[name].append(R.cp.row(m))
                    detail[name][seed] = R.first_detections(events)
        out[scen] = (rows, detail, applied)
        print(f"{scen}: done", file=sys.stderr)
    return seeds, conds, out


def _mean(xs, fmt="{:.1f}"):
    xs = [x for x in xs if x is not None]
    return fmt.format(statistics.mean(xs)) if xs else "–"


def _mmm(xs):
    return f"{statistics.mean(xs):.2f} [{min(xs):.2f}–{max(xs):.2f}]"


def _focus_open(rows, detail, seeds, name):
    lat = lambda k: [x for s in seeds for x in detail[name][s].get(("v2", k), {"lat": []})["lat"]]
    extra = sum(len(detail[name][s].get(("v2", "bid"), {"extra": []})["extra"]) for s in seeds)
    # a matched bid with negative latency fired before the child started edging in (the matcher credits it by overlap)
    early = sum(x is not None and x < 0 for x in lat("bid"))
    appr_extra = sum(len(d["extra"]) for s in seeds for (tid, k), d in detail[name][s].items() if k == "approach")
    return [_mean(lat("excluded")) + " s", f"{sum(x is None for x in lat('excluded'))}",
            _mean(lat("bid")) + " s", f"{sum(x is None for x in lat('bid'))}", f"{early}", f"{extra}",
            _mmm([r["bid precision"] for r in rows[name]]), f"{appr_extra}",
            _mmm([r["approach precision"] for r in rows[name]])]


def _focus_closed(rows, detail, seeds, name):
    first = lambda k: [detail[name][s][("v2", k)][1] for s in seeds if ("v2", k) in detail[name][s]]
    ep = [r["exclusion episodes"] for r in rows[name]]
    ttr = [r["time to resolve (s)"] for r in rows[name] if r["time to resolve (s)"] is not None]
    p13 = [r["P13 unresolved share"] for r in rows[name]]
    ref_ep = [r["exclusion episodes"] for r in rows["A"]]
    return [_mean(first("bid")) + " s", _mean(first("excluded")) + " s",
            f"{statistics.mean(ep):.2f} [{min(ep)}–{max(ep)}]",
            f"{sum(a > b for a, b in zip(ref_ep, ep))}",
            _mmm(ttr) if ttr else "–", f"{max(p13):.2f}", _mmm([r["misread rate"] for r in rows[name]])]


def report(seeds, conds, out):
    n = len(seeds)
    names = list(conds)
    md = ["# Distance error sweep: how accurate must the distance_m seed be? (simulation only)", "",
          f"Generated by `python3 -m perception.integration.distance_sweep --seeds {n}` (policy `ours`, seeds 1–{n}). "
          "Every condition except A is our start impression with Joey's true `distance_m` copied in (Level 1 "
          "\"B + his distance_m\"), plus an error on **every** visitor: a constant bias, or random error (normal, "
          f"std {NOISE_STD} m, per visitor, seeded by the run seed). **true** = no error. Simulated visitors only; his "
          "thresholds (`APPROACH_MIN_DROP_M` 0.3, `EDGE_MIN_DROP_M` 0.06, `sdc/config.py`) untouched.", ""]
    _, _, applied = out["s1_closed"]
    tru = sorted({(t, d) for t, d, _ in applied["true"]})
    md += [f"His true seeds (s1, every seed): {', '.join(f'{t} {d} m' for t, d in tru)}. "
           "v2 (the excluded child) starts outside the formation ring (1.0–2.6 m, `sdc/mock.py:20`).", ""]
    noise = [s - d for _, d, s in applied[f"noise σ={NOISE_STD}"]]
    md += [f"Random-error condition: {len(noise)} visitor seeds, error mean {statistics.mean(noise):+.2f} m, "
           f"std {statistics.pstdev(noise):.2f} m, range {min(noise):+.2f} to {max(noise):+.2f} m.", ""]

    rows, detail, _ = out["s1_one_stop"]
    md += ["## v2 in s1_one_stop (open loop, labelled)", "",
           "| condition | v2 excluded latency | excluded labels missed | v2 bid latency | bid labels missed | "
           "v2 bids before the child edged in | unlabelled v2 bids | bid precision | unlabelled approaches (all) | "
           "approach precision |", "|---|---|---|---|---|---|---|---|---|---|"]
    md += [f"| {c} | " + " | ".join(_focus_open(rows, detail, seeds, c)) + " |" for c in names]
    md.append("")
    for scen, title in (("s1_closed", "s1_closed (one stop, closed loop)"),
                        ("s2_multi_stop", "s2_multi_stop (three stops, closed loop)")):
        rows, detail, _ = out[scen]
        md += [f"## v2 in {title}", "",
               "| condition | v2 first bid | v2 first excluded | exclusion episodes | seeds with fewer episodes than A | "
               "time to resolve (s) | max P13 share | misread rate |", "|---|---|---|---|---|---|---|---|"]
        md += [f"| {c} | " + " | ".join(_focus_closed(rows, detail, seeds, c)) + " |" for c in names]
        md.append("")

    md += ["## All measures and every visitor's events", ""]
    for scen in ("s1_one_stop", "s1_closed", "s2_multi_stop"):
        rows, detail, _ = out[scen]
        summ = {c: R.cp.summarise(rows[c]) for c in names}
        md += [R.cp.table(scen, summ, list(summ[names[0]])), ""]
        for c in names[1:]:
            md += [f"Per-visitor events, {c} vs A:", ""]
            md += [f"- {l}" for l in R.event_diffs(detail["A"], detail[c], seeds, labelled=scen == "s1_one_stop")]
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
