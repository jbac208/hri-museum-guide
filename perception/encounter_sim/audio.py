"""Speech sound for the draft video: gTTS (Google Translate's voice, online) renders every line the replay shows as speech.

Network: the text of each encounter line (menu questions, greeting, the simulated visitors' answers: no real people) goes to
Google once; the mp3 is cached under replay/tts_cache/ (gitignored) and reused, so a re-render makes no calls.
A line's slot is the time the simulation gives it (robot: duration_s from the word count; visitors: the same). A line that is
longer than its slot (plus SPILL_S into the pause after it) is sped up with ffmpeg's atempo, up to MAX_TEMPO; one that still does
not fit is reported, not cut. gTTS has one voice per accent: the voices are accents (tld) and, for the child, a higher pitch.
Nothing here changes what is said or when.
"""

from __future__ import annotations

import array
import hashlib
import os
import subprocess
import wave

import make_replay

RATE = 24000                                       # gTTS mp3 rate; every rendered line is mono 16-bit at this rate
MAX_TEMPO, SPILL_S = 1.6, 0.4
CACHE = os.path.join(make_replay.HERE, "replay", "tts_cache")
ROBOT = ("co.uk", 1.0)                             # (gTTS accent, pitch factor)
ADULT = [("com", 1.0), ("com.au", 1.0), ("co.in", 1.0), ("ca", 1.0), ("ie", 1.0)]
CHILD = ("com", 1.3)                               # the simulated child's voice: high


def voices(visitors):
    """visitors: [(track_id, age_class)] -> {track_id: (accent, pitch)}; adults take the adult accents in turn."""
    out, adults = {}, iter(ADULT)
    for tid, age in visitors:
        out[tid] = CHILD if age == "child" else next(adults)
    return out


def _mp3(text, tld):
    """The cached mp3 of `text` in accent `tld`; the only network call."""
    from gtts import gTTS
    path = os.path.join(CACHE, hashlib.sha1(f"{tld}|{text}".encode()).hexdigest()[:16] + ".mp3")
    if not os.path.exists(path):
        os.makedirs(CACHE, exist_ok=True)
        gTTS(text, lang="en", tld=tld).save(path)
    return path


def _wav(mp3, pitch, tempo, path):
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", mp3, "-ac", "1", "-ar", str(RATE), "-filter:a",
                    f"asetrate={RATE * pitch:.0f},aresample={RATE},atempo={tempo / pitch:.4f}", "-c:a", "pcm_s16le", path],
                   check=True)
    with wave.open(path) as w:
        return w.getnframes() / w.getframerate()


def say(text, voice, slot_s, path):
    """Render `text` into `path` (WAV). -> (audio seconds, fits the slot)."""
    tld, pitch = voice
    mp3 = _mp3(text, tld)
    d = _wav(mp3, pitch, 1.0, path)
    if d > slot_s + SPILL_S:
        d = _wav(mp3, pitch, min(MAX_TEMPO, d / (slot_s + SPILL_S) + 0.01), path)
    return d, d <= slot_s + SPILL_S + 0.05


def mix(events, total_s, path):
    """events: [(offset_s, wav path)] -> one mono WAV of total_s seconds (overlaps are added)."""
    rate = None
    buf = None
    for off, p in events:
        with wave.open(p) as w:
            assert w.getnchannels() == 1 and w.getsampwidth() == 2
            rate = rate or w.getframerate()
            assert w.getframerate() == rate
            if buf is None:
                buf = array.array("h", bytes(2 * int(total_s * rate) + 2 * rate))
            pcm = array.array("h", w.readframes(w.getnframes()))
        i = int(off * rate)
        for k, x in enumerate(pcm):
            if i + k < len(buf):
                buf[i + k] = max(-32768, min(32767, buf[i + k] + x))
    with wave.open(path, "wb") as w:
        w.setnchannels(1), w.setsampwidth(2), w.setframerate(rate or 22050)
        w.writeframes((buf or array.array("h")).tobytes())
