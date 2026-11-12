"""Build the replay visualiser: one self-contained HTML file (no network, no dependencies).

    python3 make_replay.py                      # s1_closed (closed-loop sim) -> replay/s1_closed.html
    python3 make_replay.py s1_one_stop          # open loop on the mock stream
    python3 make_replay.py --log out.jsonl      # from a saved event log (run_sim.py --log)
    python3 make_replay.py --anon               # anonymised ids (P1.., G1..)

Open the HTML in a browser. Space = play/pause, arrows = step, ?t=72 in the URL starts at 72 s.
"Export map" downloads the map at the current moment as SVG (for the paper figure).
"""
import argparse, json, os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from sdc import metrics, scenarios

GALLERY = json.load(open(os.path.join(HERE, "data", "gallery.json")))
TEMPLATE = os.path.join(HERE, "viz", "replay_template.html")


def records_for(name):
    """(records, sim reactions) for a scenario name: SIM scenarios run closed loop, ALL open loop."""
    if name in scenarios.SIM:
        import run_sim
        loop, sim, _, _ = run_sim.run(name)
        return loop.records(), sim.reactions
    if name in scenarios.ALL:
        import run_loop
        loop, _ = run_loop.run(name)
        return loop.records(), []
    sys.exit(f"unknown scenario {name}; choose from {sorted(scenarios.SIM) + sorted(scenarios.ALL)}")


def build(records, sim=(), gallery=GALLERY):
    by = {}
    for r in records:
        by.setdefault(r["type"], []).append(r)
    data = {
        "meta": by["meta"][0],
        "gallery": gallery,
        "tracks": by.get("track", []),
        "events": by.get("event", []),
        "actions": by.get("action", []),
        "notes": by.get("note", []),
        "profile": by.get("profile", []),
        "measures": by["measures"][-1],
        "sim": list(sim),
    }
    blob = json.dumps(data, separators=(",", ":"), ensure_ascii=False).replace("</", "<\\/")
    html = open(TEMPLATE).read()
    assert "/*DATA*/null" in html
    return html.replace("/*DATA*/null", blob)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("scenario", nargs="?", default="s1_closed")
    ap.add_argument("--log", help="build from a saved event log instead of running a scenario")
    ap.add_argument("--anon", action="store_true")
    ap.add_argument("--out")
    a = ap.parse_args()
    if a.log:
        records, sim = [json.loads(l) for l in open(a.log)], []
        name = records[0].get("scenario", "replay")
    else:
        records, sim = records_for(a.scenario)
        name = a.scenario
    if a.anon:
        records = metrics.anonymise(records)
        sim = metrics.anonymise([dict(r, type="sim") for r in sim]) if sim else []
    out = a.out or os.path.join(HERE, "replay", f"{name}.html")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, "w") as f:
        f.write(build(records, sim))
    print(f"wrote {out} ({os.path.getsize(out) // 1024} KB)")


if __name__ == "__main__":
    main()
