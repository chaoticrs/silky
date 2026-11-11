"""Tools: the screen. Ask a yes/no question about what is on it, wait in the background until something
shows up, and confirm on screen that an "open ..." really happened.

install(sight, host, ...) registers the tools and returns the check for Toolbox(check=...).
`sight` is the Sight brick (anything with describe / wait_until), `host` the Host slot.
"""
import threading
import time
from typing import Callable

from .registry import tool

# tool -> the question that tells whether it worked ({argument} names are filled from the call)
VISIBLE = {"open_app": "Is {name} open in a window on this screen?",
           "open_url": "Is a web browser in front, showing or loading a web page?",
           "web_search": "Is a web browser in front, showing or loading search results?"}


def install(sight, host, every_s: float = 4, timeout_min: float = 30, verify_s: float = 6,
            log: Callable[[str], None] = print) -> Callable[[str, dict, str], str]:
    watches: dict[str, threading.Event] = {}
    following = threading.local()  # set on a thread that is carrying out a watch's follow-up

    def watch(condition: str, then: str, stop: threading.Event) -> None:
        try:
            met = sight.wait_until(f"Is this true of what the screen shows: {condition}?", timeout_min * 60, every_s, stop)
        except RuntimeError as e:
            return log(f"  watch failed: {e}")
        if stop.is_set():
            return
        watches.pop(condition, None)
        log(f"  watch {'met' if met else 'timed out'}: {condition}")
        following.on = True
        host.announce(f"What the user asked to be told about has now happened on the screen: {condition}" if met else
                      f"You watched the screen for {timeout_min:g} minutes and this never happened: {condition}",
                      then if met else "")

    @tool("Look at the user's screen once, right now, and answer a yes/no question about what is visible "
          "on it, e.g. 'is there an error message', 'is a video playing'. Not for waiting.")
    def check_screen(question: str) -> str:
        return sight.describe(question)

    @tool("Wait for something to happen on the screen and tell the user when it does: for 'tell me when...', "
          "'let me know when...', 'wait until...', 'when X finishes, do Y'. condition: what to wait for, as "
          "a statement, e.g. 'the download has finished'. then: optional command to carry out at that "
          "moment, e.g. 'lock the screen'.")
    def watch_screen(condition: str, then: str = "") -> str:
        if getattr(following, "on", False):  # a watch's own follow-up must not start another watch
            return "not started: this already is the follow-up of a watch; just tell the user"
        if condition in watches:
            return "already watching for that"
        stop = watches[condition] = threading.Event()
        threading.Thread(target=watch, args=(condition, then, stop), daemon=True).start()
        return (f"started: the screen is now checked every {every_s:g} seconds for up to {timeout_min:g} minutes and "
                "the user will be told automatically. Do not check the screen yourself; just say you will let them know.")

    @tool("Stop watching the screen.")
    def stop_watching() -> str:
        n = len(watches)
        for stop in watches.values():
            stop.set()
        watches.clear()
        return f"stopped {n} watch" + ("" if n == 1 else "es")

    def check(name: str, args: dict, result: str) -> str:
        """After a tool that should change what is on screen: look, and add what was seen to its result."""
        if not verify_s or name not in VISIBLE:
            return result
        t = time.time()
        try:
            seen = sight.wait_until(VISIBLE[name].format(**args), verify_s, 0.5)
        except (RuntimeError, KeyError):
            return result
        log(f"  looked: {'visible' if seen else 'not visible'} after {time.time() - t:.1f}s")
        return result + (" (confirmed: it is visible on screen)" if seen else
                         f" (warning: {verify_s:g} seconds later it is still not visible on screen;"
                         " it may have failed or be slow to start)")
    return check
