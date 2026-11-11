"""Brick: the fast path. Decides in embedding space, with no text generated: the utterance is
embedded once (~30 ms) and compared with example phrasings of known intents. A confident match
names a tool call directly; anything else returns None and goes to the LLM.

It only ever picks among routes written in routes.toml, so it cannot invent an action.
"""
from dataclasses import dataclass, field

import numpy as np

from .contracts import Embedder


@dataclass
class Route:
    tool: str
    say: list[str]                              # example phrasings
    args: dict = field(default_factory=dict)    # fixed arguments for the tool
    reply: str = "Done."                        # spoken afterwards; {result} is the tool's output


class Router:
    def __init__(self, embedder: Embedder, routes: list[Route], threshold: float = 0.86, margin: float = 0.04):
        self._embedder, self._routes, self._threshold, self._margin = embedder, routes, threshold, margin
        self._owner = np.array([i for i, r in enumerate(routes) for _ in r.say])
        self._examples = embedder.embed([s for r in routes for s in r.say])

    def match(self, text: str) -> tuple[Route | None, float]:
        """-> (route, score). route is None unless the best route scores >= threshold AND beats
        every other route by `margin` (so "volume up" vs "volume down" can't be a coin toss)."""
        sims = self._examples @ self._embedder.embed([text.lower().strip(" .!?,")])[0]
        best = int(np.argmax(sims))
        rival = float(np.max(sims[self._owner != self._owner[best]], initial=-1.0))
        score = float(sims[best])
        ok = score >= self._threshold and score - rival >= self._margin
        return (self._routes[self._owner[best]] if ok else None), score
