"""Brick: the Chimera voice (physical-modelling synth). Fills the Voice slot.

Keeps engines/chimera/chimera-say.exe running (its contract is at the top of
engines/chimera-say/src/main.rs) and holds the adjustable voice settings, which persist in voice.json.
Beyond the Voice slot it offers motion(text): what the voice's body did while saying a sentence, for a
display that can replay it (the overlay's Chimera head).
"""
import json
import re
import subprocess
import tempfile
import wave
from pathlib import Path

import numpy as np

# setting -> (min, max, engine default). pitch 0 = the body's natural pitch.
RANGES = {"female": (0, 1, 0), "child": (0, 1, 0), "pitch_hz": (0, 400, 0), "rate": (0.5, 2, 1),
          "breathiness": (0, 1, 0.15), "tension": (0, 1, 0.5), "roughness": (0, 1, 0.1), "fry": (0, 1, 0),
          "brightness": (0, 1, 0.25), "vibrato": (0, 100, 0)}
PRESETS = {"default": {}, "male": {}, "female": {"female": 1}, "child": {"child": 1}}
_TIME = re.compile(r"\b(\d{1,2}):(\d{2})\b")


class ChimeraVoice:
    def __init__(self, folder: Path):
        self._exe, self._dict, self._state = folder / "chimera-say.exe", folder / "cmudict.txt.gz", folder / "voice.json"
        if not self._exe.exists():
            raise FileNotFoundError(f"{self._exe} is missing; build it with setup-chimera.ps1")
        self._wav = Path(tempfile.gettempdir()) / "agentd-chimera.wav"
        self._track = self._wav.with_suffix(".json")
        self._motions: dict[str, str] = {}  # sentence -> its motion track, until someone takes it
        self._proc = None
        self.settings = {k: d for k, (_, _, d) in RANGES.items()}
        if self._state.exists():
            self.settings.update(json.loads(self._state.read_text()))

    def adjust(self, preset: str = "", **changes) -> str:
        """Apply a preset and/or individual settings (None = leave alone); values are clamped.
        -> a description of the voice now, for the model to relay."""
        if preset:
            if preset not in PRESETS:
                return f"error: preset must be one of {', '.join(PRESETS)}"
            self.settings = {k: d for k, (_, _, d) in RANGES.items()} | PRESETS[preset]
        for k, v in changes.items():
            if v is not None:
                lo, hi, _ = RANGES[k]
                self.settings[k] = min(hi, max(lo, float(v)))
        self._state.write_text(json.dumps(self.settings))
        return "voice is now " + ", ".join(f"{k} {v:g}" for k, v in self.settings.items())

    def motion(self, text: str) -> str | None:
        """The motion track (JSON, format in chimera-say's contract) of a sentence synth() rendered; once."""
        return self._motions.pop(text, None)

    def synth(self, text):
        s, said = self.settings, text
        text = _TIME.sub(lambda m: f"{m[1]} {'o clock' if m[2] == '00' else m[2]}", text).replace("%", " percent")
        req = {"text": text, "out": str(self._wav), "motion": str(self._track), "female": s["female"], "child": s["child"], "rate": s["rate"],
               "source": {"breathiness": s["breathiness"], "tension": s["tension"], "roughness": s["roughness"],
                          "fry": s["fry"], "brightness": s["brightness"], "vibratoDepth": s["vibrato"]}}
        if s["pitch_hz"]:
            req["f0"] = max(60, s["pitch_hz"])
        reply = self._ask(req)
        if not reply.get("ok"):
            raise RuntimeError(f"chimera: {reply.get('error')}")
        if len(self._motions) > 8:  # nobody is taking them (no display): don't pile up
            self._motions.clear()
        self._motions[said] = self._track.read_text(encoding="utf-8")
        with wave.open(str(self._wav)) as w:
            return np.frombuffer(w.readframes(w.getnframes()), "<i2").astype(np.float32) / 32768, w.getframerate()

    def _ask(self, req: dict) -> dict:
        for attempt in (0, 1):  # the engine aborts on an internal panic: restart it once
            if not self._proc or self._proc.poll() is not None:
                self._proc = subprocess.Popen([str(self._exe), str(self._dict)], stdin=subprocess.PIPE,
                                              stdout=subprocess.PIPE, text=True, encoding="utf-8",
                                              creationflags=subprocess.CREATE_NO_WINDOW)
                self._proc.stdout.readline()  # {"ready": true}
            try:
                self._proc.stdin.write(json.dumps(req) + "\n")
                self._proc.stdin.flush()
                if (line := self._proc.stdout.readline()):
                    return json.loads(line)
            except OSError:
                pass
            self._proc.kill()
        return {"ok": False, "error": "engine crashed twice on this sentence"}
