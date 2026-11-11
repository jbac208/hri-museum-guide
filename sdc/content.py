"""Content library (block 6): curated per-exhibit core script, additions and constrained Q&A.

Files: data/content/<exhibit>.json. Hand-written; no live LLM. Each exhibit has
  core          the shared script, in segments, with gaze/gesture cues on key words (Yamazaki 2009)
  open_question one open question to the whole group (D2)
  additions     4-6 short add-ons, each tagged by type (detail / depth / neighbour) and by the
                profile layers it serves ({kind, target}); s_i(a) in the addition score reads `serves`
  qa            canned answers matched by keywords; qa_fallback when nothing matches

All text addresses the group (D7): validate() rejects phrases that single out one visitor.
Additions only ever add to the core, never replace it.
"""
import json
import os
import re
from dataclasses import dataclass, field

from . import config as C

TYPES = {"detail", "depth", "neighbour"}
LAYER_KINDS = {"feature_interest", "depth", "exhibit_interest"}
SINGLING_OUT = re.compile(
    r"\b(you there|you over there|your (child|son|daughter|kid|husband|wife|partner)|sir|madam|"
    r"young (man|lady)|little one|the (boy|girl|child) (here|there)|\{name\})\b", re.I)
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONTENT_DIR = os.path.join(HERE, "data", "content")


def speech_s(text):
    """Estimated speaking time (TTS_WORDS_PER_S)."""
    return len(text.split()) / C.TTS_WORDS_PER_S


@dataclass
class Segment:
    id: str
    text: str
    cues: list = field(default_factory=list)      # [{word, look, gesture?}]

    @property
    def duration_s(self):
        return speech_s(self.text)

    def cue_times(self):
        """[(seconds into the segment, cue)] for each cue word (first occurrence)."""
        words = [w.strip(".,:;!?").lower() for w in self.text.split()]
        out = []
        for c in self.cues:
            i = words.index(c["word"].lower())
            out.append((i / C.TTS_WORDS_PER_S, c))
        return out


@dataclass
class Addition:
    id: str
    exhibit: str
    type: str
    feature: str | None
    text: str
    serves: list                                  # [{kind, target}]
    look: str

    @property
    def duration_s(self):
        return speech_s(self.text)

    def serves_layer(self, kind, target):
        return any(s["kind"] == kind and s["target"] == target for s in self.serves)


@dataclass
class Exhibit:
    id: str
    core: list
    open_question: dict
    additions: list
    qa: list
    qa_fallback: dict

    def addition(self, aid):
        return next(a for a in self.additions if a.id == aid)

    def answer(self, question):
        """Most specific keyword match (longest keyword) wins; fallback otherwise. Returns a qa dict."""
        q = question.lower()
        best, best_len = None, 0
        for entry in self.qa:
            for kw in entry["match"]:
                if kw in q and len(kw) > best_len:
                    best, best_len = entry, len(kw)
        return best or {"id": f"{self.id}.qa.fallback", **self.qa_fallback}


def load(exhibit, content_dir=CONTENT_DIR):
    d = json.load(open(os.path.join(content_dir, f"{exhibit}.json")))
    return Exhibit(
        d["exhibit"],
        [Segment(s["id"], s["text"], s.get("cues", [])) for s in d["core"]],
        d["open_question"],
        [Addition(a["id"], d["exhibit"], a["type"], a.get("feature"), a["text"], a["serves"], a["look"])
         for a in d["additions"]],
        d["qa"],
        d["qa_fallback"],
    )


def load_all(gallery, content_dir=CONTENT_DIR):
    return {e["id"]: load(e["id"], content_dir) for e in gallery["exhibits"]}


def validate(ex, gallery):
    """Raise ValueError on any problem. Checks ids against the gallery and D7 wording."""
    exhibits = {e["id"]: {f["id"] for f in e["features"]} for e in gallery["exhibits"]}
    features = set().union(*exhibits.values())
    looks = {"robot"} | {f"exhibit:{e}" for e in exhibits} | {f"feature:{f}" for f in features}

    def bad(msg):
        raise ValueError(f"{ex.id}: {msg}")

    if ex.id not in exhibits:
        bad("not in gallery")
    if not 4 <= len(ex.additions) <= 6:
        bad(f"{len(ex.additions)} additions, want 4-6")
    texts = [(s.id, s.text) for s in ex.core] + [("open_question", ex.open_question["text"])] + \
            [(a.id, a.text) for a in ex.additions] + [(q["id"], q["text"]) for q in ex.qa] + \
            [("qa_fallback", ex.qa_fallback["text"])]
    for tid, text in texts:
        if SINGLING_OUT.search(text):
            bad(f"{tid} singles out a visitor (D7): {SINGLING_OUT.search(text).group(0)!r}")
    for s in ex.core:
        for c in s.cues:
            if c["look"] not in looks:
                bad(f"{s.id} cue looks at unknown {c['look']}")
        try:
            s.cue_times()
        except ValueError:
            bad(f"{s.id} cue word not in text")
    ids = [a.id for a in ex.additions]
    if len(set(ids)) != len(ids):
        bad("duplicate addition id")
    for a in ex.additions:
        if a.type not in TYPES:
            bad(f"{a.id} bad type {a.type}")
        if a.feature is not None and a.feature not in exhibits[ex.id]:
            bad(f"{a.id} feature {a.feature} not on this exhibit")
        if a.look not in looks:
            bad(f"{a.id} looks at unknown {a.look}")
        if not a.serves:
            bad(f"{a.id} serves no layer")
        for s in a.serves:
            if s["kind"] not in LAYER_KINDS:
                bad(f"{a.id} serves unknown kind {s['kind']}")
            ok = s["target"] in (features if s["kind"] == "feature_interest" else exhibits)
            if not ok:
                bad(f"{a.id} serves unknown target {s['target']}")
        if a.type == "neighbour" and not any(s["kind"] == "exhibit_interest" and s["target"] != ex.id
                                             for s in a.serves):
            bad(f"{a.id} neighbour addition must serve interest in another exhibit")
    for q in ex.qa + [ex.qa_fallback]:
        if q["look"] not in looks:
            bad(f"qa looks at unknown {q['look']}")
    return True
