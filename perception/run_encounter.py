"""Run the initial encounter once and print (or write) its start_impression as one JSON line.

  python3 -m perception.run_encounter --source fake            # scripted, deterministic (used by the tests)
  python3 -m perception.run_encounter --source webcam [--camera 0] [--max-s 120] [--out si.json] [--show]

Exit code 0 with an impression, 1 if no engagement event happened before the frames ran out.
"""

from __future__ import annotations

import argparse
import json
import sys
import time

import numpy as np

from .age import AgeProbs, FakeAgeEstimator
from .encounter import Encounter
from .tracker import Detection

FRAME_W, FRAME_H, RATE_HZ = 640, 480, 10


class FakeCamera:
    """Three visitors walk up together and stop in front of the camera: an adult, a teenager (age band comes out
    unsure) and a child with a smaller face. Also a poster face in the background (too small: filter_faces drops it)
    and a face seen in one frame only (never passes the stable-frame gate). Seeded: same output every run."""

    PEOPLE = [  # (x centre px, face scale, emb seed, age probs); faces pass filter_faces in this order -> tracker ids
        (160, 1.00, 1, AgeProbs(0.05, 0.93, 0.02)),   # adult    -> visitor_1
        (480, 0.95, 3, AgeProbs(0.20, 0.35, 0.45)),   # teenager -> visitor_2 (unsure)
        (320, 0.80, 2, AgeProbs(0.88, 0.08, 0.04)),   # child    -> visitor_3 (smallest face, passes the filter last)
    ]
    GHOST_T = 2.5                                      # one-frame false detection -> visitor_4

    def __init__(self, seed: int = 7, duration_s: float = 15.0):
        self.rng = np.random.RandomState(seed)
        self.duration_s = duration_s
        self.embs = [self._unit(np.random.RandomState(s).randn(512)) for _, _, s, _ in self.PEOPLE]
        self.frame = np.zeros((FRAME_H, FRAME_W, 3), np.uint8)   # content unused: detections and ages are scripted
        self.t = 0.0
        self.estimator = FakeAgeEstimator({f"visitor_{i + 1}": p for i, (*_, p) in enumerate(self.PEOPLE)}
                                          | {"visitor_4": AgeProbs(0.05, 0.93, 0.02)}, noise=0.03, seed=seed)

    @staticmethod
    def _unit(v):
        return v / np.linalg.norm(v)

    def frames(self):
        for i in range(int(self.duration_s * RATE_HZ)):
            self.t = round(i / RATE_HZ, 3)
            yield self.t, self.frame

    def detect(self, frame):
        base = 50 + 80 * min(self.t / 3.0, 1.0)                  # face width grows 50 -> 130 px as they walk up
        out = []
        for (cx, scale, _, _), e in zip(self.PEOPLE, self.embs):
            w = base * scale
            h = 1.2 * w
            out.append(Detection((int(cx - w / 2), int(200 - h / 2), int(cx + w / 2), int(200 + h / 2)),
                                 self._unit(e + 0.05 * self.rng.randn(512) / np.sqrt(512))))
        out.append(Detection((590, 20, 610, 44), self._unit(self.rng.randn(512))))           # poster: 24 px high
        if self.t == self.GHOST_T:
            out.append(Detection((530, 280, 630, 400), self._unit(self.rng.randn(512))))
        return out


def webcam_frames(index: int, max_s: float):
    import cv2
    cap = cv2.VideoCapture(index)
    if not cap.isOpened():
        raise SystemExit(f"camera {index} did not open")
    t0 = time.monotonic()
    try:
        while (t := time.monotonic() - t0) < max_s:
            ok, frame = cap.read()
            if not ok:
                print(f"[{t:6.1f}s] frame read failed; stopping", file=sys.stderr)
                return
            yield t, frame
    finally:
        cap.release()


def show_live(frames, enc):
    """Wrap a (t, frame) source: after the encounter has processed each frame, draw what it sees in a window.
    Display only, nothing is written; the window closes with the run. Press q in the window to stop."""
    import cv2
    try:
        for t, frame in frames:
            yield t, frame                       # the encounter steps on this frame before we resume below
            view = frame.copy()
            for pid, r in enc.latest.items():
                x1, y1, x2, y2 = r["box"]
                ok = pid in enc.stable
                colour = (0, 200, 0) if ok else (0, 200, 255)
                cv2.rectangle(view, (x1, y1), (x2, y2), colour, 2)
                label = (f"{pid} {r['band']} {r['confidence']:.2f} ratio {(y2 - y1) / enc.frame_h:.2f} "
                         f"{'stable' if ok else 'unstable'} {enc.engagement.state(pid)}")
                cv2.putText(view, label, (x1, max(15, y1 - 8)), cv2.FONT_HERSHEY_SIMPLEX, 0.5, colour, 1)
            cv2.putText(view, f"t={t:.1f}s  enter ratio 0.20  q = stop", (10, view.shape[0] - 10),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)
            cv2.imshow("perception (live view)", view)
            if cv2.waitKey(1) & 0xFF == ord("q"):
                print(f"[{t:6.1f}s] stopped from the live view (q)", file=sys.stderr)
                return
    finally:
        cv2.destroyAllWindows()


def progress(every_s: float = 1.0):
    """on_frame callback: one status line per `every_s` to stderr (what the tracker, clusters and trigger see).
    ``on_frame.max_ratio`` keeps each visitor's highest face-box ratio over every frame (not only printed ones)."""
    last = [-1e9]

    def on_frame(t, enc, ev):
        for pid, r in enc.latest.items():
            on_frame.max_ratio[pid] = max(on_frame.max_ratio.get(pid, 0.0), (r["box"][3] - r["box"][1]) / enc.frame_h)
        on_frame.frames += 1
        if ev is None and t - last[0] < every_s:
            return
        last[0] = t
        parts = []
        for pid, r in sorted(enc.latest.items()):
            ctx = enc.groups.context(pid)
            ratio = (r["box"][3] - r["box"][1]) / enc.frame_h
            parts.append(f"{pid}:{r['band']}({r['confidence']:.2f}) streak={r['streak']} conf={r['track_conf']:.1f} "
                         f"ratio={ratio:.2f} {'stable' if pid in enc.stable else 'unstable'} "
                         f"group={ctx.group_id if ctx.status == 'known' else ctx.status + '/' + ctx.reason} "
                         f"engage={enc.engagement.state(pid)}")
        print(f"[{t:6.1f}s] fired={'yes' if ev else 'no'} {len(enc.latest)} face(s) " + " | ".join(parts), file=sys.stderr)
        if ev is not None:
            print(f"[{t:6.1f}s] ENGAGE {ev.person_ids} reason={ev.reason} group={ev.group}", file=sys.stderr)

    on_frame.max_ratio, on_frame.frames = {}, 0
    return on_frame


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Initial encounter -> one start_impression (schema v0.1)")
    ap.add_argument("--source", choices=["fake", "webcam"], required=True)
    ap.add_argument("--camera", type=int, default=0)
    ap.add_argument("--max-s", type=float, default=120.0, help="webcam: give up after this many seconds")
    ap.add_argument("--stable-frames", type=int, default=None, help="consecutive frames before a visitor counts")
    ap.add_argument("--out", help="write the JSON here instead of printing it")
    ap.add_argument("--show", action="store_true", help="webcam: live view window with boxes and states (q stops)")
    args = ap.parse_args(argv)
    kw = {} if args.stable_frames is None else {"stable_frames": args.stable_frames}

    if args.source == "fake":
        cam = FakeCamera()
        enc, frames, on_frame = Encounter(cam.estimator, cam.detect, **kw), cam.frames(), None
    else:
        from .age import FairFaceAgeEstimator
        from .faces import load_detect_and_embed
        enc = Encounter(FairFaceAgeEstimator(), load_detect_and_embed(), **kw)
        frames, on_frame = webcam_frames(args.camera, args.max_s), progress()
        if args.show:
            frames = show_live(frames, enc)

    si = enc.run(frames, on_frame)
    if on_frame:
        peaks = ", ".join(f"{p}={r:.3f}" for p, r in sorted(on_frame.max_ratio.items())) or "no face passed filter_faces"
        print(f"{on_frame.frames} frames; max face-box ratio (enter_ratio 0.20): {peaks}", file=sys.stderr)
    if si is None:
        print("no engagement event; no start_impression", file=sys.stderr)
        return 1
    line = json.dumps(si, separators=(",", ":"))
    if args.out:
        with open(args.out, "w") as f:
            f.write(line + "\n")
    else:
        print(line)
    return 0


if __name__ == "__main__":
    sys.exit(main())
