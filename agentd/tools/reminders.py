"""Tools: timers and reminders. They survive a restart (kept in `store`); one that came due while the
assistant was off is announced when it next starts.

install(host, store) registers the tools and returns the scheduler; call .start() once the assistant can speak.
"""
import json
import re
import threading
import time
from pathlib import Path

from .registry import tool

_CLOCK = re.compile(r"^\s*(\d{1,2})(?:[:.](\d{2}))?\s*(am|pm|a\.m\.|p\.m\.)?\s*$", re.I)


def clock_time(text: str, now: float) -> float | None:
    """'18:30', '6 pm', '6:30pm' -> the next time the clock shows that, as epoch seconds (None if unreadable)."""
    m = _CLOCK.match(text)
    if not m:
        return None
    hour, minute, half = int(m[1]), int(m[2] or 0), (m[3] or "").lower()[:1]
    if half == "p" and hour < 12:
        hour += 12
    if half == "a" and hour == 12:
        hour = 0
    if hour > 23 or minute > 59:
        return None
    day = time.localtime(now)
    at = time.mktime((day.tm_year, day.tm_mon, day.tm_mday, hour, minute, 0, 0, 0, -1))
    return at if at > now else at + 86400


class Reminders:
    def __init__(self, host, store: Path):
        self._host, self._store, self._wake = host, store, threading.Event()
        try:
            self.items: list[dict] = json.loads(store.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            self.items = []

    def add(self, about: str, at: float) -> None:
        self.items.append({"about": about, "at": at})
        self._save()
        self._wake.set()

    def cancel(self, about: str = "") -> int:
        keep = [r for r in self.items if about and about.lower() not in r["about"].lower()]
        gone = len(self.items) - len(keep)
        self.items = keep
        self._save()
        return gone

    def _save(self) -> None:
        self._store.parent.mkdir(parents=True, exist_ok=True)
        self._store.write_text(json.dumps(self.items), encoding="utf-8")

    def start(self) -> None:
        threading.Thread(target=self._run, daemon=True).start()

    def _run(self) -> None:
        while True:
            now = time.time()
            for r in [r for r in self.items if r["at"] <= now]:
                self.items.remove(r)
                self._save()
                late = now - r["at"]
                self._host.announce(f"A reminder the user set is due now: {r['about']}" if late < 90 else
                                    f"A reminder came due at {time.strftime('%H:%M', time.localtime(r['at']))} "
                                    f"while the assistant was not running: {r['about']}")
            due = min((r["at"] for r in self.items), default=now + 3600)
            self._wake.wait(max(0.2, min(due - time.time(), 3600)))
            self._wake.clear()


def install(host, store: Path) -> Reminders:
    reminders = Reminders(host, store)

    @tool("Set a timer or a reminder: 'set a 5 minute timer', 'remind me in an hour to stretch', 'at 6 pm remind me "
          "to call mom'. about: what it is for, in a few words. in_minutes: how long from now; or at: a clock time "
          "such as '18:30' or '6 pm'.")
    def remind(about: str, in_minutes: float = 0, at: str = "") -> str:
        now = time.time()
        when = clock_time(at, now) if at else now + in_minutes * 60 if in_minutes > 0 else None
        if when is None:
            return "error: give in_minutes (a number above 0) or at (a clock time like '18:30' or '6 pm')"
        reminders.add(about, when)
        return f"set for {time.strftime('%H:%M', time.localtime(when))} ({round((when - now) / 60)} minutes from now)"

    @tool("List the timers and reminders that are still waiting.")
    def list_reminders() -> str:
        rows = sorted(reminders.items, key=lambda r: r["at"])
        return "\n".join(f"{time.strftime('%H:%M', time.localtime(r['at']))}: {r['about']}" for r in rows) or "none"

    @tool("Cancel timers and reminders. about: words from the one to cancel; leave empty to cancel all of them.")
    def cancel_reminders(about: str = "") -> str:
        return f"cancelled {reminders.cancel(about)}"
    return reminders
