"""The first conversation with the group: the LLM proposes, this code decides. No LLM import here; `llm` is any
fn(system, user) -> str (perception/encounter_sim/llm.py).

Robot speech comes ONLY from MENU text (all to the group, D7; linted with Joey's content.SINGLING_OUT). The robot never
names anyone, never asks one visitor, never follows up with someone who stayed quiet, never mentions age or looks (D2,
D4, D7): there is no code path that could. Silence creates no evidence.

Selection: code computes the allowed question ids (BUDGET, choice before open, no repeats); the LLM picks one of them or
"none"; anything else (bad JSON, an id not allowed) -> the first allowed id in menu order, logged as "fallback".
Extraction (guard ported from Jay's frozen modules/museum/profile_extraction.py): parse/shape failure -> the whole answer
is dropped; per item, (kind, target) must be one of THIS question's options, confidence >= CONFIDENCE_MIN, `quote` must
occur verbatim in the answer AND name the option (one of its cues: its name, its id, a listed paraphrase), else that item
is dropped whole (never repaired); at most MAX_ITEMS per answer. The cue check was added after the first real-LLM run
(qwen2.5:7b) put "Short is fine." into the only depth option, "the full story", with a verbatim quote.
Joey's profile store loads every surviving item as a pending layer at SEED_LAYER_CONF, so the LLM's confidence only gates.
"""

from __future__ import annotations

import json
from dataclasses import dataclass

from sdc.content import LAYER_KINDS, SINGLING_OUT

BUDGET = 2
CONFIDENCE_MIN = 0.6          # from Jay's frozen modules/kg_extraction.py; untuned placeholder
MAX_ITEMS = 2
GREETING = "Hello, everyone, and welcome! I'll be your guide on your museum tour today."   # the frozen neutral_group row, reworded ("around the gallery") at Jay's request
INTRO = "I'm the guide robot for your museum tour, and I'll take you round a few of our exhibits."
ACK = "Thank you, that helps."
LEAD = "Let's head over to the {}. Please follow me."      # {} = the first exhibit's name


# Icebreakers: a fixed script before the LLM's questions (no LLM call: the LLM prompts, and so the recorded run, stay as they were).
# Said to the group (D7). Each reaction fits any answer: the robot never judges how someone's day is going (no mood inference) nor
# says who has been before. What the answers give: ice_visit -> a per-visitor "prior tour" fact (keywords, closed set); ice_day -> nothing
# (rapport only); ice_fav -> pending exhibit_interest layers, through the same name check as the LLM's items.
ICE_VISIT = "Before we start: have any of you been on a museum tour before?"
ICE_DAY = "And how is your day going so far?"
ICE_FAV = "Do you have a favourite exhibit in this museum, or have you seen any of them before?"
ICE_REACT = {"ice_visit": "Lovely. Whether it's your first tour or your fifth, I hope you find something new today.",
             "ice_day": "Thank you for sharing. I hope the tour adds something to it.",
             "ice_fav": "Thank you, I'll keep that in mind."}
ICE = (("ice_visit", ICE_VISIT), ("ice_day", ICE_DAY), ("ice_fav", ICE_FAV))


def prior_tour(text):
    """'yes' / 'no' / None from a closed set of keywords on the answer to ICE_VISIT (None = unclear: nothing stored)."""
    low = text.lower()
    if any(w in low for w in ("first", "never", "no,", "no.", "not yet")):
        return "no"
    if any(w in low for w in ("yes", "a few", "been on", "before", "once", "twice")):
        return "yes"
    return None


def favourite(gallery, text):
    """[('exhibit_interest', id)] for each exhibit whose name (or id words) the answer to ICE_FAV names; at most MAX_ITEMS."""
    low = text.lower()
    hits = [("exhibit_interest", e["id"]) for e in gallery["exhibits"]
            if any(c in low for c in (e["name"].lower(), e["id"].replace("_", " ")))]
    return hits[:MAX_ITEMS]


@dataclass(frozen=True)
class Question:
    id: str
    type: str                 # choice | open
    text: str
    options: tuple            # ((kind, target, display name), ...) the only layers an answer may yield
    cues: dict                # (kind, target) -> lowercase words a quote must contain to support that option


DEPTH_CUES = ("full story", "whole story", "long version", "longer version", "everything", "all of it", "in depth")


def _cues(kind, target, name):
    """Words that name an option: its display name and its id ('sea_chest' -> 'sea chest', 'figurehead.carving' ->
    'carving'). Depth has hand-written paraphrases. Untuned: a real visitor's paraphrase can miss them (then nothing is
    stored, which is the safe side)."""
    if kind == "depth":
        return DEPTH_CUES
    return (name, target.split(".")[-1].replace("_", " "))


def _q(qid, typ, text, options):
    return Question(qid, typ, text, options, {(k, t): _cues(k, t, n) for k, t, n in options})


def menu(gallery, first_stop):
    ex = {e["id"]: e for e in gallery["exhibits"]}
    stop = ex[first_stop]
    f = stop["features"]
    m = [
        _q("depth", "choice", "Would you like the short version of each piece, or the full story?",
           (("depth", first_stop, "the full story"),)),      # "short" has no layer kind: it yields nothing
        _q("features", "choice", f"At our first stop, the {stop['name'].lower()}, shall I tell you more about "
                                 f"the {f[0]['name'].lower()} or the {f[1]['name'].lower()}?",
           tuple(("feature_interest", x["id"], x["name"].lower()) for x in f[:2])),
        _q("open", "open", "Is there anything in this gallery you're curious to see?",
           tuple(("exhibit_interest", e["id"], e["name"].lower()) for e in gallery["exhibits"])
           + tuple(("feature_interest", x["id"], x["name"].lower()) for e in gallery["exhibits"] for x in e["features"])),
    ]
    for q in m:
        assert not SINGLING_OUT.search(q.text), q.text
        assert all(k in LAYER_KINDS for k, _, _ in q.options), q.id
    return m


def allowed(m, asked):
    if len(asked) >= BUDGET:
        return []
    return [q for q in m if q.id not in asked and (q.type == "choice" or any(a.type == "choice" for a in m if a.id in asked))]


def _json(raw):
    if not isinstance(raw, str):
        return None
    i, j = raw.find("{"), raw.rfind("}")
    if i == -1 or j < i:
        return None
    try:
        o = json.loads(raw[i:j + 1])
    except ValueError:
        return None
    return o if isinstance(o, dict) else None


SELECT_SYSTEM = (
    "You choose the next question a museum guide robot asks a whole tour group at the start of a tour. You may only "
    "choose an id from the list you are given, or \"none\" to stop asking. Prefer short choice questions; ask the open "
    "question only if it would add something. Never invent a question. Output ONLY one JSON object: {\"next\": \"<id>\"}.")


def select(llm, m, asked, known):
    """-> (Question or None, how, raw). known: {(kind, target): number of visitors} extracted so far (no text)."""
    ok = allowed(m, asked)
    if not ok:
        return None, "budget", None
    user = json.dumps({"task": "select", "allowed": [{"id": q.id, "type": q.type, "text": q.text} for q in ok],
                       "asked": list(asked), "learned_so_far": [{"kind": k, "target": t, "visitors": n}
                                                                for (k, t), n in sorted(known.items())]})
    try:
        raw = llm(SELECT_SYSTEM, user)
    except (OSError, ValueError) as exc:     # an LLM outage must not stop the encounter (a replay miss still raises)
        raw = f"[LLM error: {type(exc).__name__}]"
    o = _json(raw)
    nxt = o.get("next") if o else None
    if nxt == "none":
        return None, "llm", raw
    q = next((q for q in ok if q.id == nxt), None)
    return (q, "llm", raw) if q else (ok[0], "fallback", raw)


EXTRACT_SYSTEM = (
    "You read ONE answer a museum visitor gave to a question the robot asked the whole group. Extract only what the "
    "visitor explicitly said they want, as items from the options list. Output ONLY one JSON object: "
    "{\"layers\": [{\"kind\": str, \"target\": str, \"confidence\": 0-1, \"quote\": str}]}. kind and target must be "
    "copied from one option. quote must be copied verbatim from the answer. Do NOT infer mood, personality, age, gender, "
    "culture or anything not said. If nothing qualifies, return {\"layers\": []}.")


def extract(llm, q, text):
    """-> (layers [(kind, target)], dropped [(item, why)], raw)."""
    user = json.dumps({"task": "extract", "question": q.text,
                       "options": [{"kind": k, "target": t, "name": n} for k, t, n in q.options], "answer": text})
    try:
        raw = llm(EXTRACT_SYSTEM, user)
    except (OSError, ValueError) as exc:
        raw = f"[LLM error: {type(exc).__name__}]"
    o = _json(raw)
    if o is None or not isinstance(o.get("layers"), list):
        return [], [("all", "json_or_shape")], raw
    opts, low, out, dropped = {(k, t) for k, t, _ in q.options}, text.lower(), [], []
    for it in o["layers"]:
        if not isinstance(it, dict):
            dropped.append((str(it)[:40], "not_dict")); continue
        key = (it.get("kind"), it.get("target"))
        try:
            conf = float(it.get("confidence"))
        except (TypeError, ValueError):
            conf = 0.0
        quote = str(it.get("quote", "")).strip().lower()
        if key not in opts:
            dropped.append((f"{key[0]}:{key[1]}", "not_an_option")); continue
        if conf < CONFIDENCE_MIN:
            dropped.append((f"{key[0]}:{key[1]}", "low_conf")); continue
        if not quote or quote not in low:
            dropped.append((f"{key[0]}:{key[1]}", "quote_not_in_text")); continue
        if not any(c in quote for c in q.cues[key]):
            dropped.append((f"{key[0]}:{key[1]}", "quote_does_not_name_it")); continue
        if key not in out:
            out.append(key)
    return out[:MAX_ITEMS], dropped, raw


# ---------------------------------------------------------------- simulated replies (no LLM): hidden truth + templates

def ice_replies(qid, visitors, names, rng, max_answers=3):
    """Simulated answers to an icebreaker. visitors: [(track_id, talk probability, been_before, hidden favourite id or None)].
    The reserved visitor (p = 0) never answers. -> [(track_id, text)]."""
    out = []
    for tid, p, been, fav in visitors:
        if rng.random() >= p:
            continue
        if qid == "ice_visit":
            text = rng.choice(("Yes, I've been on a few.", "Yes, a couple of times.")) if been else rng.choice(
                ("No, this is my first one.", "No, never before."))
        elif qid == "ice_day":
            text = rng.choice(("Pretty good, thanks!", "Good, we've been looking forward to this.", "Busy, but good."))
        else:
            text = f"I like the {names[fav]}." if fav else rng.choice(("Not really, I'm new here.", "Not sure yet."))
        out.append((tid, text))
    rng.shuffle(out)
    return out[:max_answers]


def replies(q, visitors, names, rng, max_answers=3):
    """visitors: [(track_id, talk probability, hidden interests {(kind, target)})]. Who answers is a seeded draw on
    talkativeness (a reserved visitor, p = 0, never does); what they say is a template over their hidden interests.
    -> [(track_id, text)] in speaking order."""
    out = []
    for tid, p, interests in visitors:
        if rng.random() >= p:
            continue
        hits = [(k, t) for k, t, _ in q.options if (k, t) in interests]
        if q.id == "depth":
            text = "The full story, please." if hits else "Short is fine."
        elif q.id == "features":
            text = f"The {names[hits[0][1]]}!" if hits else "Either is fine."
        else:
            ex = [t for k, t in hits if k == "exhibit_interest"]
            ft = [t for k, t in hits if k == "feature_interest"]
            text = (f"What about the {names[ex[0]]}?" if ex else
                    f"That {names[ft[0]]} looks interesting." if ft else "Not sure yet.")
        out.append((tid, text))
    rng.shuffle(out)
    return out[:max_answers]
