"""Tool registry and safety policy. A tool is a plain typed function with a one-line description;
its JSON schema is derived from the signature, which keeps the prompt (and so every request) short.
"""
import inspect
import json
import time
from dataclasses import dataclass
from typing import Callable

_JSON = {str: "string", int: "integer", float: "number", bool: "boolean"}
_TOOLS: dict[str, "Tool"] = {}


@dataclass
class Tool:
    fn: Callable[..., str]
    risky: bool
    spec: dict


def tool(description: str, risky: bool = False):
    """Register a function. `risky` = changes or destroys something, or runs arbitrary code."""
    def wrap(fn):
        params = inspect.signature(fn).parameters
        _TOOLS[fn.__name__] = Tool(fn, risky, {"type": "function", "function": {
            "name": fn.__name__, "description": description,
            "parameters": {"type": "object",
                           "properties": {n: {"type": _JSON[p.annotation]} for n, p in params.items()},
                           "required": [n for n, p in params.items() if p.default is p.empty]}}})
        return fn
    return wrap


class Toolbox:
    """policy: "confirm" asks before risky tools, "auto" runs everything, "readonly" hides risky tools.
    confirm(question) -> bool is supplied by the app (spoken yes/no)."""

    def __init__(self, policy: str, confirm: Callable[[str], bool], disabled: list[str] = (),
                 check: Callable[[str, dict, str], str] = lambda name, args, result: result,
                 on_result: Callable[[str, str, float], None] = lambda name, result, seconds: None):
        """check(name, args, result) -> result: sees every successful call and may add what it observed
        afterwards (e.g. "verified on screen"), so the model reports what happened, not what it hoped.
        on_result(name, result, seconds): told about every finished call, for displays and logs."""
        self._check, self._on_result = check, on_result
        if policy not in ("confirm", "auto", "readonly"):
            raise ValueError(f"tools.policy must be confirm, auto or readonly, not {policy!r}")
        self._policy, self._confirm = policy, confirm
        self._tools = {n: t for n, t in _TOOLS.items()
                       if n not in disabled and not (t.risky and policy == "readonly")}

    def specs(self) -> list[dict]:
        return [t.spec for t in self._tools.values()]

    def menu(self) -> dict[str, str]:
        """name -> description, for anything that chooses among the tools without the full schemas."""
        return {n: t.spec["function"]["description"] for n, t in self._tools.items()}

    def call(self, name: str, arguments: str) -> str:
        """Never raises: the result string (or the error) goes back to the model."""
        started = time.time()
        result = self._call(name, arguments)
        self._on_result(name, result, time.time() - started)
        return result

    def _call(self, name: str, arguments: str) -> str:
        t = self._tools.get(name)
        if not t:
            return f"error: no tool named {name}"
        try:
            args = json.loads(arguments or "{}")
            if t.risky and self._policy == "confirm":
                detail = ", ".join(str(v) for v in args.values())[:120]
                if not self._confirm(f"Should I {name.replace('_', ' ')}: {detail}?"):
                    return "cancelled: the user said no"
            result = str(t.fn(**args))[:4000]
            return result if result.startswith("error") else self._check(name, args, result)
        except Exception as e:
            return f"error: {type(e).__name__}: {e}"
