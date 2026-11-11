"""Brick: speech out. Queues sentences, synthesizes the next one while the current one plays
(so the first sound comes after one sentence, not the whole reply), and reports loudness
and a 6-band spectrum per ~33 ms block for the overlay.
"""
import queue
import re
import threading
from typing import Callable, Iterable, Iterator

import numpy as np

from .contracts import Voice

_END = re.compile(r"(?<=[.!?:;\n])\s+")
# markdown, the stray tag a no-thinking model leaks, and emoji (a TTS voice reads them as a second of noise)
_MARKUP = re.compile(r"</?think>?|[*_#`>|]+|[\U0001F000-\U0001FAFF☀-➿⬀-⯿️‍]+")


def sentences(deltas: Iterable[str], min_chars: int = 16) -> Iterator[str]:
    """Regroup streamed text into speakable sentences, markdown stripped. A sentence shorter than
    min_chars ("Sure!") is joined to the next one, never held back until the reply ends."""
    buf = ""
    for d in deltas:
        buf += d
        parts = _END.split(buf)
        while len(parts) > 1:
            if len(parts[0]) >= min_chars:
                yield _clean(parts.pop(0))
            elif len(parts) > 2:
                parts[:2] = [parts[0] + " " + parts[1]]
            else:
                break
        buf = " ".join(parts)
    if _clean(buf):
        yield _clean(buf)


def _clean(text: str) -> str:
    return " ".join(_MARKUP.sub("", text).split())


def _bands(block: np.ndarray, rate: int) -> list[float]:
    spec = np.abs(np.fft.rfft(block * np.hanning(len(block))))
    edges = (np.array([80, 250, 500, 1000, 2000, 4000, 8000]) * len(block) / rate).astype(int)
    return [float(min(1.0, spec[a:b].mean() * 0.25)) if b > a else 0.0 for a, b in zip(edges, edges[1:])]


class Speaker:
    def __init__(self, voice: Voice, on_say: Callable[[str], None] = lambda t: None,
                 on_level: Callable[[float, list], None] = lambda v, b: None, device=None):
        self.voice = voice  # public: assign another Voice to switch engines; applies from the next sentence
        self._on_say, self._on_level, self._device = on_say, on_level, device
        self._gen = 0  # bumped by stop(); work tagged with an older gen is discarded
        self._text: queue.Queue = queue.Queue()
        self._audio: queue.Queue = queue.Queue(maxsize=2)
        threading.Thread(target=self._synth_loop, daemon=True).start()
        threading.Thread(target=self._play_loop, daemon=True).start()

    def say(self, text: str) -> None:
        """Queue one sentence; returns immediately."""
        self._text.put((self._gen, text))

    def wait(self) -> None:
        """Block until everything queued has been spoken (or stopped)."""
        self._text.join()
        self._audio.join()

    def stop(self) -> None:
        """Cut speech off now and drop whatever is queued."""
        self._gen += 1

    def _synth_loop(self):
        while True:
            gen, text = self._text.get()
            try:
                if gen == self._gen:
                    self._audio.put((gen, text, *self.voice.synth(text)))
            except Exception as e:
                print(f"[speak] {e}")
            finally:
                self._text.task_done()

    def _play_loop(self):
        import sounddevice as sd
        out, out_rate = None, 0
        while True:
            gen, text, pcm, rate = self._audio.get()
            try:
                if gen != self._gen:
                    continue
                if rate != out_rate:
                    if out is not None:  # a voice with another sample rate: don't leave the old device stream open
                        out, old = None, out
                        old.close(ignore_errors=True)
                    out = sd.OutputStream(samplerate=rate, channels=1, dtype="float32", device=self._device)
                    out.start()
                    out_rate = rate
                self._on_say(text)
                step = rate // 30
                for i in range(0, len(pcm), step):
                    if gen != self._gen:
                        break
                    block = pcm[i:i + step]
                    self._on_level(float(min(1.0, np.sqrt(np.mean(block * block)) * 6)), _bands(block, rate))
                    out.write(block)
                self._on_level(0.0, [0.0] * 6)
            except Exception as e:
                print(f"[speak] {e}")
                out_rate = 0
            finally:
                self._audio.task_done()
