"""Score the signal layer against a scenario's ground-truth labels.

    python3 eval_signals.py                 # all scenarios
    python3 eval_signals.py s1_one_stop -v  # one scenario, list every event with its reason

Matching: a detected event matches a label of the same kind and visitor if their intervals
overlap, allowing TOL seconds either side. Each label and each detection matches at most once
(greedy, largest overlap first). Unmatched detections are false positives (fragments of an
already-matched label count as false positives too).
Latency = detection time - label start, for matched labels.
"""
import argparse, json, os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from sdc import adapter, scenarios
from sdc.signals import SignalLayer

KINDS = ["linger", "approach", "point_ask", "drift", "fatigue", "bid", "barrier", "excluded"]
TOL = 5.0


def detect(name):
    path = os.path.join(HERE, "data", f"{name}.jsonl")
    if not os.path.exists(path):
        sys.exit(f"{path} missing: run python3 make_mock.py")
    gallery = json.load(open(os.path.join(HERE, "data", "gallery.json")))
    layer = SignalLayer(gallery, stop=scenarios.ALL[name]().stop)
    return layer.run(adapter.read(path))


def match(events, labels, tol=TOL):
    """Returns (pairs [(label, event)], unmatched events, unmatched labels)."""
    cands = []
    for li, l in enumerate(labels):
        for ei, e in enumerate(events):
            if e.kind != l["kind"] or e.track_id != l["track_id"]:
                continue
            ov = min(e.t1, l["t1"] + tol) - max(e.t_detect, l["t0"] - tol)
            if ov >= 0:
                cands.append((ov, li, ei))
    cands.sort(reverse=True)
    used_l, used_e, pairs = set(), set(), []
    for ov, li, ei in cands:
        if li in used_l or ei in used_e:
            continue
        used_l.add(li); used_e.add(ei)
        pairs.append((labels[li], events[ei]))
    return (pairs, [e for i, e in enumerate(events) if i not in used_e],
            [l for i, l in enumerate(labels) if i not in used_l])


def evaluate(events, labels, tol=TOL):
    quiet = {l["track_id"] for l in labels if l["kind"] == "expect_no_events"}
    labels = [l for l in labels if l["kind"] != "expect_no_events"]
    pairs, fp, fn = match(events, labels, tol)
    rows = {}
    for k in KINDS:
        n_det = sum(1 for e in events if e.kind == k)
        n_lab = sum(1 for l in labels if l["kind"] == k)
        tp = [(l, e) for l, e in pairs if l["kind"] == k]
        lat = [e.t_detect - l["t0"] for l, e in tp]
        rows[k] = {"labels": n_lab, "detected": n_det, "tp": len(tp),
                   "precision": len(tp) / n_det if n_det else None,
                   "recall": len(tp) / n_lab if n_lab else None,
                   "latency_mean": sum(lat) / len(lat) if lat else None,
                   "latency_max": max(lat) if lat else None}
    quiet_events = [e for e in events if e.track_id in quiet]
    return {"rows": rows, "pairs": pairs, "fp": fp, "fn": fn, "quiet": quiet, "quiet_events": quiet_events}


def _f(x, pct=False):
    if x is None:
        return "  -  "
    return f"{x:5.0%}" if pct else f"{x:5.1f}"


def report(name, res, verbose=False):
    print(f"\n== {name}  (tolerance ±{TOL:.0f}s)")
    print(f"{'kind':<10} {'labels':>6} {'det':>4} {'tp':>3} {'prec':>6} {'recall':>6} {'lat_mean':>8} {'lat_max':>7}")
    for k, r in res["rows"].items():
        print(f"{k:<10} {r['labels']:>6} {r['detected']:>4} {r['tp']:>3} {_f(r['precision'], 1):>6} "
              f"{_f(r['recall'], 1):>6} {_f(r['latency_mean']):>8} {_f(r['latency_max']):>7}")
    for tid in sorted(res["quiet"]):
        n = sum(1 for e in res["quiet_events"] if e.track_id == tid)
        print(f"expect_no_events {tid}: {n} events {'OK' if n == 0 else 'FAIL'}")
    if res["fp"]:
        print("false positives:")
        for e in res["fp"]:
            print(f"  {e.track_id} {e.kind:<9} {e.t_detect:6.1f}-{e.t1:6.1f}  {e.reason}")
    if res["fn"]:
        print("missed labels:")
        for l in res["fn"]:
            print(f"  {l['track_id']} {l['kind']:<9} {l['t0']}-{l['t1']}")
    if verbose:
        print("matched:")
        for l, e in sorted(res["pairs"], key=lambda p: (p[1].track_id, p[1].t_detect)):
            print(f"  {e.track_id} {e.kind:<9} label {l['t0']}-{l['t1']}  det {e.t_detect:.1f}-{e.t1:.1f} "
                  f"(evidence from {e.t0:.1f})  {e.reason}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("scenarios", nargs="*", default=list(scenarios.ALL))
    ap.add_argument("-v", "--verbose", action="store_true")
    a = ap.parse_args()
    for name in a.scenarios:
        labels = json.load(open(os.path.join(HERE, "data", f"{name}.labels.json")))["labels"]
        report(name, evaluate(detect(name), labels), a.verbose)


if __name__ == "__main__":
    main()
