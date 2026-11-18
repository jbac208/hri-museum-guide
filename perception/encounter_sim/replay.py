"""Tour replay WITH the encounter phase (wraps Joey's make_replay.build; his script is not edited).

    python3 -m perception.encounter_sim.replay                      # s2_multi_stop, recorded LLM run -> replay/s2_multi_stop_encounter.html
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
    """Caption notes for the video, timed from the run's own records."""
    acts = [r for r in records if r["type"] == "action"]
    notes = [r for r in records if r["type"] == "note"]
    first = lambda pred, rs: next((r["t"] for r in sorted(rs, key=lambda r: r["t"]) if pred(r)), None)
    t0 = min(r["t"] for r in records if r["type"] == "track")
    t_end = max(r["t"] for r in records)
    fix = first(lambda a: a["reason"].startswith("excluded"), acts)
    out = [
        (t0, "Simulation. Six visitors arrive. Our perception tracks each one and groups companions by how they "
             "move together."),
        (first(lambda a: a["args"].get("id") == "encounter.greet", acts) - 1.0,
         "The group has gathered in front of the robot: the encounter starts, and the robot greets everyone at once."),
        (first(lambda a: str(a["args"].get("id", "")).startswith("encounter.q."), acts),
         "Two short questions to the whole group. An LLM picks the next question from a fixed menu and turns answers "
         "into small guesses; fixed rules check every guess. Nobody is asked by name; quiet visitors are left alone."),
        (first(lambda a: a["args"].get("id") == "encounter.ack", acts),
         "The robot's first impression: who is together, a child/adult estimate that is never spoken, and what "
         "people said they'd like."),
        (0.0, "The tour starts. Each guess is tested by the robot's offers and dropped if nobody responds."),
        (fix - 3.0 if fix is not None else None,
         "The child is behind their parent and trying to join: the robot opens the formation for them."),
        (t_end - 15.0, "Simulated visitors; real perception and decision code. No camera images or audio were used."),
    ]
    return [{"type": "note", "t": round(t, 2), "note": "caption", "text": text} for t, text in out if t is not None]


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("scenario", nargs="?", default="s2_multi_stop")
    ap.add_argument("--llm", choices=["replay", "fake", "record"], default="replay")
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--captions", action="store_true")
    ap.add_argument("--no-layers", action="store_true")
    ap.add_argument("--out")
    a = ap.parse_args(argv)
    path = recording_path(a.scenario, a.seed)
    if a.llm == "fake":
        llm = FakeLLM()
    elif a.llm == "record":
        os.makedirs(RECORDED, exist_ok=True)
        llm = RecordingLLM(OllamaLLM(MODEL), path)
    else:
        if not os.path.exists(path):
            sys.exit(f"no recording at {path}: use --llm fake, or --llm record (calls local Ollama)")
        llm = ReplayLLM(path)
    records, sim, info = run(a.scenario, llm=llm, seed=a.seed, pending=not a.no_layers)
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
