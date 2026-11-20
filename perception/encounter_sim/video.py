"""Draft video of the encounter replay: headless Chrome screenshots of the replay page at ?t=..., joined by ffmpeg.

    python3 -m perception.encounter_sim.video [--llm replay|fake] [--fps 10] [--out replay/s2_multi_stop_encounter.mp4]

The encounter ends with the small talk and a continuous walk to stop 1 (no cut; `--tour-questions` adds the LLM's two questions
about the tour before the walk). Speeds: all speech at 1x (the encounter, and each line of the tour with a second before and after); the silent stretches of the
tour at 4x. Captions on. Sound (gTTS, see audio.py) for every line: the robot's, the encounter's simulated answers and the
simulated visitors' questions in the tour. Needs google-chrome and ffmpeg (already on this machine); gTTS needs the network the
first time a line is rendered (cached after). Frames go to a temp dir.
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
from bisect import bisect_left

import make_replay

from . import audio
from .llm import FakeLLM, ReplayLLM
from .replay import captions, recording_path, with_diagram
from .run import run

SIZE = (1440, 1260)
SIZE_DIAGRAM = (1440, 1440)                 # taller page: the system diagram sits between the map and the timeline
LEAD_S, TAIL_S, QUIET_X = 1.0, 1.0, 4.0     # around each line / the speed-up between lines in the tour
_local = threading.local()      # one Chrome profile per worker thread: Chrome refuses a profile already in use


def speech_events(records):
    """[(t0, t1, text, who)] for every line shown as speech: the robot's say_to_group (encounter and tour), the encounter's simulated
    answers and the simulated visitors' questions in the tour (his scenario's own text)."""
    out = [(r["t"], r["t"] + r["duration_s"], r["args"]["text"], "robot") for r in records
           if r["type"] == "action" and r["kind"] == "say_to_group"]
    out += [(r["t"], r["t"] + r["duration_s"], r["text"], r["track_id"]) for r in records
            if r["type"] == "note" and r["note"] in ("encounter: answer", "tour: visitor said")]
    return sorted(out)


def schedule(records, fps):
    """Sim times of the frames: list of t. Speech plays at 1x (lead-in and tail around each line, so it is never cut); the encounter
    is all 1x; the rest of the tour runs at QUIET_X (speed-up of the silent stretches; 8x after stop 2 outside any speech)."""
    t0 = min(r["t"] for r in records if r["type"] == "track")
    t_end = records[-1]["t"] if records[-1]["type"] == "measures" else max(r["t"] for r in records)
    win = [(a - LEAD_S, b + TAIL_S) for a, b, _, _ in speech_events(records)]
    ts, t = [], t0
    while t < t_end:
        ts.append(round(t, 2))
        slow = t < 0 or any(a <= t <= b for a, b in win)
        t += (1.0 if slow else QUIET_X) / fps
    return ts + [t_end]


def at_1x(ts, fps, a, b):
    """Video time (s) at which sim time a falls, if [a, b] lies inside a stretch played at 1x; else None."""
    i, j = bisect_left(ts, a - 1e-6), bisect_left(ts, b - 1e-6)
    if j >= len(ts) or any(abs(ts[k + 1] - ts[k] - 1 / fps) > 0.011 for k in range(i, j)):
        return None
    return i / fps - (ts[i] - a)


def soundtrack(records, ts, fps, tmp):
    """-> (wav path, report) for every spoken line."""
    ho = next(r for r in records if r["type"] == "note" and r["note"] == "encounter: handoff")
    voice = audio.voices([(v["track_id"], v["age_class"]) for v in ho["visitors"]])
    voice["robot"] = audio.ROBOT
    events, late, skipped = [], [], 0
    for n, (a, b, text, who) in enumerate(speech_events(records)):
        off = at_1x(ts, fps, a, b)
        if off is None:
            skipped += 1
            continue
        p = os.path.join(tmp, f"s{n:03d}.wav")
        d, fits = audio.say(text, voice[who], b - a, p)
        events.append((max(off, 0.0), p))
        if not fits:
            late.append(f"{who} at {a:.1f} s: {d:.1f} s of audio for a {b - a:.1f} s slot")
    out = os.path.join(tmp, "speech.wav")
    audio.mix(events, len(ts) / fps, out)
    return out, f"{len(events)} lines with sound, {skipped} not at 1x left silent, {len(late)} too long for their slot" + "".join("; " + x for x in late)


def shoot(html, t, path, tmp, size=SIZE):
    if not hasattr(_local, "profile"):
        _local.profile = tempfile.mkdtemp(prefix="prof", dir=tmp)
    profile = _local.profile
    subprocess.run(["google-chrome", "--headless=new", "--disable-gpu", "--no-first-run", f"--user-data-dir={profile}",
                    f"--window-size={size[0]},{size[1]}", "--hide-scrollbars",
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
    ap.add_argument("--no-audio", action="store_true")
    ap.add_argument("--no-diagram", action="store_true", help="without the system diagram under the map")
    ap.add_argument("--tour-questions", action="store_true", help="the LLM's two questions about the tour between the small talk and the walk (default: walk right after the small talk)")
    ap.add_argument("--out", default=os.path.join(make_replay.HERE, "replay", "s2_multi_stop_encounter.mp4"))
    a = ap.parse_args(argv)
    llm = FakeLLM() if a.llm == "fake" or not a.tour_questions else ReplayLLM(recording_path("s2_multi_stop", a.seed))
    records, sim, _ = run("s2_multi_stop", llm=llm, seed=a.seed, tour_questions=a.tour_questions)
    records = records + captions(records)
    ts = schedule(records, a.fps)
    tmp = tempfile.mkdtemp(prefix="encounter_video_")
    try:
        html = os.path.join(tmp, "replay.html")
        with open(html, "w") as f:
            page = make_replay.build(records, sim)
            f.write(page if a.no_diagram else with_diagram(page))
        jobs = [(html, t, os.path.join(tmp, f"f{i:05d}.png"), tmp,
                 SIZE if a.no_diagram else SIZE_DIAGRAM) for i, t in enumerate(ts)]
        with cf.ThreadPoolExecutor(a.jobs) as ex:
            for n, _ in enumerate(ex.map(lambda j: shoot(*j), jobs), 1):
                if n % 100 == 0:
                    print(f"{n}/{len(jobs)} frames", file=sys.stderr)
        os.makedirs(os.path.dirname(a.out), exist_ok=True)
        wav, report = (None, "no sound") if a.no_audio else soundtrack(records, ts, a.fps, tmp)
        print(report, file=sys.stderr)
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-framerate", str(a.fps), "-i", os.path.join(tmp, "f%05d.png"),
                        *([] if wav is None else ["-i", wav, "-c:a", "aac", "-b:a", "128k", "-shortest"]),
                        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "20", a.out], check=True)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    print(f"wrote {a.out}: {len(ts)} frames at {a.fps} fps = {len(ts) / a.fps:.0f} s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
