"""Tools: the machine itself (clock, status, volume, media keys, lock)."""
import ctypes
import subprocess
import time
from ctypes import wintypes

from .registry import tool

_KEYS = {"volume_up": 0xAF, "volume_down": 0xAE, "mute": 0xAD, "play_pause": 0xB3, "next": 0xB0, "previous": 0xB1}


def _tap(vk: int, times: int = 1):
    for _ in range(times):
        ctypes.windll.user32.keybd_event(vk, 0, 0, 0)
        ctypes.windll.user32.keybd_event(vk, 0, 2, 0)


@tool("Current local date and time.")
def get_time() -> str:
    return time.strftime("%A %d %B %Y, %I:%M %p")


@tool("Press a media key. action: volume_up, volume_down, mute, play_pause, next, previous.")
def media_key(action: str) -> str:
    if action not in _KEYS:
        return f"error: action must be one of {', '.join(_KEYS)}"
    _tap(_KEYS[action], 5 if action.startswith("volume") else 1)  # 5 taps = 10% volume
    return "done"


class _MEM(ctypes.Structure):
    _fields_ = [("len", wintypes.DWORD), ("load", wintypes.DWORD), ("total", ctypes.c_uint64),
                ("avail", ctypes.c_uint64), ("_", ctypes.c_uint64 * 5)]


class _POWER(ctypes.Structure):
    _fields_ = [("ac", ctypes.c_byte), ("flag", ctypes.c_byte), ("pct", ctypes.c_byte), ("_", ctypes.c_byte),
                ("life", wintypes.DWORD), ("full", wintypes.DWORD)]


@tool("Battery, memory and GPU status of this laptop.")
def system_status() -> str:
    mem, pw = _MEM(len=ctypes.sizeof(_MEM)), _POWER()
    ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(mem))
    ctypes.windll.kernel32.GetSystemPowerStatus(ctypes.byref(pw))
    out = [f"battery {pw.pct & 0xFF}% ({'charging' if pw.ac == 1 else 'on battery'})",
           f"RAM {mem.load}% used, {mem.avail / 2**30:.1f} GB free"]
    try:
        gpu = subprocess.run(["nvidia-smi", "--query-gpu=utilization.gpu,memory.used,memory.total,temperature.gpu",
                              "--format=csv,noheader"], capture_output=True, text=True, timeout=5,
                             creationflags=subprocess.CREATE_NO_WINDOW).stdout.strip()
        if gpu:
            out.append(f"GPU (util, VRAM used, total, temp): {gpu}")
    except OSError:
        pass
    return "; ".join(out)


@tool("Lock the screen.")
def lock_screen() -> str:
    ctypes.windll.user32.LockWorkStation()
    return "locked"
