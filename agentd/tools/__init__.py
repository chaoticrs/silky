"""Brick: tools the agent can call. Public surface: Toolbox (and `tool` for writing new ones).
To add a tool: write a function with @tool in a module here and import that module below.
A tool that needs a live brick (the file index, the screen, the assistant itself) lives in a module with an
install(...) function instead, which the app calls with that brick: linked, lookout, reminders, memory.
"""
from .registry import Toolbox, tool
from . import apps, clipboard, files, shell, system  # noqa: F401  (importing registers their tools)

__all__ = ["Toolbox", "tool"]
