"""Run a multi-stop tour closed loop against the tour sim and print what happened.

    python3 run_tour.py                     # s2_multi_stop
    python3 run_tour.py --all               # include gaze balancing and cue gazes
    python3 run_tour.py --log out.jsonl [--anon]
"""
import argparse, json, os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from sdc import metrics, scenarios
from sdc.sim import run_tour
from sdc.tour import Tour

GALLERY = json.load(open(os.path.join(HERE, "data", "gallery.json")))


def run(name="s2_multi_stop", spec=None):
    spec = spec or scenarios.TOUR[name]()
    return run_tour(spec, GALLERY, lambda s: Tour(GALLERY, s.first_stop, s.stop_durations, scenario=s.name))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("scenario", nargs="?", default="s2_multi_stop")
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--log")
    ap.add_argument("--anon", action="store_true")
    a = ap.parse_args()
    tour, sim, lines, out = run(a.scenario)
    rows = tour.decision_log() + [dict(r, type="sim") for r in sim.reactions]
    for e in sorted(rows, key=lambda e: e["t"]):
        if e["type"] == "action":
            if not a.all and e["reason"].startswith(("gaze balancing", "cue word")):
                continue
            arg = e["args"].get("text") or e["args"]
            if isinstance(arg, str) and len(arg) > 50:
                arg = arg[:47] + "..."
            print(f"{e['t']:6.1f}  {e['kind']:<12} {str(arg):<50} <- {e['reason'][:110]}")
        elif e["type"] == "sim":
            print(f"{e['t']:6.1f}  [sim] {e['track_id']} {e['reaction']}")
        else:
            extra = {k: v for k, v in e.items() if k not in ("type", "t", "note")}
            print(f"{e['t']:6.1f}  -- {e['note']}  {str(extra)[:160]}")
    recs = tour.records()
    m = recs[-1]
    print("\nstops:", out["stops"])
    for p in out["plans"]:
        print(f"plan after {p['after']}: next {p['next']} | {' / '.join(p['reasons'])}")
    print("weights:", {t: round(tour.profile.weight(t), 2) for t in tour.profile.visitors})
    print("measures:", json.dumps({k: v for k, v in m.items() if k not in ("type", "t")}, default=str)[:900])
    if a.log:
        metrics.write(metrics.anonymise(recs) if a.anon else recs, a.log)


if __name__ == "__main__":
    main()
