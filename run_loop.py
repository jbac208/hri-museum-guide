"""Run the processing loop on a mock scenario and print the action log.

    python3 run_loop.py                 # s1_one_stop, actions + notes, no gaze balancing
    python3 run_loop.py --all           # include gaze balancing
    python3 run_loop.py --json out.json # also write the full log
"""
import argparse, json, os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from sdc import adapter, scenarios
from sdc.loop import Loop


def run(name):
    gallery = json.load(open(os.path.join(HERE, "data", "gallery.json")))
    scn = scenarios.ALL[name]()
    path = os.path.join(HERE, "data", f"{name}.jsonl")
    if not os.path.exists(path):
        sys.exit(f"{path} missing: run python3 make_mock.py")
    loop = Loop(gallery, scn.stop, scn.duration_s, scenario=scn.name)
    out = loop.run(adapter.read(path))
    return loop, out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("scenario", nargs="?", default="s1_one_stop")
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--json")
    ap.add_argument("--log", help="write the event log (JSONL, tracks + events) here")
    ap.add_argument("--anon", action="store_true", help="anonymise ids in the written log")
    a = ap.parse_args()
    loop, out = run(a.scenario)
    for e in sorted(loop.ctrl.log, key=lambda e: e["t"]):
        if e["type"] == "action":
            if not a.all and e["reason"].startswith(("gaze balancing", "cue word")):
                continue
            arg = e["args"].get("text") or e["args"]
            if isinstance(arg, str) and len(arg) > 60:
                arg = arg[:57] + "..."
            print(f"{e['t']:6.1f}  {e['kind']:<12} {str(arg):<62} <- {e['reason']}")
        else:
            extra = {k: v for k, v in e.items() if k not in ("type", "t", "note")}
            print(f"{e['t']:6.1f}  -- {e['note']}  {extra}")
    print("\nlayers:")
    for l in loop.profile.layers():
        print(f"  {l.track_id} {l.kind:<17} {l.target:<20} {l.status:<9} conf {l.confidence:.2f}")
    print("credit:", {t: v.credit for t, v in loop.profile.visitors.items()})
    print("plan:", json.dumps(out["plan"], indent=1))
    recs = loop.records()
    m = recs[-1]
    print("\nmeasures:")
    print(f"  steering uptake  {m['steering_uptake']['acted_on']}/{m['steering_uptake']['detected']}"
          f" = {m['steering_uptake']['share']}")
    print(f"  exclusion        {m['exclusion']['episodes']} episodes, {m['exclusion']['resolved']} resolved, "
          f"time to resolve {m['exclusion']['time_to_resolve_s']}")
    print(f"  misread rate     {m['misread_rate']['rescinded']}/{m['misread_rate']['tested']} = {m['misread_rate']['rate']}")
    print(f"  dominance share  {m['dominance_share']['top_visitor']} {m['dominance_share']['share']} "
          f"{m['dominance_share']['acted_per_visitor']}")
    print(f"  P13 unresolved   {m['p13_unresolved']['share']} {m['p13_unresolved']['visitors_with_unresolved']}")
    if a.log:
        from sdc import metrics
        metrics.write(metrics.anonymise(recs) if a.anon else recs, a.log)
    if a.json:
        json.dump({"log": loop.ctrl.log, "profile": loop.profile.log, **out}, open(a.json, "w"), indent=1)


if __name__ == "__main__":
    main()
