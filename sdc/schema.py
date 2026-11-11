"""Perception -> processing interface (block 2 -> block 3), schema v0.1.

A stream is a JSONL file. Line types:
  header            once, first line
  start_impression  once, from Jay's initial encounter (block 1)
  frame             perception output, RATE_HZ times a second
  utterance         asynchronous, from ASR, whenever a visitor finishes speaking

See "Interface (perception → processing).md" in the vault for the human-readable spec.
This module is the executable version: validate_line() raises SchemaError on any violation.
"""

SCHEMA_VERSION = "0.1"

AGE_CLASSES = {"child", "adult"}
POSTURES = {"standing", "leaning", "sitting"}
ATTENTION_PREFIXES = ("exhibit:", "feature:", "visitor:")
ATTENTION_PLAIN = {"robot", "none"}


class SchemaError(ValueError):
    pass


def _req(obj, key, types, where):
    if key not in obj:
        raise SchemaError(f"{where}: missing '{key}'")
    v = obj[key]
    bad_bool = isinstance(v, bool) and bool not in _as_tuple(types)  # bool is an int subclass
    if not isinstance(v, types) or bad_bool:
        raise SchemaError(f"{where}: '{key}' has type {type(v).__name__}")
    return v


def _as_tuple(t):
    return t if isinstance(t, tuple) else (t,)


NUM = (int, float)


def _attention_ok(a):
    return a in ATTENTION_PLAIN or any(a.startswith(p) and len(a) > len(p) for p in ATTENTION_PREFIXES)


def validate_header(o):
    w = "header"
    if _req(o, "schema_version", str, w) != SCHEMA_VERSION:
        raise SchemaError(f"{w}: schema_version {o['schema_version']} != {SCHEMA_VERSION}")
    _req(o, "rate_hz", NUM, w)
    _req(o, "gallery", str, w)
    _req(o, "scenario", str, w)


def validate_start_impression(o):
    w = "start_impression"
    _req(o, "t", NUM, w)
    vs = _req(o, "visitors", list, w)
    for v in vs:
        vw = f"{w}.visitor[{v.get('track_id')}]"
        _req(v, "track_id", str, vw)
        if _req(v, "age_class", str, vw) not in AGE_CLASSES:
            raise SchemaError(f"{vw}: bad age_class")
        _req(v, "age_conf", NUM, vw)
        _req(v, "cluster_id", str, vw)
        _req(v, "responded_to_steer_invite", bool, vw)
        seed = _req(v, "baseline_seed", dict, vw)
        for k in ("distance_m", "robot_glances_per_min", "speech_frac"):
            _req(seed, k, NUM, vw + ".baseline_seed")
        for pl in _req(v, "pending_layers", list, vw):
            _req(pl, "kind", str, vw + ".pending_layers")
            _req(pl, "target", str, vw + ".pending_layers")
    g = _req(o, "group", dict, w)
    _req(g, "size", int, w + ".group")
    _req(g, "spread_m", NUM, w + ".group")


def validate_frame(o):
    w = f"frame@{o.get('t')}"
    _req(o, "t", NUM, w)
    r = _req(o, "robot", dict, w)
    for k in ("x", "y", "yaw"):
        _req(r, k, NUM, w + ".robot")
    _req(r, "speaking", bool, w + ".robot")
    for v in _req(o, "visitors", list, w):
        vw = f"{w}.visitor[{v.get('track_id')}]"
        _req(v, "track_id", str, vw)
        for k in ("x", "y", "body_yaw", "head_yaw", "track_conf", "age_conf"):
            _req(v, k, NUM, vw)
        if not _attention_ok(_req(v, "attention", str, vw)):
            raise SchemaError(f"{vw}: bad attention '{v['attention']}'")
        for k in ("speaking", "overlapped", "los_exhibit", "los_robot", "in_formation"):
            _req(v, k, bool, vw)
        if v["overlapped"] and not v["speaking"]:
            raise SchemaError(f"{vw}: overlapped without speaking")
        _req(v, "cluster_id", str, vw)
        if _req(v, "age_class", str, vw) not in AGE_CLASSES:
            raise SchemaError(f"{vw}: bad age_class")
        if _req(v, "posture", str, vw) not in POSTURES:
            raise SchemaError(f"{vw}: bad posture")
        p = v.get("pointing_at", None)
        if p is not None and not isinstance(p, str):
            raise SchemaError(f"{vw}: pointing_at must be a feature id or null")


def validate_utterance(o):
    w = f"utterance@{o.get('t')}"
    _req(o, "t", NUM, w)
    _req(o, "track_id", str, w)
    _req(o, "text", str, w)
    _req(o, "is_question", bool, w)
    _req(o, "duration_s", NUM, w)


VALIDATORS = {
    "header": validate_header,
    "start_impression": validate_start_impression,
    "frame": validate_frame,
    "utterance": validate_utterance,
}


def validate_line(o):
    t = o.get("type")
    if t not in VALIDATORS:
        raise SchemaError(f"unknown line type {t!r}")
    VALIDATORS[t](o)


def validate_stream(lines):
    """lines: iterable of parsed dicts. Checks per-line schema plus stream order."""
    lines = list(lines)
    if not lines or lines[0].get("type") != "header":
        raise SchemaError("stream must start with a header")
    if sum(1 for o in lines if o.get("type") == "start_impression") != 1:
        raise SchemaError("stream must contain exactly one start_impression")
    last_t = -1.0
    for o in lines:
        validate_line(o)
        if o["type"] == "frame":
            if o["t"] <= last_t:
                raise SchemaError(f"frame times not increasing at t={o['t']}")
            last_t = o["t"]
    return len(lines)
