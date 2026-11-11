"""Tools: look at and manage files."""
import ctypes
import os
from ctypes import wintypes
from pathlib import Path

from .registry import tool

HOME = Path.home()
_PLACES = {n: HOME / n.capitalize() for n in ("desktop", "documents", "downloads", "pictures", "music", "videos")}
NOTES = HOME / "Documents" / "agent-notes.md"


_FOUND: dict[str, Path] = {}  # file name -> where it is, for files a search tool has just listed
LAST: list[Path] = []         # the most recent listing, for a display that wants to show it


def listing(paths: list) -> str:
    """Found files as the model should see (and say) them: 'name (in Folder)', never a full path.
    The names are remembered, so 'open <name>' works afterwards without the model knowing the path."""
    if len(_FOUND) > 200:
        _FOUND.clear()
    LAST[:] = [Path(p) for p in paths]
    for p in LAST:
        _FOUND[p.name.lower()] = p
    return "\n".join(f"{Path(p).name} (in {Path(p).parent.name})" for p in paths)


def resolve(path: str) -> Path:
    """'downloads', '~/x', '%TEMP%/y', relative-to-home and absolute paths all work, and so does the
    bare name of a file a search has just listed."""
    p = path.strip().strip('"')
    if p.lower() in _PLACES:
        return _PLACES[p.lower()]
    if p.lower() in _FOUND:
        return _FOUND[p.lower()]
    q = Path(os.path.expandvars(os.path.expanduser(p)))
    return q if q.is_absolute() else HOME / q


@tool("List the files in a folder ('desktop', 'downloads', or a path), newest first.")
def list_folder(path: str) -> str:
    items = sorted(resolve(path).iterdir(), key=lambda f: f.stat().st_mtime, reverse=True)[:40]
    return "\n".join(f.name + ("/" if f.is_dir() else "") for f in items) or "empty"


@tool("Find files by part of their name in the user's Desktop, Documents and Downloads.")
def find_files(name: str) -> str:
    hits = []
    for root in ("desktop", "documents", "downloads"):
        for f in _PLACES[root].rglob(f"*{name}*"):
            hits.append(f)
            if len(hits) >= 12:
                return listing(hits)
    return listing(hits) or "nothing found"


@tool("Read the start of a text file.")
def read_text_file(path: str) -> str:
    return resolve(path).read_text(encoding="utf-8", errors="replace")[:3000]


@tool("Save a note or reminder for the user.")
def write_note(text: str) -> str:
    with NOTES.open("a", encoding="utf-8") as f:
        f.write(f"- {text}\n")
    return f"saved to {NOTES}"


class _SHFILEOP(ctypes.Structure):
    _fields_ = [("hwnd", wintypes.HWND), ("wFunc", wintypes.UINT), ("pFrom", wintypes.LPCWSTR),
                ("pTo", wintypes.LPCWSTR), ("fFlags", ctypes.c_ushort), ("fAborted", wintypes.BOOL),
                ("hNameMappings", ctypes.c_void_p), ("lpszProgressTitle", wintypes.LPCWSTR)]


@tool("Move a file or folder to the Recycle Bin.", risky=True)
def delete_file(path: str) -> str:
    p = resolve(path)
    if not p.exists():
        return f"error: {p} does not exist"
    op = _SHFILEOP(None, 3, str(p) + "\0", None, 0x0040 | 0x0010 | 0x0400, False, None, None)  # delete, undo+silent
    code = ctypes.windll.shell32.SHFileOperationW(ctypes.byref(op))
    return f"moved {p.name} to the Recycle Bin" if code == 0 else f"error: shell code {code}"
