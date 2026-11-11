"""Brick: the agent loop. Text in, text deltas out, calling tools in between.
Knows nothing about audio, the kit, or which tools exist.

The system prompt and tool list never change between requests, so the server's prompt cache
skips re-reading them: only the new user turn is processed each time.
"""
from typing import Callable, Iterator, Protocol

from .contracts import Llm


class Tools(Protocol):
    def specs(self) -> list[dict]: ...
    def call(self, name: str, arguments: str) -> str: ...


class Agent:
    def __init__(self, llm: Llm, tools: Tools, system: str, history_turns: int = 6, max_rounds: int = 5,
                 on_tool: Callable[[str, str], None] = lambda name, arguments: None):
        self._llm, self._tools, self._specs = llm, tools, tools.specs()
        self._system = {"role": "system", "content": system}
        self._turns: list[list[dict]] = []  # one list of messages per user turn
        self._keep, self._rounds, self._on_tool = history_turns, max_rounds, on_tool

    def warm_up(self) -> None:
        """Load the model and cache the system prompt + tools before the first real request."""
        for _ in self._llm.stream([self._system, {"role": "user", "content": "hi"}], self._specs):
            break

    def note(self, user_text: str, reply: str) -> None:
        """Record an exchange that was handled elsewhere (the fast path), so follow-ups have context."""
        self._remember([{"role": "user", "content": user_text}, {"role": "assistant", "content": reply}])

    def _remember(self, turn: list[dict]) -> None:
        self._turns = self._turns[-(self._keep - 1):] + [turn] if self._keep > 1 else [turn]

    def respond(self, user_text: str, hint: str = "") -> Iterator[str]:
        """hint: an instruction for the first step only (e.g. which tool a decision model picked); it is
        sent after the conversation, so the cached prompt is untouched, and it is not remembered."""
        turn = [{"role": "user", "content": user_text}]
        self._remember(turn)
        for step in range(self._rounds):
            text, calls = "", []
            nudge = [{"role": "system", "content": hint}] if hint and step == 0 else []
            for kind, data in self._llm.stream([self._system, *(m for t in self._turns for m in t), *nudge],
                                               self._specs):
                if kind == "text":
                    text += data
                    yield data
                else:
                    calls = data
            msg = {"role": "assistant", "content": text or None}
            if calls:
                msg["tool_calls"] = [{"id": c["id"], "type": "function",
                                      "function": {"name": c["name"], "arguments": c["arguments"]}} for c in calls]
            turn.append(msg)
            if not calls:
                return
            for c in calls:
                self._on_tool(c["name"], c["arguments"])
                turn.append({"role": "tool", "tool_call_id": c["id"],
                             "content": self._tools.call(c["name"], c["arguments"])})
        yield "I had to stop there, that took too many steps."
