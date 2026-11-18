"""Draft video of the encounter replay: headless Chrome screenshots of the replay page at ?t=..., joined by ffmpeg.

    python3 -m perception.encounter_sim.video [--llm replay|fake] [--fps 10] [--out replay/s2_multi_stop_encounter.mp4]

Speeds (plan G): the encounter at 1x, stop 1 at 4x, 2x from 10 s before to 15 s after the first exclusion fix, the rest
at 8x; captions on. Needs google-chrome and ffmpeg (both already on this machine); no network. Frames go to a temp dir.
"""

from __future__ import annotations

import argparse
import concurrent.futures as cf
import os
import shutil
import subprocess
import sys
import tempfile
import threading

import make_replay

from .llm import FakeLLM, ReplayLLM
from .replay import captions, recording_path
from .run import run

SIZE = (1440, 1260)
_local = threading.local()      # one Chrome profile per worker thread: Chrome refuses a profile already in use


def schedule(records, fps):
    """Sim times of the frames: list of t."""
    t0 = min(r["t"] for r in records if r["type"] == "track")
    t_end = records[-1]["t"] if records[-1]["type"] == "measures" else max(r["t"] for r in records)
    stop2 = next((r["t"] for r in records if r["type"] == "note" and r["note"] == "transition start"), t_end)
    fix = next((r["t"] for r in sorted(records, key=lambda r: r["t"]) if r["type"] == "action"
                and r["reason"].startswith("excluded")), None)
    spans = [(t0, 0.0, 1.0), (0.0, stop2, 4.0)]
    if fix is not None and fix > stop2:
        spans += [(stop2, fix - 10, 8.0), (fix - 10, fix + 15, 2.0), (fix + 15, t_end, 8.0)]
    else:
        spans += [(stop2, t_end, 8.0)]
    ts = []
    for a, b, speed in spans:
        t = a
        while t < b:
            ts.append(round(t, 2))
            t += speed / fps
    return ts + [t_end]


def shoot(html, t, path, tmp):
    if not hasattr(_local, "profile"):
        _local.profile = tempfile.mkdtemp(prefix="prof", dir=tmp)
    profile = _local.profile
    subprocess.run(["google-chrome", "--headless=new", "--disable-gpu", "--no-first-run", f"--user-data-dir={profile}",
                    f"--window-size={SIZE[0]},{SIZE[1]}", "--hide-scrollbars",
                    "--blink-settings=preferredColorScheme=1",     # light theme in every frame (fresh profiles vary) "--virtual-time-budget=2000",
                    f"--screenshot={path}", f"file://{html}?t={t}"], capture_output=True, timeout=120, check=True,
                   # Chrome puts its singleton socket under TMPDIR; a long TMPDIR overflows the socket path and it aborts
                   env={k: v for k, v in os.environ.items() if k != "TMPDIR"})


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--llm", choices=["replay", "fake"], default="replay")
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--fps", type=int, default=10)
    ap.add_argument("--jobs", type=int, default=8)
    ap.add_argument("--out", default=os.path.join(make_replay.HERE, "replay", "s2_multi_stop_encounter.mp4"))
    a = ap.parse_args(argv)
    llm = FakeLLM() if a.llm == "fake" else ReplayLLM(recording_path("s2_multi_stop", a.seed))
    records, sim, _ = run("s2_multi_stop", llm=llm, seed=a.seed)
    records = records + captions(records)
    ts = schedule(records, a.fps)
    tmp = tempfile.mkdtemp(prefix="encounter_video_")
    try:
        html = os.path.join(tmp, "replay.html")
        with open(html, "w") as f:
            f.write(make_replay.build(records, sim))
        jobs = [(html, t, os.path.join(tmp, f"f{i:05d}.png"), tmp) for i, t in enumerate(ts)]
        with cf.ThreadPoolExecutor(a.jobs) as ex:
            for n, _ in enumerate(ex.map(lambda j: shoot(*j), jobs), 1):
                if n % 100 == 0:
                    print(f"{n}/{len(jobs)} frames", file=sys.stderr)
        os.makedirs(os.path.dirname(a.out), exist_ok=True)
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-framerate", str(a.fps), "-i", os.path.join(tmp, "f%05d.png"),
                        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "20", a.out], check=True)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    print(f"wrote {a.out}: {len(ts)} frames at {a.fps} fps = {len(ts) / a.fps:.0f} s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
