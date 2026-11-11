"""Brick: eyes. Grabs what is on the screen (or just the window in front) as a PNG, for a model to look at,
and lists the titles of the open windows: the one thing about the screen the OS knows exactly.
Plain Win32 and zlib: no imaging library.
"""
import ctypes
import struct
import zlib
from ctypes import wintypes

import numpy as np

_u, _g = ctypes.WinDLL("user32"), ctypes.WinDLL("gdi32")
_u.GetDC.restype = _g.CreateCompatibleDC.restype = _g.CreateCompatibleBitmap.restype = ctypes.c_void_p
_g.SelectObject.restype = ctypes.c_void_p
_u.GetForegroundWindow.restype = wintypes.HWND
_u.ReleaseDC.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
_g.CreateCompatibleDC.argtypes = _g.DeleteDC.argtypes = _g.DeleteObject.argtypes = [ctypes.c_void_p]
_g.CreateCompatibleBitmap.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_int]
_g.SelectObject.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
_g.BitBlt.argtypes = [ctypes.c_void_p] + [ctypes.c_int] * 4 + [ctypes.c_void_p, ctypes.c_int, ctypes.c_int, wintypes.DWORD]
_g.GetDIBits.argtypes = [ctypes.c_void_p, ctypes.c_void_p, wintypes.UINT, wintypes.UINT, ctypes.c_void_p,
                         ctypes.c_void_p, wintypes.UINT]


class _BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [("size", wintypes.DWORD), ("width", ctypes.c_long), ("height", ctypes.c_long),
                ("planes", wintypes.WORD), ("bits", wintypes.WORD), ("compression", wintypes.DWORD),
                ("image", wintypes.DWORD), ("xppm", ctypes.c_long), ("yppm", ctypes.c_long),
                ("used", wintypes.DWORD), ("important", wintypes.DWORD)]


def titles(limit: int = 8) -> list[str]:
    """Titles of the visible windows, front first."""
    found: list[str] = []

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def each(hwnd, _):
        if _u.IsWindowVisible(hwnd) and _u.GetWindowTextLengthW(hwnd):
            text = ctypes.create_unicode_buffer(160)
            _u.GetWindowTextW(hwnd, text, 160)
            found.append(text.value)
        return len(found) < limit
    _u.EnumWindows(each, 0)
    return found


def pixels(window_only: bool = False) -> np.ndarray:
    """-> the screen (or the foreground window) as an RGB array, height x width x 3."""
    x, y, w, h = 0, 0, _u.GetSystemMetrics(0), _u.GetSystemMetrics(1)
    if window_only and (hwnd := _u.GetForegroundWindow()):
        r = wintypes.RECT()
        _u.GetWindowRect(hwnd, ctypes.byref(r))
        x, y = max(0, r.left), max(0, r.top)
        w, h = max(1, min(w, r.right) - x), max(1, min(h, r.bottom) - y)
    screen = _u.GetDC(None)
    dc = _g.CreateCompatibleDC(screen)
    bitmap = _g.CreateCompatibleBitmap(screen, w, h)
    old = _g.SelectObject(dc, bitmap)
    try:
        _g.BitBlt(dc, 0, 0, w, h, screen, x, y, 0x00CC0020 | 0x40000000)  # SRCCOPY | CAPTUREBLT (layered windows too)
        info = _BITMAPINFOHEADER(ctypes.sizeof(_BITMAPINFOHEADER), w, -h, 1, 32, 0)  # negative height = top row first
        raw = ctypes.create_string_buffer(w * h * 4)
        _g.GetDIBits(dc, bitmap, 0, h, raw, ctypes.byref(info), 0)
    finally:
        _g.SelectObject(dc, old)
        _g.DeleteObject(bitmap)
        _g.DeleteDC(dc)
        _u.ReleaseDC(None, screen)
    return np.frombuffer(raw, np.uint8).reshape(h, w, 4)[:, :, 2::-1]  # BGRA -> RGB


def png(rgb: np.ndarray) -> bytes:
    h, w, _ = rgb.shape
    rows = np.concatenate([np.zeros((h, 1), np.uint8), rgb.reshape(h, w * 3)], axis=1).tobytes()  # filter byte 0

    def chunk(kind: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(rows, 1)) + chunk(b"IEND", b""))


def grab(window_only: bool = False, max_side: int = 1280) -> bytes:
    """A PNG of the screen or the foreground window, shrunk (by averaging) so its longer side is <= max_side."""
    rgb = pixels(window_only)
    n = -(-max(rgb.shape[:2]) // max_side)  # whole-number shrink factor
    if n > 1:
        h, w = rgb.shape[0] // n * n, rgb.shape[1] // n * n
        rgb = rgb[:h, :w].reshape(h // n, n, w // n, n, 3).mean((1, 3)).astype(np.uint8)
    return png(np.ascontiguousarray(rgb))
