"""Brick: endpointing. Records one utterance from a Mic: starts at the first loud frame and stops
after a silence. Energy finds the pauses (no model, about zero CPU); an optional TurnEnd decision
model then judges a short pause, so a finished command ends after `quick_s` instead of `silence_s`.
"""
from typing import Callable

import numpy as np

from .contracts import FRAME, MIC_RATE, Mic, TurnEnd

FRAME_S = FRAME / MIC_RATE


class Listener:
    def __init__(self, min_rms: float = 0.008, silence_s: float = 0.8, max_s: float = 15.0,
                 turn: TurnEnd | None = None, quick_s: float = 0.3, sure: float = 0.8):
        """turn: asked once per pause, after quick_s of quiet; if it is at least `sure` that the speaker
        has finished, the utterance ends there. Without it (or when unsure) silence_s decides, as before."""
        self._min, self._silence, self._max = min_rms, silence_s, max_s
        self._turn, self._quick, self._sure = turn, quick_s, sure
        self._noise = min_rms / 3

    def observe(self, frame: np.ndarray) -> None:
        """Call with idle frames so the speech threshold follows the room's noise floor."""
        rms = float(np.sqrt(np.mean(frame * frame)))
        self._noise = min(rms, self._noise * 1.02 + 1e-6)  # drops fast, creeps up slowly

    def capture(self, mic: Mic, start_timeout_s: float, on_level: Callable[[float], None] = lambda v: None,
                lead: list = ()):
        """-> the utterance, or None if nobody spoke within start_timeout_s.
        `lead` = frames heard just before this call (the wake word and what followed it), replayed
        first so words spoken while the wake word was still being recognised are not lost."""
        lead = list(lead)
        gate = max(self._min, self._noise * 3)
        frames, waited, quiet, started = [], 0.0, 0.0, False
        while True:
            f = lead.pop(0) if lead else mic.read()
            rms = float(np.sqrt(np.mean(f * f)))
            on_level(min(1.0, rms * 12))
            if rms >= gate:
                started, quiet = True, 0.0
            elif started:
                quiet += FRAME_S
                if self._turn and abs(quiet - self._quick) < FRAME_S / 2:  # once per pause
                    so_far = np.concatenate(frames + [f])
                    if self._turn.finished(so_far) >= self._sure:
                        return so_far
            else:
                waited += FRAME_S
                if waited >= start_timeout_s:
                    return None
                frames = frames[-2:]  # keep 200 ms of lead-in so the first consonant isn't clipped
                self.observe(f)
            frames.append(f)
            if started and (quiet >= self._silence or len(frames) * FRAME_S >= self._max):
                return np.concatenate(frames)
