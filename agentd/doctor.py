"""`run.ps1 --doctor`: check, without starting anything, that everything the daemon needs is in place,
and say what to do about each thing that is not.
"""
from pathlib import Path

from .kit import Kit, KitError


def report(cfg: dict, root: Path) -> int:
    """Prints one line per check. -> the number of problems that would stop the daemon (0 = good to go)."""
    problems = 0

    def line(ok, what: str, fix: str = "", needed: bool = True) -> None:
        nonlocal problems
        problems += bool(needed and not ok)
        print(f"  [{'ok' if ok else '!!' if needed else '--'}] {what}" + (f"\n       -> {fix}" if fix and not ok else ""))

    k = cfg["kit"]
    kit = Kit(k["url"])
    up = kit.healthy()
    print("Inference kit")
    line(up, f"answering at {k['url']}", "start it: run.ps1 does this, or start.ps1 in the kit's folder")
    try:
        served = kit.models() if up else set()
    except KitError:
        served = set()
    for key, what in (("agent_role", "the LLM"), ("tts_role", "speech")):
        line(k[key] in served, f"role '{k[key]}' ({what})", "add a model for it in the kit: manage.ps1 add / role", up)
    line(k["stt_role"] in served or "stt" in served, "role 'stt' (speech to text)", "add a speech-to-text model in the kit", up)
    line(k["stt_role"] in served, f"role '{k['stt_role']}' (faster on short commands)", "optional: run setup-kit.ps1", False)
    line(cfg["router"]["embed_role"] in served, f"role '{cfg['router']['embed_role']}' (fast path, file search, memory)",
         "optional: run setup-kit.ps1 (without it those three switch themselves off)", False)
    line(cfg["decide"]["model"] in served, f"model '{cfg['decide']['model']}' (tool choice, screen)",
         "optional: run setup-kit.ps1", False)

    print("Sound")
    try:
        import sounddevice as sd
        mic, out = sd.query_devices(kind="input"), sd.query_devices(kind="output")
        line(True, f"microphone: {mic['name']}")
        line(True, f"speakers:   {out['name']}")
    except Exception as e:
        line(False, "a microphone and speakers", f"Windows reports: {e}")

    print("Local files")
    kws = root / "models" / "kws" / "tokens.txt"
    line(kws.exists(), "wake-word model", "run setup.ps1")
    line((root / "models" / "turn" / "smart-turn-v3.2-cpu.onnx").exists(), "end-of-turn model",
         "optional: run setup.ps1 (without it a fixed pause ends a command)", False)
    chimera = root / "engines" / "chimera"
    line((chimera / "chimera-say.exe").exists(), "Chimera voice", "optional: run setup-chimera.ps1", False)
    line((chimera / "head.js").exists(), "Chimera head for the overlay", "optional: run setup-chimera.ps1", False)
    meta = root / "index" / "meta.json"
    line(meta.exists(), "file-search index" + (f" ({meta.stat().st_size // 2**20} MB)" if meta.exists() else ""),
         "optional: run.ps1 --index (it is also built in the background at start)", False)
    try:
        import webview  # noqa: F401
        line(True, "overlay window (WebView2)")
    except Exception as e:
        line(False, "overlay window", f"optional: {e}; run with --no-overlay", False)

    print(f"\n{'Good to go.' if not problems else f'{problems} thing(s) to fix first.'}  [--] marks optional extras that are missing.")
    return problems
