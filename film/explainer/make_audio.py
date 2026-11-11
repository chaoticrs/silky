"""The explainer's soundtrack, all made on this PC: narration from the kit's TTS, the recorded takes' own sound,
UI sound effects and a quiet pad.

Writes out/explainer.wav (48 kHz stereo) and out/timeline.json: when each phrase and recording starts and ends,
an estimate of when each word is spoken (for the kinetic type), what the daemon reported in each recording, and
when each effect lands. explainer.html and render.mjs
follow the timeline.        run:  ..\\..\\.venv\\Scripts\\python.exe make_audio.py      (needs the kit running)
"""
import hashlib
import json
import re
import sys
import wave
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent.parent))
sys.path.insert(0, str(HERE))
from agentd.kit import Kit, KitVoice  # noqa: E402
from beats import BEATS, END_CARD, SEQ, SFX  # noqa: E402

SR = 48000
OUT = HERE / "out"
FOOTAGE = HERE.parent / "out"   # the launch film's recorded take, cut by ../cut.py
CLIPS = OUT / "clips"
VOICE = "juno"
rng = np.random.default_rng(11)


# ---------------------------------------------------------------- helpers
def resample(x: np.ndarray, sr: int) -> np.ndarray:
    if sr == SR:
        return x.astype(np.float32)
    n = int(round(len(x) * SR / sr))
    spec = np.fft.rfft(x)
    out = np.zeros(n // 2 + 1, complex)
    m = min(len(spec), len(out))
    out[:m] = spec[:m]
    return (np.fft.irfft(out, n) * (n / len(x))).astype(np.float32)


def onepole(x: np.ndarray, hz: float, high: bool = False) -> np.ndarray:
    f = np.fft.rfftfreq(len(x), 1 / SR)
    gain = 1 / np.sqrt(1 + (f / hz) ** 2)
    return np.fft.irfft(np.fft.rfft(x) * (np.sqrt(1 - gain ** 2) if high else gain), len(x)).astype(np.float32)


def smooth(x: np.ndarray, seconds: float) -> np.ndarray:
    k = max(1, int(seconds * SR))
    c = np.cumsum(np.concatenate([np.zeros(1), x.astype(np.float64)]))
    out = (c[k:] - c[:-k]) / k
    return np.concatenate([np.full(k // 2, out[0]), out, np.full(len(x) - len(out) - k // 2, out[-1])]).astype(np.float32)


def place(track: np.ndarray, clip: np.ndarray, at: float, gain: float = 1.0, pan: float = 0.0) -> None:
    i = int(at * SR)
    if i < 0:
        clip, i = clip[-i:], 0
    clip = clip[:max(0, len(track) - i)]
    track[i:i + len(clip), 0] += clip * gain * np.sqrt((1 - pan) / 2)
    track[i:i + len(clip), 1] += clip * gain * np.sqrt((1 + pan) / 2)


def write_wav(path: Path, x: np.ndarray) -> None:
    with wave.open(str(path), "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes((np.clip(x, -1, 1) * 32767).astype("<i2").tobytes())


def t_(seconds: float) -> np.ndarray:
    return np.arange(int(seconds * SR)) / SR


# ---------------------------------------------------------------- narration
def syllables(word: str) -> int:
    return max(1, len(re.findall(r"[aeiouy]+", word.lower().rstrip("e"))))


def word_times(pcm: np.ndarray, text: str) -> list:
    """Estimate when each word is said: spread the words, weighted by syllables, over the voiced stretches of the
    clip, with the pauses between stretches left out. Good to a word or so, which is what the type needs."""
    hop = int(0.01 * SR)
    rms = np.sqrt(np.convolve(pcm ** 2, np.ones(hop) / hop, "same")[::hop])
    voiced = rms > max(0.008, 0.08 * rms.max())
    # fill gaps shorter than 70 ms: those are inside words, not between them
    idx = np.flatnonzero(voiced)
    for a, b in zip(idx[:-1], idx[1:]):
        if 1 < b - a <= 7:
            voiced[a:b] = True
    frames = np.flatnonzero(voiced)                     # the instants that carry speech, in order
    words = text.split()
    weight = np.array([syllables(w) + (0.6 if w[-1] in ",.?" else 0) for w in words], float)
    edges = np.concatenate([[0], np.cumsum(weight)]) / weight.sum()
    pos = lambda f: frames[min(len(frames) - 1, int(f * (len(frames) - 1)))] * hop / SR
    return [{"w": w, "t0": round(pos(edges[i]), 3), "t1": round(pos(edges[i + 1]), 3)} for i, w in enumerate(words)]


def sequence():
    """Lay out SEQ back to back: phrases from the kit's TTS, footage with its own recorded sound.
    -> (voice track, footage track, items, length)"""
    CLIPS.mkdir(parents=True, exist_ok=True)
    voice = KitVoice(Kit("http://127.0.0.1:8080"), "tts", VOICE)
    cut = json.loads((FOOTAGE / "cut.json").read_text(encoding="utf-8"))
    items, clips, t = [], [], 0.0
    for iid, gap, what in SEQ:
        start = max(0.0, t + gap)
        if isinstance(what, str):
            key = CLIPS / (hashlib.sha1(f"{VOICE}|{what}".encode()).hexdigest()[:12] + ".npy")
            if not key.exists():
                pcm, sr = voice.synth(what)
                pcm = resample(pcm, sr)
                loud = np.flatnonzero(np.abs(pcm) > 0.01)
                np.save(key, pcm[max(0, loud[0] - 960):loud[-1] + 2400])  # trim, keep 20 ms before and 50 ms after
            pcm = np.load(key)
            words = [{**w, "t0": round(start + w["t0"], 3), "t1": round(start + w["t1"], 3)} for w in word_times(pcm, what)]
            items.append({"id": iid, "kind": "phrase", "text": what, "t0": round(start, 3), "t1": round(start + len(pcm) / SR, 3), "words": words})
            clips.append(("voice", start, pcm))
        else:
            shot = cut[what["shot"]]
            a, b = what["from"], min(what["to"], shot["seconds"])
            pcm = np.load(FOOTAGE / f"cut_{what['shot']}.npy")[int(a * SR):int(b * SR)].copy()
            fade = int(0.04 * SR)
            pcm[:fade] *= np.linspace(0, 1, fade); pcm[-fade:] *= np.linspace(1, 0, fade)
            # the daemon's own notes and the cuts already in the shot, in this item's time
            notes = [{**n, "t": round(start + n["t"] - a, 3)} for n in shot["notes"] if a <= n["t"] <= b]
            cuts = [{"t": round(start + p["t"] - a, 3), "skipped": p["skipped"]} for p in shot["parts"] if p["skipped"] and a < p["t"] < b]
            items.append({"id": iid, "kind": "footage", "shot": what["shot"], "title": what["title"], "command": shot["command"],
                          "from": a, "t0": round(start, 3), "t1": round(start + b - a, 3), "frames": shot["frames"],
                          "notes": notes, "cuts": cuts})
            clips.append(("footage", start, pcm))
        t = items[-1]["t1"]
        print(f"  {iid:4s} {items[-1]['t0']:6.2f} - {items[-1]['t1']:6.2f}  {what if isinstance(what, str) else what['shot'] + ' (recorded take)'}")
    length = round(t + 0.35 + END_CARD, 2)
    voice_tr, foot_tr = (np.zeros((int(length * SR), 2), np.float32) for _ in range(2))
    for kind, start, pcm in clips:
        pcm = onepole(pcm, 80, high=True)
        loud = pcm[np.abs(pcm) > 0.004]
        pcm = np.tanh(pcm / (np.sqrt(np.mean(loud ** 2)) + 1e-9) * 0.16 * 2.2) / 2.2   # level every clip, tame peaks
        place(voice_tr if kind == "voice" else foot_tr, pcm, start, 1.0 if kind == "voice" else 0.9)
    return voice_tr, foot_tr, items, length


# ---------------------------------------------------------------- effects: short, crisp, quiet
def env(seconds: float, attack: float, decay: float) -> np.ndarray:
    t = t_(seconds)
    return (np.minimum(1, t / max(attack, 1e-4)) * np.exp(-t / decay)).astype(np.float32)


def click(pitch=2400.0, gain=0.5):
    t = t_(0.05)
    body = np.sin(2 * np.pi * pitch * t) * env(0.05, 0.0005, 0.008)
    snap = onepole(rng.standard_normal(len(t)).astype(np.float32), 3000, high=True) * env(0.05, 0.0002, 0.003)
    return (body * 0.7 + snap * 0.5).astype(np.float32) * gain


def swoosh(seconds=0.5, reverse=False):
    n = int(seconds * SR)
    noise = rng.standard_normal(n).astype(np.float32)
    shape = np.sin(np.linspace(0, np.pi, n)) ** 2
    shape = shape * (np.linspace(0.3, 1, n) if not reverse else np.linspace(1, 0.3, n))
    # the brightness follows the swell: mix a dark and a bright copy by the envelope
    dark, bright = onepole(onepole(noise, 900), 900), onepole(onepole(noise, 4200), 300, high=True)
    out = (dark * (1 - shape) + bright * shape) * shape
    out = out[::-1] if reverse else out
    return (out / np.abs(out).max() * 0.35).astype(np.float32)


def pop():
    t = t_(0.12)
    f = 300 + 700 * np.exp(-t / 0.02)
    return (np.sin(2 * np.pi * np.cumsum(f) / SR) * env(0.12, 0.001, 0.035)).astype(np.float32) * 0.45


def bell(notes, decay=0.5, gain=0.25):
    out = np.zeros(int((0.12 * len(notes) + decay * 3) * SR), np.float32)
    for i, f in enumerate(notes):
        t = t_(decay * 3)
        tone = (np.sin(2 * np.pi * f * t) + 0.35 * np.sin(2 * np.pi * f * 2.76 * t) * np.exp(-t / 0.08)) * env(decay * 3, 0.002, decay)
        out[int(i * 0.12 * SR):int(i * 0.12 * SR) + len(t)] += tone.astype(np.float32)
    return out * gain


def roll(seconds=1.0):
    out = np.zeros(int((seconds + 0.06) * SR), np.float32)
    at = 0.0
    while at < seconds:
        c = click(3600 + rng.uniform(-200, 200), 0.18)
        out[int(at * SR):int(at * SR) + len(c)] += c
        at += 0.045 + 0.04 * (at / seconds) ** 2        # slows as the number settles
    return out


def thump():
    t = t_(0.5)
    f = 48 + 60 * np.exp(-t / 0.03)
    return (np.sin(2 * np.pi * np.cumsum(f) / SR) * env(0.5, 0.002, 0.13)).astype(np.float32) * 0.8


SOUNDS = {
    "click": lambda: click(), "tick": lambda: click(3800, 0.3), "pop": pop, "roll": roll, "thump": thump,
    "swoosh": lambda: swoosh(), "rswoosh": lambda: swoosh(0.45, reverse=True),
    "ding": lambda: bell([1318.5, 1975.5], 0.35, 0.18), "ping": lambda: bell([1760.0, 2637.0], 0.3, 0.18),
}


def effects(items, length):
    starts = {p["id"]: p["t0"] for p in items}
    starts["end"] = items[-1]["t1"] + 0.35
    fx, events = np.zeros((int(length * SR), 2), np.float32), []
    for anchor, offset, kind in SFX:
        at = starts[anchor] + offset
        pan = {"swoosh": -0.3, "rswoosh": 0.3}.get(kind, rng.uniform(-0.25, 0.25))
        place(fx, SOUNDS[kind](), at, pan=pan)
        events.append({"t": round(at, 3), "kind": kind})
    return fx, events


# ---------------------------------------------------------------- music: a soft major-key pad and a slow pulse
hz = lambda note: 440 * 2 ** ((note - 69) / 12)
CHORDS = [(48, 55, 59, 64), (45, 52, 55, 60), (41, 48, 52, 57), (43, 50, 55, 59)]   # Cmaj7 Am7 Fmaj7 G


def tone(freq, seconds, harmonics, rolloff, detune=0.0):
    t = t_(seconds)
    out = np.zeros(len(t), np.float32)
    for k in range(1, harmonics + 1):
        out += (np.sin(2 * np.pi * freq * k * (1 + detune) * t + rng.uniform(0, 6.28)) / k ** rolloff).astype(np.float32)
    return out


def music(length, beats, footage):
    n, bar = int(length * SR), 60 / 104 * 4
    pad, pulse = np.zeros((n, 2), np.float32), np.zeros((n, 2), np.float32)
    for b in range(int(length / bar) + 1):
        chord, at = CHORDS[b % 4], b * bar
        t = t_(bar + 1.5)
        swell = (np.minimum(1, t / 1.2) * np.minimum(1, (bar + 1.5 - t) / 1.5)).astype(np.float32)
        for note in chord:
            for side, detune in ((-0.6, -0.002), (0.6, 0.002)):
                place(pad, tone(hz(note + 12), bar + 1.5, 6, 1.8, detune) * swell * 0.03, at, pan=side)
        place(pad, tone(hz(chord[0] - 12), bar + 1.5, 3, 2.0) * swell * 0.06, at)
        for beat in range(4):                                                  # a soft felt-piano-like pulse
            note = chord[(beat * 2 + 1) % 4] + 24
            tp = t_(1.0)
            pluck = (np.sin(2 * np.pi * hz(note) * tp) * np.exp(-tp / 0.35)).astype(np.float32) * 0.035
            place(pulse, onepole(pluck, 2500), at + beat * bar / 4, pan=0.4 * (-1) ** beat)
    t = np.arange(n) / SR
    mix = pad + pulse
    ir = (rng.standard_normal(int(2.0 * SR)) * np.exp(-np.arange(int(2.0 * SR)) / (0.5 * SR))).astype(np.float32)
    size = n + len(ir)
    wet = np.stack([np.fft.irfft(np.fft.rfft(mix[:, c], size) * np.fft.rfft(ir * (1 if c else -1), size), size)[:n] for c in (0, 1)], 1)
    mix += (wet / np.abs(wet).max() * 0.12).astype(np.float32)
    # quiet in the problem beat, fuller from "Meet Silky", low under the recordings, resolves at the end
    meet = beats[1]["t0"]
    level = np.interp(t, [0, meet - 0.2, meet + 0.6, length - 3, length - 1.2, length], [0.45, 0.45, 1.0, 1.1, 1.0, 0.0])
    for f in footage:
        level *= 1 - 0.55 * np.clip(np.minimum((t - f["t0"] + 0.4) / 0.4, (f["t1"] + 0.3 - t) / 0.4), 0, 1)
    fade = np.minimum(1, t / 1.0)
    return mix * (level * fade)[:, None].astype(np.float32)


if __name__ == "__main__":
    OUT.mkdir(exist_ok=True)
    print("narration (synthesized once, then cached in out/clips) and footage")
    voice, foot, items, length = sequence()
    byid = {i["id"]: i for i in items}
    beats = [{"label": label, "t0": round(byid[first]["t0"] - lead, 3)} for label, first, lead in BEATS]
    footage = [i for i in items if i["kind"] == "footage"]
    fx, events = effects(items, length)
    bed = music(length, beats, footage)
    speech = voice + foot
    level = np.sqrt(smooth(np.mean(speech ** 2, axis=1), 0.2))
    duck = smooth(1 - 0.6 * np.clip(level / 0.04, 0, 1), 0.3)
    db = lambda d: 10 ** (d / 20)
    final = voice * 1.25 + foot * 1.15 + bed * duck[:, None] * db(-6) + fx * db(-7)
    final = np.tanh(final * 1.1) / np.tanh(1.1)
    final *= 0.89 / np.abs(final).max()
    write_wav(OUT / "explainer.wav", final)
    (OUT / "timeline.json").write_text(json.dumps({"fps": 30, "length": length, "end": round(items[-1]["t1"] + 0.35, 3),
                                                   "beats": beats, "items": items, "sfx": events}, indent=1))
    print(f"out/explainer.wav and out/timeline.json: {length:.1f} s")
