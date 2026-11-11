"""Brick: the on-screen presence. A small frameless always-on-top window in the top-right corner that
appears when the agent wakes and hides shortly after it goes idle. Fills the Ui slot.

A persona can bring its own look, a "skin": one script the page loads when that persona first wakes
(contract: the `ui.skin` comment in web/index.html).

When a tool finds files the page lists them as a card; clicking a row calls back into Python
(`on_open`, set by the app), and the card keeps the window up for `card_s` instead of `linger_s`.

The page (web/index.html) is the whole look; this file only owns the window and forwards events to
`ui.on(event)`. Uses the WebView2 runtime that ships with Windows, so nothing is bundled.
"""
import ctypes
import json
import threading
import time
from collections import deque
from ctypes import wintypes
from pathlib import Path
from typing import Callable

import webview

PAGE = Path(__file__).parent / "web" / "index.html"


class _Bridge:
    """What the page may call: window.pywebview.api.open(path)."""

    def __init__(self, overlay):
        self._overlay = overlay

    def open(self, path):
        self._overlay.on_open(str(path))


class Overlay:
    def __init__(self, width: int = 320, height: int = 280, margin: int = 0, linger_s: float = 4.0,
                 skins: dict[str, Path] | None = None, card_s: float = 20.0):
        self.on_open: Callable[[str], None] = lambda path: None  # the app decides what may be opened
        self._card_s, self._hold = card_s, 0.0  # _hold: don't hide before this time (a card is showing)
        self._skins = {name: path.as_uri() for name, path in (skins or {}).items()}
        self._linger, self._ready, self._hide_timer, self._shown = linger_s, threading.Event(), None, False
        self._persona = None  # remembered while hidden, replayed when the window appears
        self._margin = margin
        self._queue, self._wake, self._gen = deque(), threading.Condition(), 0  # see emit / _sender
        threading.Thread(target=self._sender, daemon=True).start()
        self._win = webview.create_window(
            "agentd", PAGE.as_uri(), width=width, height=height, x=0, y=0,  # _place() moves it to the corner
            frameless=True, easy_drag=True, on_top=True, hidden=True, focus=False, resizable=False,
            background_color="#050506", js_api=_Bridge(self))
        self._win.events.loaded += self._on_loaded

    def _place(self) -> None:
        """Pin the visible card `margin` px from the top-right corner of the work area. Done with Win32 in
        real pixels: pywebview scales a window's size on a scaled display but not its position, and a
        window's rectangle can include an invisible border."""
        try:
            user, hwnd = ctypes.windll.user32, ctypes.c_void_p(self._win.native.Handle.ToInt64())
            win, card, area = wintypes.RECT(), wintypes.RECT(), wintypes.RECT()
            user.GetWindowRect(hwnd, ctypes.byref(win))
            if ctypes.windll.dwmapi.DwmGetWindowAttribute(hwnd, 9, ctypes.byref(card), ctypes.sizeof(card)):
                card = win  # 9 = DWMWA_EXTENDED_FRAME_BOUNDS, the part you can see
            user.SystemParametersInfoW(48, 0, ctypes.byref(area), 0)  # SPI_GETWORKAREA: screen minus taskbar
            m = round(self._margin * user.GetDpiForWindow(hwnd) / 96)
            user.SetWindowPos(hwnd, None, area.right - m - (card.right - win.left),
                              area.top + m - (card.top - win.top), 0, 0, 0x0015)  # no size, z-order or focus change
        except Exception:
            pass  # stays where Windows put it

    def run(self, worker: Callable[[], None]) -> None:
        """Blocks on the UI loop (must be the main thread); `worker` runs beside it. Returns when either ends."""
        def work():
            try:
                worker()
            finally:
                self._win.destroy()
        webview.start(lambda: threading.Thread(target=work, daemon=True).start())

    def emit(self, event: str, **data) -> None:
        """Fire-and-forget (the Ui contract): queued for the sender thread, so the caller never waits on the
        page. The speaker's play loop sends a level 30 times a second between audio blocks; a level not yet
        sent is replaced by the newer one, never queued behind it."""
        with self._wake:
            if event == "level" and self._queue and self._queue[-1][0] == "level":
                self._queue[-1] = (event, data)
            else:
                self._queue.append((event, data))
            self._wake.notify()

    def _sender(self) -> None:
        """The only thread that touches the page and shows or hides the window: events arrive in order,
        and a hide can't land in the middle of showing for a new turn."""
        while True:
            with self._wake:
                while not self._queue:
                    self._wake.wait()
                event, data = self._queue.popleft()
            try:
                self._deliver(event, data)
            except Exception:
                pass  # window closing

    def _deliver(self, event: str, data: dict) -> None:
        if not self._ready.wait(10):  # only the first events ever wait, while the page loads
            return
        if event == "_hide":
            if data["gen"] == self._gen:  # no state event came in since the timer was set
                self._hide()
            return
        if event == "heard":
            self._hold = 0.0  # a new request: the page closes the old card, so it no longer holds the window
        if event == "persona":
            if data["name"] in self._skins:
                data["skin"] = self._skins[data["name"]]
            self._persona = data
        if event == "card":
            self._hold = time.time() + self._card_s
        if event == "state":
            self._on_state(data["s"])
        if self._shown:
            self._js({"type": event, **data})

    def _js(self, obj: dict) -> None:
        try:
            self._win.evaluate_js(f"ui.on({json.dumps(obj)})")
        except Exception:
            pass  # window closing

    def _on_loaded(self):
        try:  # Windows 11 rounded corners (DWMWA_WINDOW_CORNER_PREFERENCE = round)
            hwnd = self._win.native.Handle.ToInt64()
            ctypes.windll.dwmapi.DwmSetWindowAttribute(ctypes.c_void_p(hwnd), 33, ctypes.byref(ctypes.c_int(2)), 4)
        except Exception:
            pass
        self._place()
        self._ready.set()

    def _on_state(self, s: str) -> None:
        self._gen += 1
        if self._hide_timer:
            self._hide_timer.cancel()
        if s == "idle":
            self._hide_in(max(self._linger, self._hold - time.time()))
        elif not self._shown:
            self._hold = 0.0
            self._shown = True
            self._win.show()
            self._place()
            self._js({"type": "visible", "v": True})
            if self._persona:
                self._js({"type": "persona", **self._persona})

    def _hide_in(self, seconds: float) -> None:
        self._hide_timer = threading.Timer(seconds, lambda gen=self._gen: self.emit("_hide", gen=gen))
        self._hide_timer.daemon = True
        self._hide_timer.start()

    def _hide(self):
        self._js({"type": "visible", "v": False})
        self._shown = False
        self._win.hide()
