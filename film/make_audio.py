"""Step 3 of the film: the soundtrack, all made on this PC.

  footage    the sound of the recorded proof shots (cut.py): the spoken commands and the assistant's answers
  narration  the kit's TTS role and the Chimera synth, one clip per script line (cached)
  music      synthesized below with numpy: a pad, a bass, a plucked arpeggio and a soft pulse over Am F C G
  effects    the product's own cues (agentd/cues.py) and noise sweeps on scene changes

Writes out/soundtrack.wav (48 kHz stereo) and out/timeline.json (when each scene and line starts, plus
Chimera's motion tracks), which film.html and render.mjs follow.     run:  ..\\.venv\\Scripts\\python.exe make_audio.py
"""
import hashlib
import json
import sys
import wave
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
from agentd import cues  # noqa: E402
from agentd.chimera import ChimeraVoice  # noqa: E402
from agentd.kit import Kit, KitVoice  # noqa: E402
from script import SCENES, TAIL  # noqa: E402

SR = 48000
OUT = HERE / "out"
CLIPS = OUT / "clips"
rng = np.random.default_rng(7)


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
    """A gentle 6 dB/octave filter, done in the frequency domain (no loop over samples)."""
    f = np.fft.rfftfreq(len(x), 1 / SR)
    gain = 1 / np.sqrt(1 + (f / hz) ** 2)
    return np.fft.irfft(np.fft.rfft(x) * (np.sqrt(1 - gain ** 2) if high else gain), len(x)).astype(np.float32)


def smooth(x: np.ndarray, seconds: float) -> np.ndarray:
    """Moving average over `seconds`, by running sum (a plain convolution here would take minutes)."""
    k = max(1, int(seconds * SR))
    c = np.cumsum(np.concatenate([np.zeros(1), x.astype(np.float64)]))
    out = (c[k:] - c[:-k]) / k
    return np.concatenate([np.full(k // 2, out[0]), out, np.full(len(x) - len(out) - k // 2, out[-1])]).astype(np.float32)


def place(track: np.ndarray, clip: np.ndarray, at: float, gain: float = 1.0, pan: float = 0.0) -> None:
    """Mix a mono clip into the stereo track at `at` seconds. pan: -1 left .. 1 right."""
    i = int(at * SR)
    clip = clip[:max(0, len(track) - i)]
    track[i:i + len(clip), 0] += clip * gain * np.sqrt((1 - pan) / 2)
    track[i:i + len(clip), 1] += clip * gain * np.sqrt((1 + pan) / 2)


def write_wav(path: Path, x: np.ndarray) -> None:
    with wave.open(str(path), "wb") as w:
        w.setnchannels(x.shape[1] if x.ndim > 1 else 1)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes((np.clip(x, -1, 1) * 32767).astype("<i2").tobytes())


# ---------------------------------------------------------------- speech
def speech():
    """-> (voice track, timeline). One clip per line, cached by its text; scenes are as long as their lines need."""
    CLIPS.mkdir(parents=True, exist_ok=True)
    kit = Kit("http://127.0.0.1:8080")
    voices = {"narrator": KitVoice(kit, "tts", "juno"), "user": KitVoice(kit, "tts", "mira"),
              "chimera": ChimeraVoice(HERE.parent / "engines" / "chimera")}
    voices["chimera"].settings.update(rate=0.9)  # a touch slower: it is easier to follow

    def clip(who: str, text: str):
        key = CLIPS / (hashlib.sha1(f"{who}|{text}".encode()).hexdigest()[:12] + ".npy")
        motion = key.with_suffix(".json")
        if not key.exists():
            pcm, sr = voices[who].synth(text)
            pcm = resample(pcm, sr)
            loud = np.flatnonzero(np.abs(pcm) > 0.01)
            pcm = pcm[max(0, loud[0] - 2400):loud[-1] + 7200]            # trim silence, keep a little air
            np.save(key, pcm)
            if who == "chimera":
                track = json.loads(voices[who].motion(text))
                cut = max(0, loud[0] - 2400) / SR                         # keep the motion in step with the trim
                track["frames"] = track["frames"][int(cut * track["fps"]):]
                motion.write_text(json.dumps(track))
        return np.load(key), (motion.read_text() if motion.exists() else None)

    cut = json.loads((OUT / "cut.json").read_text(encoding="utf-8")) if (OUT / "cut.json").exists() else {}
    scenes, clips, t = [], [], 0.0
    for scene in SCENES:
        start, lines, shots = t, [], []
        at = start + scene.get("lead", 0)
        for name in scene.get("shots", []):          # footage: its sound goes in as it was recorded
            clips.append(("footage", at, np.load(OUT / f"cut_{name}.npy")))
            shots.append({"name": name, "t0": round(at, 3), **cut[name]})
            at += cut[name]["seconds"]
        for who, pause, text in scene.get("lines", []):
            pcm, motion = clip(who, text)
            t += pause
            lines.append({"who": who, "text": text, "t0": round(t, 3), "t1": round(t + len(pcm) / SR, 3), "motion": motion})
            clips.append((who, t, pcm))
            t += len(pcm) / SR
        t = max(t + TAIL if lines else t, at + (0.25 if shots else 0), start + scene.get("min", 0))
        scenes.append({"id": scene["id"], "t0": round(start, 3), "t1": round(t, 3), "lines": lines, "shots": shots,
                       "title": scene.get("title", ""), "colour": scene.get("colour", "red")})
        print(f"  {scene['id']:8s} {start:6.2f} - {t:6.2f}")
    track = np.zeros((int((t + 1.0) * SR), 2), np.float32)
    for who, at, pcm in clips:
        pcm = onepole(pcm, 90, high=True)
        loud = pcm[np.abs(pcm) > 0.004]                                   # footage is mostly silence between words
        if not len(loud):                                                 # a sped-up shot has no sound at all
            continue
        pcm = np.tanh(pcm / (np.sqrt(np.mean(loud ** 2)) + 1e-9) * 0.16 * 2.2) / 2.2   # level every line, tame peaks
        place(track, pcm, at, {"narrator": 1.0, "footage": 0.9, "chimera": 0.95}[who])
    return track, {"fps": 30, "length": round(t + 1.0, 3), "scenes": scenes}


# ---------------------------------------------------------------- music
BPM = 116
BEAT = 60 / BPM
CHORDS = [(57, 60, 64, 69), (53, 57, 60, 65), (48, 55, 60, 64), (55, 59, 62, 67)]   # Am  F  C  G   (MIDI notes)
hz = lambda note: 440 * 2 ** ((note - 69) / 12)


def tone(freq: float, seconds: float, harmonics: int, rolloff: float, detune: float = 0.0) -> np.ndarray:
    t = np.arange(int(seconds * SR)) / SR
    out = np.zeros(len(t), np.float32)
    for k in range(1, harmonics + 1):
        if freq * k > 9000:
            break
        out += (np.sin(2 * np.pi * freq * k * (1 + detune) * t + rng.uniform(0, 6.28)) / k ** rolloff).astype(np.float32)
    return out


def music(length: float, scenes: list) -> np.ndarray:
    n = int(length * SR)
    pad, bass, arp, pulse = (np.zeros((n, 2), np.float32) for _ in range(4))
    bar = 4 * BEAT
    for b in range(int(length / bar) + 1):
        chord, at = CHORDS[b % 4], b * bar
        t = np.arange(int((bar + 1.2) * SR)) / SR
        swell = np.minimum(1, t / 1.1) * np.minimum(1, (bar + 1.2 - t) / 1.2)       # bars overlap and crossfade
        for note in chord:
            for side, detune in ((-0.7, -0.0025), (0.7, 0.0025)):
                place(pad, tone(hz(note), bar + 1.2, 7, 1.6, detune) * swell * 0.045, at, pan=side)
        tb = np.arange(int(bar * SR)) / SR
        place(bass, (np.sin(2 * np.pi * hz(chord[0] - 24) * tb) * np.minimum(1, tb / 0.05) * np.exp(-tb / 2.4)).astype(np.float32) * 0.20, at)
        for step in range(8):                                                       # eighth notes up and down the chord
            note = (chord + chord[2:0:-1] + chord[:2])[step] + 12
            tp = np.arange(int(0.9 * SR)) / SR
            pluck = ((np.sin(2 * np.pi * hz(note) * tp) + 0.4 * np.sin(4 * np.pi * hz(note) * tp)) * np.exp(-tp / 0.16)).astype(np.float32)
            for echo, (gain, side) in enumerate(((0.10, -0.5), (0.05, 0.5), (0.025, -0.5))):   # ping-pong echo
                place(arp, pluck, at + step * BEAT / 2 + echo * BEAT * 0.75, gain, side)
        for beat in (0, 2):                                                         # a soft thump on one and three
            tk = np.arange(int(0.35 * SR)) / SR
            place(pulse, (np.sin(2 * np.pi * (48 * tk + 70 * 0.045 * (1 - np.exp(-tk / 0.045)))) * np.exp(-tk / 0.11)).astype(np.float32) * 0.30, at + beat * BEAT)
        for beat in range(4):                                                       # and a whisper of a hat on the offbeats
            tick = (rng.standard_normal(int(0.05 * SR)) * np.exp(-np.arange(int(0.05 * SR)) / (0.012 * SR))).astype(np.float32)
            place(pulse, onepole(tick, 6000, high=True) * 0.05, at + (beat + 0.5) * BEAT, pan=0.3)

    # which layers play in which scene: the film opens bare, fills out for the features, thins for Chimera
    levels = {"hook": (0.8, 0.8, 0.6, 0.7), "grammar": (0.7, 0.9, 0.7, 1.0), "files": (0.7, 0.9, 0.8, 1.0),
              "watch": (0.7, 0.9, 0.8, 1.0), "chimera": (0.9, 0.7, 0.3, 0.6), "also": (0.9, 1.0, 1.0, 1.0),
              "speed": (0.9, 1.0, 1.0, 1.0), "freedom": (1.0, 1.0, 1.0, 1.0), "end": (1.0, 0.8, 0.5, 0.0)}
    t = np.arange(n) / SR
    mix = np.zeros((n, 2), np.float32)
    for layer, stem in enumerate((pad, bass, arp, pulse)):
        gain = np.interp(t, [s["t0"] + 0.2 for s in scenes], [levels[s["id"]][layer] for s in scenes])
        mix += stem * smooth(gain, 0.5)[:, None]                                     # layers ease in over half a second
    # a little room: convolve with a decaying burst of noise
    ir = (rng.standard_normal(int(1.8 * SR)) * np.exp(-np.arange(int(1.8 * SR)) / (0.45 * SR))).astype(np.float32)
    size = n + len(ir)
    wet = np.stack([np.fft.irfft(np.fft.rfft(mix[:, c], size) * np.fft.rfft(ir * (1 if c else -1), size), size)[:n] for c in (0, 1)], 1)
    mix += (wet / np.abs(wet).max() * 0.18).astype(np.float32)
    fade = np.minimum(1, t / 0.4) * np.minimum(1, (length - t) / 2.5)
    return mix * fade[:, None].astype(np.float32)


def effects(length: float, scenes: list) -> np.ndarray:
    fx = np.zeros((int(length * SR), 2), np.float32)
    for s in scenes[1:]:                                                             # a sweep of air into each scene
        m = int(0.5 * SR)
        sweep = onepole(rng.standard_normal(m).astype(np.float32), 2600) * (np.linspace(0, 1, m) ** 3).astype(np.float32)
        place(fx, sweep * 0.5, s["t0"] - 0.5, pan=-0.2)
        tb = np.arange(int(1.2 * SR)) / SR
        place(fx, (np.sin(2 * np.pi * 52 * tb) * np.exp(-tb / 0.35)).astype(np.float32) * 0.35, s["t0"])
    place(fx, resample(cues.render("notify", "", 0.5), cues.RATE), 0.05)             # the film opens on the product's own tone
    return fx


if __name__ == "__main__":
    OUT.mkdir(exist_ok=True)
    print("speech (the first run synthesizes every line; later runs reuse the clips)")
    voice, timeline = speech()
    n = len(voice)
    print("music")
    bed = music(timeline["length"], timeline["scenes"])[:n]
    fx = effects(timeline["length"], timeline["scenes"])[:n]
    # the music steps back while someone is speaking
    level = np.sqrt(smooth(np.mean(voice ** 2, axis=1), 0.2))
    duck = smooth(1 - 0.7 * np.clip(level / 0.04, 0, 1), 0.25)
    final = voice * 1.25 + bed * duck[:, None] * 0.8 + fx * 0.6
    final = np.tanh(final * 1.15) / np.tanh(1.15)
    final *= 0.89 / np.abs(final).max()
    write_wav(OUT / "soundtrack.wav", final)
    (OUT / "timeline.json").write_text(json.dumps(timeline))
    print(f"out/soundtrack.wav and out/timeline.json: {timeline['length']:.1f} s")
