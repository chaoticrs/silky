"""Film the assistant at work, for the launch film's proof shots.

Takes over the screen for a couple of minutes: opens a demo desktop full screen (stage.html), starts the
real daemon with its overlay, records the screen with ffmpeg, and gives the daemon spoken commands. Don't
touch the keyboard or mouse while it runs.

What is real: every command goes in as audio through the daemon's own microphone slot (a synthesized voice,
so the take can be repeated), and from there it is the product: wake word, end-of-turn model, speech to
text, router, decision model, LLM, tools, speech, overlay. Tools act on the real clipboard, keyboard and screen.
What is staged: the desktop (so nothing private is in shot) and the six demo documents it searches.

Writes out/rec.mkv (the screen), out/session.json (what happened when, with the daemon's own timings) and
out/session.npz (everything that was said, to rebuild the sound).   run:  ..\\.venv\\Scripts\\python.exe record.py
"""
import collections
import ctypes
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import threading
import time
import tomllib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT))
from agentd import app  # noqa: E402
from agentd.contracts import FRAME, MIC_RATE  # noqa: E402
from agentd.kit import Kit, KitVoice  # noqa: E402

OUT = HERE / "out"
DOCS = {
    "Op-amp lab notes.txt": "Lab 4: operational amplifiers. Inverting amplifier gain is minus R2 over R1. Measured gain 9.8 with a 741. Slew rate limits the output above 20 kHz.",
    "Signals and systems summary.md": "Fourier transform pairs, convolution, sampling theorem, Laplace transform and poles and zeros of filters.",
    "Ladakh trip packing list.md": "Warm jacket, sunscreen, power bank, permits for Pangong lake, altitude sickness tablets, camera.",
    "Electricity bill March.txt": "Units consumed 212. Amount payable 1840 rupees. Due date 14 April. Consumer number 4471.",
    "Internship offer letter.txt": "We are pleased to offer you a summer internship in embedded systems, starting in June, with a monthly stipend.",
    "Grandma's dal recipe.md": "Toor dal, turmeric, tomatoes, cumin and mustard seeds for the tempering, ghee, fresh coriander.",
}
# (name, what the page shows first, the spoken command, what to do while the daemon works)
SHOTS = [
    ("time", ["clear"], "Silky, what time is it?", None),
    ("grammar", ["notes", "select"], "Silky, fix the grammar of this and put it back.", None),
    ("files", ["clear"], "Silky, find my notes about amplifiers.", None),
    ("remember", ["clear"], "Silky, remember that my locker code is four one seven two.", None),
    ("recall", ["clear"], "Silky, what is my locker code?", None),
    ("watch", ["download"], "Silky, tell me when the download finishes.", "finish"),
    ("chimera", ["clear"], "Chimera, what time is it?", None),
    ("open", ["clear"], "Silky, open the calculator.", None),
]


class ScriptMic:
    """The Mic slot, fed by this script: silence in real time, and a spoken command when one is queued."""

    def __init__(self):
        self._frames, self._due, self.spoken = collections.deque(), time.time(), []

    def say(self, name: str, pcm: np.ndarray) -> None:
        pcm = np.concatenate([pcm, np.zeros(-len(pcm) % FRAME, np.float32)])
        self._frames.extend([name, *pcm.reshape(-1, FRAME)])

    def read(self):
        self._due = max(self._due + FRAME / MIC_RATE, time.time() - 0.3)   # real time; never burst to catch up
        time.sleep(max(0, self._due - time.time()))
        if self._frames and isinstance(self._frames[0], str):
            self.spoken.append((self._frames.popleft(), time.time()))
        return self._frames.popleft() if self._frames else np.random.default_rng().normal(0, 1e-4, FRAME).astype(np.float32)

    def flush(self):
        pass


class Tap:
    """Sits between the daemon and the overlay: passes every event on, and keeps a timed copy."""

    def __init__(self, ui):
        self._ui, self.events, self.state, self.on_open = ui, [], "idle", lambda path: None

    def emit(self, event, **data):
        if event == "state":
            self.state = data["s"]
        if event not in ("level", "motion"):
            self.events.append({"at": time.time(), "type": event, **{k: v for k, v in data.items() if k != "rows"}})
        self._ui.emit(event, **data)


class Recorded:
    """Wraps a Voice: everything it synthesizes is kept, to rebuild the soundtrack of the take."""

    def __init__(self, voice, clips):
        self._voice, self._clips = voice, clips

    def synth(self, text):
        pcm, rate = self._voice.synth(text)
        self._clips[text] = (pcm, rate)
        return pcm, rate

    def __getattr__(self, name):
        return getattr(self._voice, name)


def command_audio(kit: Kit, text: str) -> np.ndarray:
    """The user's line, spoken by the kit's second voice, at the microphone's rate (cached)."""
    path = OUT / "clips" / ("user-" + hashlib.sha1(text.encode()).hexdigest()[:12] + ".npy")
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        pcm, rate = KitVoice(kit, "tts", "mira").synth(text)
        loud = np.flatnonzero(np.abs(pcm) > 0.01)
        pcm = pcm[max(0, loud[0] - 1200):loud[-1] + 2400]
        np.save(path, np.interp(np.arange(0, len(pcm), rate / MIC_RATE), np.arange(len(pcm)), pcm).astype(np.float32))
    return np.load(path) * 2.2   # a person at a laptop microphone is this loud


def serve_stage():
    """The demo desktop page, and the queue of things it should show."""
    todo = []

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path.startswith("/next"):
                since = int(self.path.split("=")[-1])
                body, kind = json.dumps([c for c in todo if c["n"] > since]).encode(), "application/json"
            else:
                body, kind = (HERE / "stage.html").read_bytes(), "text/html"
            self.send_response(200)
            self.send_header("Content-Type", kind)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *a):
            pass
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return f"http://127.0.0.1:{server.server_address[1]}/", lambda do: todo.append({"n": len(todo) + 1, "do": do})


def session(ui) -> None:
    log = app.log
    cfg = tomllib.loads((ROOT / "config.toml").read_text(encoding="utf-8"))
    docs = OUT / "demo-docs"
    docs.mkdir(parents=True, exist_ok=True)
    for name, text in DOCS.items():
        (docs / name).write_text(text, encoding="utf-8")
    for old in (OUT / "demo-data").glob("*"):
        old.unlink()
    cfg["paths"] = {"data": "film/out/demo-data", "index": "film/out/demo-index"}   # never your real memory or index
    cfg["search"] |= {"folders": [str(docs)], "refresh_on_start": False}
    cfg["listen"]["follow_up_s"] = 0
    cfg["sight"]["watch_every_s"] = 2
    cfg["tools"]["disabled"] = ["run_powershell", "delete_file", "web_search", "open_url", "lock_screen", "write_note", "forget"]

    url, show = serve_stage()
    edge = next(p for p in ("C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe",
                            "C:/Program Files/Microsoft/Edge/Application/msedge.exe") if Path(p).exists())
    stage = subprocess.Popen([edge, f"--app={url}", "--start-fullscreen", "--no-first-run", "--no-default-browser-check",
                              f"--user-data-dir={tempfile.mkdtemp(prefix='silky-stage-')}"])
    tap, mic, clips, said, cues = Tap(ui), ScriptMic(), {}, [], []
    kit = Kit(cfg["kit"]["url"])
    audio = {name: command_audio(kit, text) for name, _, text, _ in SHOTS}
    d = app.Daemon(cfg, tap, mic)
    d.refresh_index()
    d.personas = {phrase: (name, Recorded(voice, clips)) for phrase, (name, voice) in d.personas.items()}
    d._speaker.voice = next(iter(d.personas.values()))[1]
    on_say = d._speaker._on_say
    d._speaker._on_say = lambda text: (said.append((time.time(), text)), on_say(text))
    play = d._cues.play
    d._cues.play = lambda cue, persona="", wait=False: (cues.append((time.time(), cue, persona)), play(cue, persona, wait))
    from agentd.wake import SherpaWake
    w = cfg["wake"]
    threading.Thread(target=lambda: d.run(SherpaWake(ROOT / "models" / "kws", list(d.personas), w["threshold"], w["boost"]), True),
                     daemon=True).start()
    time.sleep(6)   # the stage is up, the models are warm

    rec = subprocess.Popen(["ffmpeg", "-y", "-loglevel", "error", "-use_wallclock_as_timestamps", "1", "-f", "gdigrab", "-framerate", "30",
                            "-draw_mouse", "0", "-i", "desktop", "-c:v", "h264_qsv", "-global_quality", "20", "-copyts",
                            str(OUT / "rec.mkv")], stdin=subprocess.PIPE)
    time.sleep(2)

    def settle(limit: float) -> None:
        """Wait until the daemon has answered and gone quiet (or `limit` seconds pass)."""
        end, busy = time.time() + limit, False
        while time.time() < end:
            busy = busy or tap.state != "idle"
            if busy and tap.state == "idle":
                d._speaker.wait()
                return
            time.sleep(0.05)

    shots, calculators = [], _pids("CalculatorApp.exe")
    for name, setup, text, during in SHOTS:
        for do in setup:
            show(do)
            time.sleep(0.4)
        time.sleep(0.8)
        start = time.time()
        log(f"== {name}: {text}")
        mic.say(name, audio[name])
        settle(40)
        if during:                    # e.g. the download finishes; the daemon's watch has to notice by itself
            time.sleep(1.5)
            show(during)
            tap.state = "idle"
            settle(40)
        time.sleep(1.3)
        shots.append({"name": name, "text": text, "t0": start, "t1": time.time()})
    rec.stdin.write(b"q")
    rec.stdin.flush()
    rec.wait(10)
    stage.terminate()
    for pid in _pids("CalculatorApp.exe") - calculators:
        subprocess.run(["taskkill", "/PID", pid, "/F"], capture_output=True)

    spoken = [(t, text) for t, text in said if text in clips]
    np.savez(OUT / "session.npz", **{f"user_{n}": audio[n] for n in audio},
             **{f"said_{i}": clips[text][0] for i, (_, text) in enumerate(spoken)})
    (OUT / "session.json").write_text(json.dumps({
        "shots": shots, "events": tap.events, "user": [{"name": n, "at": t} for n, t in mic.spoken],
        "said": [{"at": t, "text": text, "rate": clips[text][1], "key": f"said_{i}"} for i, (t, text) in enumerate(spoken)],
        "cues": [{"at": t, "cue": c, "persona": p} for t, c, p in cues]}, indent=1), encoding="utf-8")
    log("recorded: out/rec.mkv, out/session.json, out/session.npz")
    os._exit(0)   # the daemon's threads never end by themselves


def _pids(image: str) -> set:
    out = subprocess.run(["tasklist", "/FI", f"IMAGENAME eq {image}", "/FO", "CSV", "/NH"], capture_output=True, text=True).stdout
    return {line.split(",")[1].strip('"') for line in out.splitlines() if line.lower().startswith(f'"{image.lower()}')}


if __name__ == "__main__":
    sys.stdout.reconfigure(errors="replace")
    ctypes.windll.shcore.SetProcessDpiAwareness(2)   # screenshots the assistant takes are then full resolution
    from agentd.overlay import Overlay
    o = tomllib.loads((ROOT / "config.toml").read_text(encoding="utf-8"))["overlay"]
    overlay = Overlay(o["width"], o["height"], o["margin"], o["linger_s"], {"chimera": ROOT / "engines" / "chimera" / "head.js"}, 6.0)
    overlay.run(lambda: session(overlay))
