"""Sound for the draft video (no numpy, no network): voices, mixing, and fitting a line into its slot (a generated tone stands in for gTTS)."""
import shutil
import subprocess
import wave

import pytest

from perception.encounter_sim import audio


def test_the_child_gets_the_high_voice_and_adults_distinct_ones():
    v = audio.voices([("v1", "adult"), ("v2", "child"), ("v3", "adult"), ("v4", "adult")])
    assert v["v2"] == audio.CHILD and v["v2"][1] > max(p for _, p in audio.ADULT)
    assert len({v["v1"], v["v3"], v["v4"], audio.ROBOT}) == 4


def test_mix_places_each_line_at_its_offset(tmp_path):
    def wav(name, n, x):
        p = str(tmp_path / name)
        with wave.open(p, "wb") as w:
            w.setnchannels(1), w.setsampwidth(2), w.setframerate(1000)
            w.writeframes(b"".join(int(x).to_bytes(2, "little", signed=True) for _ in range(n)))
        return p
    out = str(tmp_path / "m.wav")
    audio.mix([(1.0, wav("a.wav", 500, 100)), (1.25, wav("b.wav", 500, 50))], 3.0, out)
    with wave.open(out) as w:
        pcm = [int.from_bytes(w.readframes(1), "little", signed=True) for _ in range(w.getnframes())]
    assert pcm[500] == 0 and pcm[1100] == 100 and pcm[1300] == 150 and pcm[1600] == 50 and pcm[1800] == 0


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg not installed")
def test_a_line_is_sped_up_to_fit_its_slot(tmp_path, monkeypatch):
    tone = str(tmp_path / "tone.mp3")
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", "sine=frequency=300:duration=6", "-ar", "24000", tone], check=True)
    monkeypatch.setattr(audio, "_mp3", lambda text, tld: tone)               # no network in tests
    d, fits = audio.say("x", audio.ROBOT, 4.8, str(tmp_path / "x.wav"))
    assert fits and d <= 4.8 + audio.SPILL_S + 0.05 and d > 4.0
    d, fits = audio.say("x", audio.ROBOT, 2.0, str(tmp_path / "y.wav"))      # 6 s into 2 s: beyond MAX_TEMPO, reported not cut
    assert not fits and d > 2.4
    d, _ = audio.say("x", audio.CHILD, 9.0, str(tmp_path / "z.wav"))        # higher pitch keeps the duration
    assert 5.8 < d < 6.2
