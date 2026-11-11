"""Brick: looking at the screen. Pairs the screen grabber with the Decider slot (a vision decision model)
to answer yes/no questions about what is on screen, in about a third of a second and with no text generated.
The model is told the titles of the open windows as well: from the picture alone it could not tell
whether Notepad was open (0.33 with it, 0.39 without); with the titles it could (0.78 against 0.22).

That is what lets the agent act on feedback instead of assuming: check that an app it launched really
appeared, or keep watching until something the user is waiting for has happened.
"""
import threading
from typing import Callable

from .contracts import Decider

KINDS = {"code": "A code editor, IDE or terminal", "browser": "A web page in a browser", "video": "A video player or a game",
         "document": "A document, PDF, slides or spreadsheet", "chat": "A chat, mail or messaging app",
         "files": "A file manager or the desktop", "settings": "A settings, installer or dialog window"}


class Sight:
    def __init__(self, decider: Decider, grab: Callable[..., bytes], titles: Callable[[], list[str]],
                 sure: float = 0.6, lock=None):
        """lock: held for each look, so looking never overlaps other work that holds it (re-entrant is fine)."""
        self._decider, self._grab, self._titles, self._sure = decider, grab, titles, sure
        self._lock = lock or threading.RLock()

    def _state(self) -> str:
        return ("A screenshot of the user's computer screen, taken just now. Titles of the open windows, front "
                "first: " + "; ".join(t[-60:] for t in self._titles()))

    def look(self, question: str, window_only: bool = False) -> float:
        """-> probability (0..1) that the answer to a yes/no question about the screen is yes."""
        with self._lock:
            a = self._decider.decide({"q": {"type": "noul", "instructions": question}}, state=self._state(),
                                     images=[self._grab(window_only)])
        return float(a["q"]["noul"])

    def describe(self, question: str) -> str:
        """A yes/no question answered in words, with what kind of thing is on screen (context for the LLM)."""
        a = self._decider.decide({"q": {"type": "noul", "instructions": question},
                                  "kind": {"type": "choice", "instructions": "What is mainly on this screen?",
                                           "criteria": KINDS}},
                                 state=self._state(), images=[self._grab()])
        p = float(a["q"]["noul"])
        verdict = "yes" if p >= self._sure else "no" if p <= 1 - self._sure else "unclear"
        return f"{verdict} ({round(100 * max(p, 1 - p))}% sure); the screen mainly shows: {KINDS[a['kind']['choice']].lower()}"

    def wait_until(self, question: str, timeout_s: float, every_s: float, stop: threading.Event | None = None,
                   window_only: bool = False) -> bool:
        """Look every `every_s` until the answer is yes twice in a row (one glance can be fooled by a
        frame mid-redraw). -> False if `timeout_s` passes or `stop` is set first."""
        stop, streak, waited = stop or threading.Event(), 0, 0.0
        while waited <= timeout_s and not stop.is_set():
            streak = streak + 1 if self.look(question, window_only) >= self._sure else 0
            if streak == 2:
                return True
            stop.wait(every_s if not streak else min(every_s, 1.0))  # confirm a first yes quickly
            waited += every_s
        return False
