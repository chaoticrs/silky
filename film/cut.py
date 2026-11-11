"""Step 2 of the film: cut the recorded take (record.py) into the proof shots.

For each shot in CUTS it takes stretches of out/rec.mkv, writes them as numbered frames the film page shows,
rebuilds their sound from what was actually said in the take, and lists what the daemon reported during
them (what it heard, how long each step took), so the film can caption the footage with its own numbers.

A shot's parts are (from, to, speed), in seconds from the moment its command starts being spoken. A gap between
two parts is a cut, and the film says so on screen ("12 s later"). Speed 2 is labelled x2 and has no sound.

Writes out/cut.json, out/cut_<shot>.npy (48 kHz mono) and out/frames/<shot>/00001.jpg ...
run:  ..\\.venv\\Scripts\\python.exe cut.py
"""
import json
import shutil
import subprocess
import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
from agentd import cues  # noqa: E402

OUT, SR, FPS = HERE / "out", 48000, 30
CROP = "crop=1920:1020:0:0"   # the bottom 60 px are the Windows taskbar
# shot (as named in record.py) -> parts. "said:N" = the start of the N-th thing the assistant said in that shot.
CUTS = {
    "grammar": [(-0.3, 6.9, 1), ("said:1", 3.2, 1)],
    "files": [(-0.3, 7.1, 1), ("said:0", 3.3, 1)],
    "watch": [(-0.3, 6.0, 1), ("event:notify-3.0", 3.5, 1), ("said:2", 2.6, 1)],
    "chimera": [(-0.3, 8.6, 1)],
    "recall": [("said:0-2.6", 4.4, 2)],
    "open": [("tool:open_app-0.4", 4.4, 2)],
}


def resample(x: np.ndarray, sr: int) -> np.ndarray:
    n = int(round(len(x) * SR / sr))
    return np.interp(np.arange(n) * sr / SR, np.arange(len(x)), x).astype(np.float32)


if __name__ == "__main__":
    session = json.loads((OUT / "session.json").read_text(encoding="utf-8"))
    said_audio = np.load(OUT / "session.npz")
    probe = lambda entry, path: float(subprocess.run(["ffprobe", "-v", "error", "-show_entries", f"format={entry}", "-of", "csv=p=0",
                                                      str(path)], capture_output=True, text=True).stdout)
    t0 = probe("start_time", OUT / "rec.mkv")                     # the recording's first frame, as wall-clock time
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(OUT / "rec.mkv"), "-c", "copy", str(OUT / "rec0.mkv")], check=True)
    length = probe("duration", OUT / "rec0.mkv")

    # the take's sound, rebuilt: the command audio that went into the microphone slot, every sentence the
    # assistant spoke, and its cues, each at the moment it happened
    sound = np.zeros(int((length + 2) * SR), np.float32)

    def lay(pcm, at, gain=1.0):
        i = int((at - t0) * SR)
        if 0 <= i < len(sound):
            pcm = pcm[:len(sound) - i]
            sound[i:i + len(pcm)] += pcm * gain
    for u in session["user"]:
        lay(resample(said_audio["user_" + u["name"]] / 2.2, 16000), u["at"], 0.9)
    for s in session["said"]:
        lay(resample(said_audio[s["key"]], s["rate"]), s["at"] + 0.05)
    for c in session["cues"]:
        lay(resample(cues.render(c["cue"], c["persona"], 0.25), cues.RATE), c["at"])

    shutil.rmtree(OUT / "frames", ignore_errors=True)
    spoken = {u["name"]: u["at"] for u in session["user"]}
    shots = {}
    for shot in session["shots"]:
        name = shot["name"]
        if name not in CUTS:
            continue
        inside = lambda e: shot["t0"] <= e["at"] <= shot["t1"]
        said = [s for s in session["said"] if inside(s)]
        events = [e for e in session["events"] if inside(e)] + [{"at": c["at"], "type": "cue", **c} for c in session["cues"] if inside(c)]

        def when(mark) -> float:
            """A part's start, in recording seconds."""
            if not isinstance(mark, str):
                return spoken[name] - t0 + mark
            kind, _, rest = mark.partition(":")
            key, _, back = rest.partition("-")
            at = (said[int(key)]["at"] if kind == "said" else
                  next(e["at"] for e in events if e.get("name") == key or e.get("cue") == key))
            return at - t0 - float(back or 0)

        frames_dir, n, parts, audio, notes, clock = OUT / "frames" / name, 0, [], [], [], 0.0
        frames_dir.mkdir(parents=True)
        for mark, seconds, speed in CUTS[name]:
            a = when(mark)
            tmp = frames_dir / "part"
            tmp.mkdir()
            subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-ss", f"{a:.3f}", "-t", f"{seconds:.3f}", "-i", str(OUT / "rec0.mkv"),
                            "-vf", f"{CROP},setpts=PTS/{speed},fps={FPS}", "-q:v", "3", str(tmp / "%05d.jpg")], check=True)
            got = sorted(tmp.glob("*.jpg"))
            for f in got:
                n += 1
                f.rename(frames_dir / f"{n:05d}.jpg")
            tmp.rmdir()
            took = len(got) / FPS
            piece = sound[int(a * SR):int((a + seconds) * SR)].copy() if speed == 1 else np.zeros(int(took * SR), np.float32)
            piece = np.concatenate([piece, np.zeros(max(0, int(took * SR) - len(piece)), np.float32)])[:int(took * SR)]
            fade = min(len(piece) // 2, int(0.03 * SR))
            piece[:fade] *= np.linspace(0, 1, fade)
            piece[-fade:] *= np.linspace(1, 0, fade)
            for e in events:                                       # what the daemon reported during this part
                at = e["at"] - t0
                if a <= at <= a + seconds and e["type"] in ("heard", "timing", "done", "card", "cue", "said"):
                    notes.append({"t": round(clock + (at - a) / speed, 2), **{k: v for k, v in e.items() if k != "at"}})
            parts.append({"t": round(clock, 3), "from": round(a, 2), "seconds": seconds, "speed": speed,
                          "skipped": round(a - parts[-1]["end"], 1) if parts else 0, "end": a + seconds})
            audio.append(piece)
            clock += took
        np.save(OUT / f"cut_{name}.npy", np.concatenate(audio))
        shots[name] = {"frames": n, "seconds": round(n / FPS, 3), "command": shot["text"], "parts": parts, "notes": notes,
                       "said": [s["text"] for s in said]}
        print(f"  {name:8s} {n / FPS:5.1f} s  {[(p['from'], p['seconds'], p['speed']) for p in parts]}")
    (OUT / "cut.json").write_text(json.dumps(shots, indent=1), encoding="utf-8")
    print(f"out/cut.json: {sum(s['seconds'] for s in shots.values()):.1f} s of footage")
