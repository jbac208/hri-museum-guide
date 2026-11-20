"""Draft 1-minute video for the HRI submission: the shots in perception/HRI_VIDEO_PLAN.md, a TTS voice-over (gTTS, one narrator
voice), the system diagram on, the voice-over as subtitles in the caption bar. The simulated speech is not voiced (the panel
shows it); each shot runs at the speed that makes it as long as its narration.

    python3 -m perception.encounter_sim.short [--out replay/hri_short_draft.mp4]
"""

from __future__ import annotations

import argparse
import concurrent.futures as cf
import os
import shutil
import subprocess
import sys
import tempfile

import make_replay

from . import audio
from .llm import FakeLLM
from .replay import with_diagram
from .run import run
from .video import SIZE_DIAGRAM, shoot

NARRATOR = ("co.za", 1.0)        # an accent no one in the scene has
GAP_S = 0.8                      # silence after each narration line before the next shot

# (sim ranges, narration): seed 1, no tour questions; times from that run (see HRI_VIDEO_PLAN.md)
SHOTS = [
    ([(-113.6, -95.4)], "This is a simulation. Visitors arrive, and our perception gives each one an ID, estimates child or adult, "
                        "and groups companions by who arrives and moves together."),
    ([(-95.4, -88.5)], "When every group has settled, the robot greets everyone at once. It always speaks to the whole group."),
    ([(-36.5, -23.0)], "A little small talk builds a first profile. One visitor names the compass, and that becomes a guess, not a fact."),
    ([(-18.7, 0.0)], "The robot leads the group to the first exhibit and hands this first impression to the tour."),
    ([(57.0, 61.0), (75.0, 81.0), (94.0, 97.0)],
     "During the tour it watches behaviour. One visitor keeps looking at the ship model, so the robot offers a link to it. "
     "The visitor looks, and the guess is confirmed."),
    ([(158.0, 166.0)], "When the child is stuck behind the group, the robot opens the formation for them."),
    ([(251.0, 261.0)], "At a choice of exhibits, it offers two, and follows where the group turns."),
]


def frames(ranges, length_s, fps):
    """Sim times for one shot: its ranges played back to back, stretched or squeezed to length_s."""
    span = sum(b - a for a, b in ranges)
    n = max(1, round(length_s * fps))
    out = []
    for k in range(n):
        x = k * span / n
        for a, b in ranges:
            if x < b - a or (a, b) == ranges[-1]:
                out.append(round(a + min(x, b - a), 2))
                break
            x -= b - a
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--fps", type=int, default=10)
    ap.add_argument("--jobs", type=int, default=8)
    ap.add_argument("--out", default=os.path.join(make_replay.HERE, "replay", "hri_short_draft.mp4"))
    a = ap.parse_args(argv)
    records, sim, _ = run("s2_multi_stop", llm=FakeLLM(), seed=1, tour_questions=False)      # no LLM call
    tmp = tempfile.mkdtemp(prefix="hri_short_")
    try:
        ts, events, plan = [], [], []
        for i, (ranges, text) in enumerate(SHOTS):
            wav = os.path.join(tmp, f"n{i}.wav")
            d, _ = audio.say(text, NARRATOR, 99.0, wav)                                      # natural speed
            events.append((len(ts) / a.fps, wav))
            shot = frames(ranges, d + GAP_S, a.fps)
            plan.append(f"shot {i + 1}: sim {ranges[0][0]}..{ranges[-1][1]} s, {len(shot) / a.fps:.1f} s, "
                        f"{sum(b - x for x, b in ranges) / (len(shot) / a.fps):.1f}x")
            ts += shot
        subs = [{"type": "note", "t": ranges[0][0], "note": "caption", "text": text} for ranges, text in SHOTS]
        html = os.path.join(tmp, "replay.html")
        with open(html, "w") as f:
            f.write(with_diagram(make_replay.build(records + subs, sim)))
        jobs = [(html, t, os.path.join(tmp, f"f{i:05d}.png"), tmp, SIZE_DIAGRAM) for i, t in enumerate(ts)]
        with cf.ThreadPoolExecutor(a.jobs) as ex:
            list(ex.map(lambda j: shoot(*j), jobs))
        speech = os.path.join(tmp, "speech.wav")
        audio.mix(events, len(ts) / a.fps, speech)
        os.makedirs(os.path.dirname(a.out), exist_ok=True)
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-framerate", str(a.fps), "-i", os.path.join(tmp, "f%05d.png"),
                        "-i", speech, "-c:a", "aac", "-b:a", "128k", "-shortest",
                        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "20", a.out], check=True)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    print("\n".join(plan), file=sys.stderr)
    print(f"wrote {a.out}: {len(ts)} frames at {a.fps} fps = {len(ts) / a.fps:.0f} s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
