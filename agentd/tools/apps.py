"""Tools: launch things."""
import os
import webbrowser
from pathlib import Path
from urllib.parse import quote_plus

from .registry import tool

_MENUS = [Path(os.environ.get("ProgramData", "C:/ProgramData")) / "Microsoft/Windows/Start Menu/Programs",
          Path(os.environ.get("AppData", "")) / "Microsoft/Windows/Start Menu/Programs"]


@tool("Open an app, file or folder by name or path, e.g. 'notepad', 'chrome', 'downloads'.")
def open_app(name: str) -> str:
    from .files import resolve
    path = resolve(name)
    if path.exists():
        os.startfile(path)
        return f"opened {path}"
    want = name.lower().replace(" ", "")
    for menu in _MENUS:  # Start Menu shortcuts cover installed apps that aren't on PATH
        for lnk in menu.rglob("*.lnk"):
            if want in lnk.stem.lower().replace(" ", ""):
                os.startfile(lnk)
                return f"opened {lnk.stem}"
    os.startfile(name)  # last resort: ShellExecute resolves PATH and registered apps; raises if unknown
    return f"opened {name}"


@tool("Open a web page in the default browser.")
def open_url(url: str) -> str:
    webbrowser.open(url if "://" in url else "https://" + url)
    return "opened"


@tool("Open a web search in the browser. Only when the user asks to search or look something up online.")
def web_search(query: str) -> str:
    webbrowser.open("https://duckduckgo.com/?q=" + quote_plus(query))
    return "search opened in browser"
