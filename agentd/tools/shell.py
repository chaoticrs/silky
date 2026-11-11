"""Tools: arbitrary commands. Always risky."""
import subprocess

from .registry import tool


@tool("Run a PowerShell command and return its output. Use only when no other tool fits.", risky=True)
def run_powershell(command: str) -> str:
    r = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", command], capture_output=True,
                       text=True, timeout=30, creationflags=subprocess.CREATE_NO_WINDOW)
    return (r.stdout + r.stderr).strip()[:3000] or f"exit code {r.returncode}"
