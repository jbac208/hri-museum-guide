"""Tour replay WITH the encounter phase (wraps Joey's make_replay.build; his script is not edited).

    python3 -m perception.encounter_sim.replay                      # s2_multi_stop: small talk, then the walk to stop 1 -> replay/s2_multi_stop_encounter.html
    python3 -m perception.encounter_sim.replay --tour-questions     # plus the LLM's two questions about the tour (recorded LLM run)
    python3 -m perception.encounter_sim.replay --llm fake           # deterministic stand-in, no LLM at all
    python3 -m perception.encounter_sim.replay --llm record         # call local Ollama once and record its outputs (asks the network)
    python3 -m perception.encounter_sim.replay --captions           # add the video captions (G in perception/ENCOUNTER_PLAN.md)
    python3 -m perception.encounter_sim.replay --no-layers          # hand over without the conversation's pending layers

Open the HTML as usual; without ?t= it starts at the beginning of the encounter (negative time).
"""

from __future__ import annotations

import argparse
import os
import sys

import make_replay                                   # Joey's root script: build(), HERE

from .llm import FakeLLM, OllamaLLM, RecordingLLM, ReplayLLM
from .run import run

RECORDED = os.path.join(os.path.dirname(os.path.abspath(__file__)), "recorded")
MODEL = "qwen2.5:7b"


def recording_path(name, seed, model=MODEL):
    return os.path.join(RECORDED, f"{name}_seed{seed}_{model.replace(':', '-')}.jsonl")


def captions(records):
    """Caption notes for the video, timed from the run's own records. Without the tour questions (run(tour_questions=False)) their captions go."""
    acts = [r for r in records if r["type"] == "action"]
    notes = [r for r in records if r["type"] == "note"]
    first = lambda pred, rs: next((r["t"] for r in sorted(rs, key=lambda r: r["t"]) if pred(r)), None)
    t0 = min(r["t"] for r in records if r["type"] == "track")
    t_end = max(r["t"] for r in records)
    fix = first(lambda a: a["reason"].startswith("excluded"), acts)
    out = [
        (t0, "Simulation. Six visitors walk into the reception, one after another. Our perception tracks each one and works "
             "out companion groups step by step, from who arrives together and keeps close and moves together."),
        (first(lambda a: a["args"].get("id") == "encounter.greet", acts) - 1.0,
         "Everyone has arrived and every group is settled: the robot turns to the group and greets everyone at once."),
        (first(lambda a: a["args"].get("id") == "encounter.intro", acts),
         "A short get-to-know-you chat, all said to the group: a welcome and an introduction, then three easy questions "
         "(been on a museum tour before? how is your day? a favourite exhibit?). Nobody is asked by name; quiet visitors "
         "are left alone."),
        (first(lambda a: str(a["args"].get("id", "")).startswith("encounter.q."), acts),
         "Two questions about this tour. An LLM picks the next one from a fixed menu and turns answers into small guesses; "
         "fixed rules check every guess. What is said becomes the first assumptions in each visitor's profile."),
        (first(lambda a: a["args"].get("id") == "encounter.ack", acts),
         "The robot's first impression: who is together, a child/adult estimate that is never spoken, and what "
         "people said they'd like."),
        (first(lambda a: a["args"].get("id") == "encounter.lead", acts) - 0.5,
         "The robot invites the group to the first exhibit and walks there; the visitors follow."),
        (0.0, "The tour starts, and the same profile keeps being updated: each guess is tested by the robot's offers, confirmed or "
              "dropped, and new guesses are added from what visitors do and ask."),
        (fix - 3.0 if fix is not None else None,
         "The child is behind their parent and trying to join: the robot opens the formation for them."),
        (t_end - 15.0, "Simulated visitors; real perception and decision code. The voices are synthesised; no camera images or microphone audio were used."),
    ]
    return [{"type": "note", "t": round(t, 2), "note": "caption", "text": text} for t, text in out if t is not None]


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("scenario", nargs="?", default="s2_multi_stop")
    ap.add_argument("--llm", choices=["replay", "fake", "record"], default="replay")
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--captions", action="store_true")
    ap.add_argument("--tour-questions", action="store_true", help="the LLM's two questions about the tour before the walk")
    ap.add_argument("--no-layers", action="store_true")
    ap.add_argument("--out")
    a = ap.parse_args(argv)
    path = recording_path(a.scenario, a.seed)
    if a.llm == "fake" or (a.llm == "replay" and not a.tour_questions):     # no tour questions: the LLM is not called at all
        llm = FakeLLM()
    elif a.llm == "record":
        os.makedirs(RECORDED, exist_ok=True)
        llm = RecordingLLM(OllamaLLM(MODEL), path)
    else:
        if not os.path.exists(path):
            sys.exit(f"no recording at {path}: use --llm fake, or --llm record (calls local Ollama)")
        llm = ReplayLLM(path)
    records, sim, info = run(a.scenario, llm=llm, seed=a.seed, pending=not a.no_layers, tour_questions=a.tour_questions)
    if a.captions:
        records = records + captions(records)
    out = a.out or os.path.join(make_replay.HERE, "replay", f"{a.scenario}_encounter.html")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, "w") as f:
        f.write(make_replay.build(records, sim))
    print(f"wrote {out} ({os.path.getsize(out) // 1024} KB); encounter {info['t_encounter_s']} s, LLM {info['llm_model']}, "
          f"asked {info['asked']}, layers {info['layers']}")
    if a.llm == "record":
        print(f"recorded LLM outputs: {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
