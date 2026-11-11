"""Brick: end-of-turn decision. Fills the TurnEnd slot with Smart Turn v3.2 (Pipecat, BSD-2-Clause), an
8 MB audio classifier that answers one question from the sound alone: has the speaker finished?
About 30 ms on the CPU, so a command can end after a short pause instead of a long fixed one, and a
mid-sentence pause no longer cuts the speaker off.

The model wants Whisper's input: the last 8 s of audio as an 80 x 800 log-mel picture.
"""
from pathlib import Path

import numpy as np

from .contracts import MIC_RATE

_WINDOW = 8 * MIC_RATE
_N_FFT, _HOP, _MELS = 400, 160, 80


def _mel_filters() -> np.ndarray:
    """Whisper's 80 triangular filters (Slaney scale and normalisation), shape (201, 80)."""
    def to_mel(f):
        f = np.asarray(f, np.float64)
        return np.where(f >= 1000, 15 + np.log(np.maximum(f, 1e-9) / 1000) * 27 / np.log(6.4), 3 * f / 200)

    def to_hz(m):
        return np.where(m >= 15, 1000 * np.exp(np.log(6.4) / 27 * (m - 15)), 200 * m / 3)

    bins = np.linspace(0, MIC_RATE / 2, _N_FFT // 2 + 1)
    edges = to_hz(np.linspace(to_mel(0), to_mel(8000), _MELS + 2))
    up = (bins[:, None] - edges[None, :-2]) / np.diff(edges)[None, :-1]
    down = (edges[None, 2:] - bins[:, None]) / np.diff(edges)[None, 1:]
    return (np.maximum(0, np.minimum(up, down)) * (2 / (edges[2:] - edges[:-2]))[None, :]).astype(np.float32)


class SmartTurn:
    def __init__(self, model: Path, threads: int = 2):
        import onnxruntime as ort  # here, not at the top: without the model file the daemon never needs it
        if not model.exists():
            raise FileNotFoundError(f"{model} is missing; run setup.ps1")
        so = ort.SessionOptions()
        so.intra_op_num_threads, so.inter_op_num_threads = threads, 1
        self._session = ort.InferenceSession(str(model), so, providers=["CPUExecutionProvider"])
        self._filters = _mel_filters()
        self._window = np.hanning(_N_FFT + 1)[:-1].astype(np.float32)

    def finished(self, pcm: np.ndarray) -> float:
        x = pcm[-_WINDOW:].astype(np.float32)
        x = (x - x.mean()) / np.sqrt(x.var() + 1e-7)
        x = np.pad(x, (_WINDOW - len(x), 0))                       # silence goes in front, speech ends the window
        x = np.pad(x, _N_FFT // 2, mode="reflect")
        frames = np.lib.stride_tricks.sliding_window_view(x, _N_FFT)[::_HOP][:-1]
        power = np.abs(np.fft.rfft(frames * self._window, axis=1)) ** 2
        mel = np.log10(np.maximum(power @ self._filters, 1e-10))
        mel = (np.maximum(mel, mel.max() - 8.0) + 4.0) / 4.0
        return float(self._session.run(None, {"input_features": mel.T[None].astype(np.float32)})[0].reshape(-1)[0])
