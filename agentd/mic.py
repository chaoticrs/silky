"""Brick: microphone. Fills the Mic slot with the default input device, or a WAV file for tests."""
import queue
import wave

import numpy as np

from .contracts import FRAME, MIC_RATE


class DeviceMic:
    def __init__(self, device=None):
        import sounddevice as sd
        self._q: queue.Queue[np.ndarray] = queue.Queue(maxsize=100)  # 10 s; older audio is dropped
        self._stream = sd.InputStream(samplerate=MIC_RATE, blocksize=FRAME, channels=1, dtype="float32",
                                      device=device, callback=self._on_audio)
        self._stream.start()

    def _on_audio(self, data, frames, time, status):
        # must never raise: sounddevice aborts the stream on an exception here and the mic goes dead for good.
        # (full() then get_nowait() can find the queue already emptied by a flush() on the other thread)
        try:
            if self._q.full():
                self._q.get_nowait()
            self._q.put_nowait(data[:, 0].copy())
        except (queue.Empty, queue.Full):
            pass

    def read(self):
        return self._q.get()

    def flush(self):
        try:
            while True:
                self._q.get_nowait()
        except queue.Empty:
            pass


class FileMic:
    """Plays a 16 kHz mono 16-bit WAV as if spoken, then `tail_s` of silence, then EOFError."""

    def __init__(self, path: str, tail_s: float = 3.0):
        with wave.open(path) as w:
            assert (w.getframerate(), w.getnchannels(), w.getsampwidth()) == (MIC_RATE, 1, 2), "need 16 kHz mono s16"
            pcm = np.frombuffer(w.readframes(w.getnframes()), "<i2").astype(np.float32) / 32768
        self._pcm = np.concatenate([pcm, np.zeros(int(tail_s * MIC_RATE) + FRAME, np.float32)])
        self._pos = 0

    def read(self):
        if self._pos + FRAME > len(self._pcm):
            raise EOFError
        self._pos += FRAME
        return self._pcm[self._pos - FRAME:self._pos]

    def flush(self):
        pass
