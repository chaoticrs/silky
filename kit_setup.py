"""Give the inference kit the three extras the assistant uses beyond the kit's own defaults (setup-kit.ps1 runs this).

  embed        a small embedding model on the CPU: instant commands, file search by meaning, memory
  stt-command  the kit's speech-to-text model again, tuned for short English commands (about 6x faster)
  d1           LiquidAI's decision model with its vision projector: picks tools, reads the screen

Each is skipped if it is already there, so running this twice is harmless. Without them the assistant still
works: those features switch themselves off. Downloads about 1.6 GB in total, through the kit's own manager.
"""
import json
import os
import subprocess
import sys
import tomllib
from pathlib import Path

HERE = Path(__file__).resolve().parent


def find_kit() -> Path:
    cfg = tomllib.loads((HERE / "config.toml").read_text(encoding="utf-8"))["kit"]
    for folder in (cfg.get("folder", ""), "../llama-swap-kit", "../LocalAI"):
        kit = (HERE / folder).resolve()
        if folder and (kit / "manage.ps1").exists():
            return kit
    sys.exit("llama-swap-kit was not found next to this folder. Clone and set it up first:\n"
             "  https://github.com/chaoticrs/llama-swap-kit   (or point [kit] folder in config.toml at it)")


def main() -> None:
    kit = find_kit()
    registry = kit / "models" / "registry.json"
    if not registry.exists():
        sys.exit(f"{kit} is not set up yet. Run its scripts\\setup.ps1 first.")
    load = lambda: json.loads(registry.read_text(encoding="utf-8"))
    manage = lambda *args: subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File",
                                           str(kit / "manage.ps1"), *args], check=True)

    def patch(change) -> None:
        reg = load()
        change(reg)
        registry.write_text(json.dumps(reg, indent=2), encoding="utf-8")

    reg = load()
    print(f"kit: {kit}")
    for role in ("agent", "stt", "tts"):
        if role not in reg["roles"]:
            print(f"  !! the kit has no '{role}' role yet; finish its setup (scripts\\setup.ps1) before starting the assistant")

    if "embed" in reg["roles"]:
        print("  embed: already there")
    else:
        print("  embed: adding bge-small (35 MB)")
        manage("add", "CompendiumLabs/bge-small-en-v1.5-gguf", "--quant", "Q8_0", "--id", "bge-small", "--cpu", "--always-on",
               "--args=--embedding -c 512")
        manage("role", "embed", "bge-small")

    reg = load()
    if "stt-command" in reg["roles"]:
        print("  stt-command: already there")
    elif reg["models"].get(reg["roles"].get("stt"), {}).get("backend") != "whisper":
        print("  stt-command: skipped (the kit's stt model is not whisper.cpp); the assistant will use the 'stt' role")
    else:
        threads = max(2, (os.cpu_count() or 4) // 2)
        print(f"  stt-command: the kit's whisper model with short-command settings ({threads} threads)")

        def add(reg):
            base = reg["models"][reg["roles"]["stt"]]
            reg["models"]["whisper-command"] = base | {
                "args": f"-l en -t {threads} -bs 1 -nf -ac 512",
                "description": "the stt model tuned for short English voice commands (max ~10 s of audio)"}
            reg["roles"]["stt-command"] = "whisper-command"
        patch(add)

    reg = load()
    if "d1" in reg["models"]:
        print("  d1: already there")
    else:
        print("  d1: adding LiquidAI/d1-2B-GGUF, 4-bit, with its projector (about 1.4 GB)")
        manage("add", "LiquidAI/d1-2B-GGUF", "--quant", "Q4_K_M", "--id", "d1")
        small = load().get("hardware", {}).get("vram_total_mb", 0) <= 4608
        if small:   # a 4 GB card: small buffers and a fixed budget, or the kit swaps d1 and the LLM on every step
            print("       4 GB card: giving d1 small buffers and a fixed 1850 MiB budget so it can sit beside the LLM")
            patch(lambda reg: reg["models"]["d1"].update(args="-ngl 99 -b 2048 -ub 2048 -c 4096", vram_mb=1850, mem_manual=True))
            agent = load()["models"][load()["roles"]["agent"]]
            print(f"       your agent model is budgeted {agent.get('vram_mb')} MiB; both stay loaded only if the two budgets fit "
                  f"in {load()['pools']['vram']} MiB.\n       If they do not, the kit swaps them (slow): use a smaller agent model, "
                  "or set decide.enabled = false in config.toml.")
    manage("render")
    print("done. Restart the kit if it is running, then:  .\\run.ps1 --doctor")


if __name__ == "__main__":
    main()
