"""The studs every brick plugs into. Bricks import from here and never from each other;
only app.py knows which concrete brick fills which slot.

Audio everywhere is mono float32 in [-1, 1]. Mic audio is 16 kHz in FRAME-sample blocks.
"""
from typing import Any, Iterator, Protocol

import numpy as np

MIC_RATE = 16000
FRAME = 1600  # 100 ms


class Mic(Protocol):
    def read(self) -> np.ndarray:
        """Block until the next FRAME of mic audio. Raises EOFError when the source ends."""

    def flush(self) -> None:
        """Drop audio buffered while nobody was reading."""


class Wake(Protocol):
    def heard(self, frame: np.ndarray) -> str | None:
        """Feed one frame; on the frame that completes a wake phrase, that phrase (else None)."""


class Stt(Protocol):
    def transcribe(self, pcm: np.ndarray) -> str:
        """16 kHz audio -> text ('' if nothing intelligible)."""


class Voice(Protocol):
    """Text-to-speech. A new voice engine (e.g. Chimera) is one class with this method."""

    def synth(self, text: str) -> tuple[np.ndarray, int]:
        """One sentence -> (samples, sample_rate)."""


class TurnEnd(Protocol):
    """A decision model for endpointing: is the speaker done, judged from the sound of the utterance so far?"""

    def finished(self, pcm: np.ndarray) -> float:
        """Mono 16 kHz audio ending at the pause in question -> probability 0..1 that the turn is over."""


class Decider(Protocol):
    """A decision model: reads a state (text and/or pictures) and answers typed questions in one forward
    pass, with probabilities and no generated text."""

    def decide(self, questions: dict, state: str | None = None, images: list[bytes] = ()) -> dict:
        """questions: name -> {"type": "noul", "instructions": ...}                      (a yes/no question)
                           or {"type": "choice", "instructions": ..., "criteria": {option: description}}
        images: PNG or JPEG bytes.
        -> name -> {"noul": probability of yes}  or  {"choice": option, "confidence": 0..1, "probabilities": {...}}"""


class Embedder(Protocol):
    def embed(self, texts: list[str]) -> np.ndarray:
        """-> one unit-length row per text, so a dot product is the cosine similarity."""


class Llm(Protocol):
    def stream(self, messages: list[dict], tools: list[dict]) -> Iterator[tuple[str, Any]]:
        """Yields ("text", str) deltas, then at most one ("tools", [{"id", "name", "arguments": json str}])."""


class Host(Protocol):
    """What a background feature (a reminder, a screen watch) may ask of the running assistant."""

    def announce(self, event: str, then: str = "") -> None:
        """Tell the user about `event` in the assistant's own words, from any thread, waiting for a turn
        in progress to finish. then: a command in plain words to carry out afterwards (ignored unless it
        asks for more than being told)."""


class Ui(Protocol):
    def emit(self, event: str, **data) -> None:
        """Fire-and-forget, callable from any thread. Events:
        state  s = idle | listening | thinking | speaking
        level  v = 0..1 loudness, bands = 6 floats 0..1 (low -> high frequency)
        heard  text = what the user said
        said   text = sentence being spoken
        tool   name = tool being run
        done   name = tool that finished, ok = it worked, ms = how long it took
        timing step = stt | route | decide | reply, ms = how long that step of the turn took
        card   title, rows = [{"label", "sub", "open": path}]: things found, to show and let the user open
        persona name = which assistant woke up (sets the overlay's label and colours)
        motion track = JSON from a voice describing what its body does during the sentence that starts
                       playing now (only voices with a motion(text) method send it; see chimera.py)
        """


class NoUi:
    def emit(self, event: str, **data) -> None:
        pass
