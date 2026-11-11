"""Tools: launch things."""
import os
import webbrowser
from pathlib import Path
from urllib.parse import quote_plus

from .registry import tool

_MENUS = [Path(os.environ.get("ProgramData", "C:/ProgramData")) / "Microsoft/Windows/Start Menu/Programs",
          Path(os.environ.get("AppData", "")) / "Microsoft/Windows/Start Menu/Programs"]


# Windows' own apps have no Start Menu shortcut to find, and their everyday names are not their commands
_BUILT_IN = {"calculator": "calc", "paint": "mspaint", "fileexplorer": "explorer", "explorer": "explorer",
             "settings": "ms-settings:", "taskmanager": "taskmgr", "terminal": "wt", "commandprompt": "cmd",
             "snippingtool": "snippingtool", "controlpanel": "control"}


@tool("Open an app, file or folder by name or path, e.g. 'notepad', 'chrome', 'downloads'.")
def open_app(name: str) -> str:
    from .files import resolve
    path = resolve(name)
    if path.exists():
        os.startfile(path)
        return f"opened {path}"
    want = name.lower().replace(" ", "").removeprefix("the")
    if want in _BUILT_IN:
        os.startfile(_BUILT_IN[want])
        return f"opened {name}"
    shortcuts = [lnk for menu in _MENUS for lnk in menu.rglob("*.lnk")]  # installed apps that aren't on PATH
    for exact in (True, False):          # "calculator" must not open "Calculator Tools" when both could match
        for lnk in shortcuts:
            stem = lnk.stem.lower().replace(" ", "")
            if stem == want if exact else want in stem:
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
