"""Tools: the clipboard and the selection in whatever window the user is working in.
Together they let the agent act on text the user points at: "explain what I selected",
"fix the grammar of this and put it back", "copy that answer".
"""
import ctypes
import time
from ctypes import wintypes

from .registry import tool

# own handles, so the prototypes set here can't clash with other modules' use of ctypes.windll
_u, _k = ctypes.WinDLL("user32"), ctypes.WinDLL("kernel32")
_u.GetClipboardData.restype = _u.SetClipboardData.restype = ctypes.c_void_p
_u.SetClipboardData.argtypes = [wintypes.UINT, ctypes.c_void_p]
_k.GlobalAlloc.restype = _k.GlobalLock.restype = ctypes.c_void_p
_k.GlobalAlloc.argtypes = [wintypes.UINT, ctypes.c_size_t]
_k.GlobalLock.argtypes = _k.GlobalUnlock.argtypes = [ctypes.c_void_p]
_TEXT, _CTRL, _LIMIT = 13, 0x11, 6000  # CF_UNICODETEXT, VK_CONTROL, characters handed to the model


def _open() -> bool:
    for _ in range(10):  # another app may hold the clipboard for a moment
        if _u.OpenClipboard(None):
            return True
        time.sleep(0.02)
    return False


def get_text() -> str | None:
    """Clipboard text; '' if it holds no text; None if the clipboard stayed busy."""
    if not _open():
        return None
    try:
        h = _u.GetClipboardData(_TEXT)
        if not h:
            return ""
        text = ctypes.wstring_at(_k.GlobalLock(h))
        _k.GlobalUnlock(h)
        return text
    finally:
        _u.CloseClipboard()


def set_text(text: str) -> bool:
    data = (text + "\0").encode("utf-16-le")
    if not _open():
        return False
    try:
        _u.EmptyClipboard()
        h = _k.GlobalAlloc(0x0002, len(data))  # GMEM_MOVEABLE; the clipboard owns it after SetClipboardData
        ctypes.memmove(_k.GlobalLock(h), data, len(data))
        _k.GlobalUnlock(h)
        return bool(_u.SetClipboardData(_TEXT, h))
    finally:
        _u.CloseClipboard()


def _ctrl(key: str) -> None:
    for vk, up in ((_CTRL, 0), (ord(key), 0), (ord(key), 2), (_CTRL, 2)):
        _u.keybd_event(vk, 0, up, 0)


@tool("Read the text currently on the clipboard.")
def read_clipboard() -> str:
    text = get_text()
    return "error: clipboard busy" if text is None else text[:_LIMIT] or "clipboard has no text"


@tool("Put text on the clipboard, e.g. an answer, a rewrite or a translation the user asked to copy.")
def write_clipboard(text: str) -> str:
    return f"copied {len(text)} characters" if set_text(text) else "error: clipboard busy"


@tool("Get the text the user has selected (highlighted) in the window they are working in. "
      "Use for 'this', 'what I selected', 'the highlighted text'.")
def copy_selection() -> str:
    before = get_text()
    set_text("")
    _ctrl("C")
    for _ in range(20):  # the app answers Ctrl+C within a few tens of ms
        time.sleep(0.03)
        if (text := get_text()):
            return text[:_LIMIT]
    if before:
        set_text(before)  # nothing was selected: leave the clipboard as it was
    return "nothing is selected"


@tool("Type text into the window the user is working in, replacing what is selected there. "
      "Use after rewriting or fixing the selection, or when asked to paste or insert something.")
def paste_text(text: str) -> str:
    if not set_text(text):
        return "error: clipboard busy"
    time.sleep(0.05)
    _ctrl("V")
    return f"pasted {len(text)} characters"
