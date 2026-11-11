"""Brick: sound cues. A few very short tones, synthesized here (no audio files), that tell you where the
assistant is without looking: it woke, it heard you, it has something to tell you, something failed.
Each persona has its own timbre, so you can hear which one answered.
"""
import numpy as np

RATE = 24000
# cue -> notes as (frequency ratio to the persona's base, start s, length s)
CUES = {
    "wake": [(1.0, 0.00, 0.09), (1.5, 0.08, 0.14)],
    "heard": [(2.0, 0.00, 0.05)],
    "notify": [(1.0, 0.00, 0.09), (1.25, 0.09, 0.09), (1.5, 0.18, 0.09), (2.0, 0.27, 0.20)],
    "error": [(0.75, 0.00, 0.11), (0.5, 0.12, 0.18)],
}
# persona -> (base Hz, harmonic amplitudes): the default is a clean bell, Chimera a reedy, throat-like tone
TIMBRES = {"": (660.0, (1.0, 0.25, 0.08)), "chimera": (196.0, (1.0, 0.7, 0.5, 0.35, 0.2, 0.12))}


def render(cue: str, persona: str = "", volume: float = 0.2) -> np.ndarray:
    """-> the cue as mono float32 at RATE."""
    base, harmonics = TIMBRES.get(persona, TIMBRES[""])
    notes = CUES[cue]
    out = np.zeros(int(RATE * (max(s + n for _, s, n in notes) + 0.05)), np.float32)
    for ratio, start, length in notes:
        t = np.arange(int(RATE * length)) / RATE
        tone = sum(a * np.sin(2 * np.pi * base * ratio * (k + 1) * t) for k, a in enumerate(harmonics))
        envelope = np.minimum(1, t / 0.004) * np.exp(-t / (length * 0.35))  # 4 ms attack: no click
        i = int(RATE * start)
        out[i:i + len(t)] += (tone * envelope).astype(np.float32)
    return out * (volume / max(1e-6, float(np.abs(out).max())))


class Cues:
    def __init__(self, volume: float = 0.2, device=None):
        self._volume, self._device, self._cache = volume, device, {}

    def play(self, cue: str, persona: str = "", wait: bool = False) -> None:
        """Never raises: a cue is a nicety. wait=True returns when it has finished sounding
        (use it before listening, so the microphone does not record the cue)."""
        try:
            import sounddevice as sd
            key = (cue, persona)
            if key not in self._cache:
                self._cache[key] = render(cue, persona, self._volume)
            sd.play(self._cache[key], RATE, device=self._device, blocking=wait)
        except Exception:
            pass
