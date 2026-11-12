"""Baseline comparison (task 9, P14): our loop vs one-size-fits-all vs engagement-maximising.

    python3 compare_policies.py              # 20 seeds of s1_closed, 10 of s2_multi_stop
    python3 compare_policies.py --seeds 5    # quicker

Same sim, same visitors, same seeds for every policy; only the decision layer's switches differ
(sdc/policies.py). Prints a markdown table (mean, [min-max] over seeds) and writes results/policies.md.

Caveat for the paper: the visitors are simulated. Their reactions are rules (e.g. the child only joins
the formation when the robot opens it; uptake depends on hidden interests), so these numbers show the
mechanisms working as designed, not how real visitors would respond.
"""
import argparse, json, os, statistics, sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from sdc import content, policies, scenarios
from sdc.loop import Loop
from sdc.sim import run_closed_loop, run_tour
from sdc.tour import Tour

GALLERY = json.load(open(os.path.join(HERE, "data", "gallery.json")))
CONTENTS = content.load_all(GALLERY)


def run_s1(policy, seed):
    spec = scenarios.s1_closed()
    spec.seed = spec.scenario.seed = seed
    loop, *_ = run_closed_loop(spec, GALLERY, lambda scn: Loop(GALLERY, scn.stop, scn.duration_s, contents=CONTENTS,
                                                                 scenario=scn.name, policy=policy))
    return loop.records()[-1]


def run_s2(policy, seed):
    spec = scenarios.s2_multi_stop()
    spec.seed = seed
    tour, *_ = run_tour(spec, GALLERY, lambda s: Tour(GALLERY, s.first_stop, s.stop_durations, contents=CONTENTS,
                                                       scenario=s.name, policy=policy))
    m = tour.records()[-1]
    m["_stops"] = tour.visited
    return m


def row(ms):
    """Pull the comparable numbers out of one run's measures."""
    ex = ms["exclusion"]
    return {
        "steering uptake": ms["steering_uptake"]["share"] or 0.0,
        "exclusion episodes": ex["episodes"],
        "resolved": ex["resolved"],
        "time to resolve (s)": ex["mean_time_to_resolve_s"],
        "P13 unresolved share": ms["p13_unresolved"]["share"] or 0.0,
        "misread rate": ms["misread_rate"]["rate"],
        "dominance share": ms["dominance_share"]["share"],
        "fell behind": ms.get("falling_behind", {}).get("episodes", 0),
        "started w/o everyone": ms.get("falling_behind", {}).get("stops_started_without_everyone", 0),
    }


def summarise(rows):
    out = {}
    for k in rows[0]:
        vals = [r[k] for r in rows if r[k] is not None]
        if not vals:
            out[k] = "–"
        else:
            m, lo, hi = statistics.mean(vals), min(vals), max(vals)
            fmt = (lambda x: f"{x:.0f}") if all(float(v).is_integer() for v in vals) and k not in (
                "steering uptake", "P13 unresolved share", "misread rate", "dominance share") else (lambda x: f"{x:.2f}")
            out[k] = fmt(m) if lo == hi else f"{m:.2f} [{fmt(lo)}–{fmt(hi)}]"
            if len(vals) < len(rows):
                out[k] += f" (n={len(vals)})"
    return out


def table(title, results, keys):
    names = list(results)
    lines = [f"### {title}", "", "| measure | " + " | ".join(names) + " |", "|---|" + "---|" * len(names)]
    for k in keys:
        lines.append(f"| {k} | " + " | ".join(results[n][k] for n in names) + " |")
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seeds", type=int, default=20)
    a = ap.parse_args()
    s1_seeds, s2_seeds = range(1, a.seeds + 1), range(1, max(2, a.seeds // 2) + 1)
    s1, s2, routes = {}, {}, {}
    for name, pol in policies.ALL.items():
        s1[name] = summarise([row(run_s1(pol, s)) for s in s1_seeds])
        runs = [run_s2(pol, s) for s in s2_seeds]
        s2[name] = summarise([row(m) for m in runs])
        routes[name] = sorted({" → ".join(m["_stops"]) for m in runs})
    keys1 = ["steering uptake", "exclusion episodes", "resolved", "time to resolve (s)", "P13 unresolved share",
             "misread rate", "dominance share"]
    keys2 = keys1 + ["fell behind", "started w/o everyone"]
    md = "\n\n".join([
        "## Baseline comparison (simulated visitors)",
        "Policies: **ours** (the loop as designed) · **one_size** (fixed tour, Burgard 1999) · "
        "**engagement** (engagement-maximising, Lin 2024). Same sim and seeds for each; mean [min–max].",
        table(f"s1_closed: one stop, {len(s1_seeds)} seeds", s1, keys1),
        table(f"s2_multi_stop: three stops, {len(s2_seeds)} seeds", s2, keys2),
        "Routes taken in s2: " + "; ".join(f"{n}: {', '.join(r)}" for n, r in routes.items()),
        "Steering uptake = share of steering signals (linger, approach, drift, point/ask) the robot visibly acted on "
        "(answered, or addressed with an addition). Dominance share = share of acted-on signals from the single most-"
        "served visitor. P13 = share of visitors with an exclusion episode still unresolved at a stop's end. "
        "Simulated visitors: these show the mechanisms, not real-visitor outcomes.",
    ])
    print(md)
    os.makedirs(os.path.join(HERE, "results"), exist_ok=True)
    with open(os.path.join(HERE, "results", "policies.md"), "w") as f:
        f.write(md + "\n")


if __name__ == "__main__":
    main()
