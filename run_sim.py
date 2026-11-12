"""Run the processing loop closed-loop against the visitor sim and print what happened.

    python3 run_sim.py                  # s1_closed
    python3 run_sim.py --all            # include gaze balancing and cue gazes
    python3 run_sim.py --stream out.jsonl --json log.json
"""
import argparse, json, os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from sdc import scenarios
from sdc.loop import Loop
from sdc.sim import run_closed_loop, write_stream

GALLERY = json.load(open(os.path.join(HERE, "data", "gallery.json")))


def run(name="s1_closed", spec=None):
    spec = spec or scenarios.SIM[name]()
    return run_closed_loop(spec, GALLERY, lambda scn: Loop(GALLERY, scn.stop, scn.duration_s, scenario=scn.name))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("scenario", nargs="?", default="s1_closed")
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--stream")
    ap.add_argument("--json")
    ap.add_argument("--log", help="write the event log (JSONL, tracks + events) here")
    ap.add_argument("--anon", action="store_true", help="anonymise ids in the written log")
    a = ap.parse_args()
    loop, sim, lines, out = run(a.scenario)
    rows = [dict(e, src="robot") for e in loop.ctrl.log] + [dict(r, type="sim", src="sim") for r in sim.reactions]
    for e in sorted(rows, key=lambda e: e["t"]):
        if e["type"] == "action":
            if not a.all and e["reason"].startswith(("gaze balancing", "cue word")):
                continue
            arg = e["args"].get("text") or e["args"]
            if isinstance(arg, str) and len(arg) > 55:
                arg = arg[:52] + "..."
            print(f"{e['t']:6.1f}  {e['kind']:<12} {str(arg):<56} <- {e['reason']}")
        elif e["type"] == "sim":
            print(f"{e['t']:6.1f}  [sim] {e['track_id']} {e['reaction']}")
        else:
            extra = {k: v for k, v in e.items() if k not in ("type", "t", "note", "src")}
            print(f"{e['t']:6.1f}  -- {e['note']}  {extra}")
    print("\nlayers:")
    for l in loop.profile.layers():
        print(f"  {l.track_id} {l.kind:<17} {l.target:<20} {l.status:<9} conf {l.confidence:.2f}")
    print("credit:", {t: v.credit for t, v in loop.profile.visitors.items()})
    print("weights:", {t: round(loop.profile.weight(t), 2) for t in loop.profile.visitors})
    print("plan:", out["plan"]["next"], "|", " / ".join(out["plan"]["reasons"]))
    if a.stream:
        write_stream(lines, a.stream)
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
        json.dump({"log": loop.ctrl.log, "sim": sim.reactions, "profile": loop.profile.log, **out},
                  open(a.json, "w"), indent=1)


if __name__ == "__main__":
    main()
