"""Tools: a memory for things the user tells the assistant to keep ("remember that my bike lock code is
4172", "what did I say about the landlord?"). Recalled by meaning with the Embedder slot, stored only on
this PC in `store` (a readable JSON file plus the vectors).

install(embedder, store) registers the tools.
"""
import json
import time
from pathlib import Path

import numpy as np

from .registry import tool

QUERY = "Represent this sentence for searching relevant passages: "  # what bge models expect in front of a query


class Memory:
    def __init__(self, embedder, store: Path):
        self._embedder, self._facts, self._npy = embedder, store / "memory.json", store / "memory.npy"
        try:
            self.facts: list[dict] = json.loads(self._facts.read_text(encoding="utf-8"))
            self._vectors = np.load(self._npy)
            assert len(self._vectors) == len(self.facts)
        except (OSError, ValueError, AssertionError):
            self.facts, self._vectors = [], None

    def add(self, text: str) -> None:
        v = self._embedder.embed([text])
        self._vectors = v if self._vectors is None or not len(self.facts) else np.concatenate([self._vectors, v])
        self.facts.append({"text": text, "at": time.time()})
        self._save()

    def find(self, about: str, k: int = 3, floor: float = 0.45) -> list[tuple[float, int]]:
        """-> up to k (similarity, index into facts), best first, leaving out anything below `floor`."""
        if not self.facts:
            return []
        sims = self._vectors @ self._embedder.embed([QUERY + about])[0]
        return [(float(sims[i]), int(i)) for i in np.argsort(-sims)[:k] if sims[i] >= floor]

    def drop(self, index: int) -> str:
        text = self.facts.pop(index)["text"]
        self._vectors = np.delete(self._vectors, index, axis=0)
        self._save()
        return text

    def _save(self) -> None:
        self._facts.parent.mkdir(parents=True, exist_ok=True)
        self._facts.write_text(json.dumps(self.facts, indent=1), encoding="utf-8")
        np.save(self._npy, self._vectors)


def install(embedder, store: Path) -> Memory:
    memory = Memory(embedder, store)

    @tool("Remember something for the user when they ask you to remember, note or keep in mind a fact about "
          "themselves or their things. fact: the fact as one full sentence.")
    def remember(fact: str) -> str:
        memory.add(fact)
        return "remembered"

    @tool("Look up what the user asked you to remember earlier: 'what is my ...', 'what did I tell you about ...', "
          "'do you remember ...'. about: what to look for.")
    def recall(about: str) -> str:
        hits = memory.find(about)
        return "\n".join(f"{memory.facts[i]['text']} (told {time.strftime('%d %B', time.localtime(memory.facts[i]['at']))})"
                         for _, i in hits) or "nothing remembered about that"

    @tool("Forget something the user asked you to remember. about: which thing.", risky=True)
    def forget(about: str) -> str:
        hits = memory.find(about, k=1, floor=0.6)
        return f"forgot: {memory.drop(hits[0][1])}" if hits else "nothing remembered matches that"
    return memory
