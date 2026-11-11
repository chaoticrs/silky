"""Checks on the soundtrack that do not need ears: loudness over time, clipping, and whether speech-to-text
still understands every line with the music under it."""
import json, sys, wave
from pathlib import Path
import numpy as np
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
from agentd.kit import Kit, KitStt
with wave.open(str(HERE / "out" / "soundtrack.wav")) as w:
    x = np.frombuffer(w.readframes(w.getnframes()), "<i2").astype(np.float32).reshape(-1, 2) / 32768
    sr = w.getframerate()
tl = json.loads((HERE / "out" / "timeline.json").read_text())
db = lambda v: 20 * np.log10(max(1e-9, v))
print(f"peak {db(np.abs(x).max()):.1f} dBFS, overall rms {db(np.sqrt(np.mean(x ** 2))):.1f} dB, samples at full scale: {int((np.abs(x) > 0.999).sum())}")
stt = KitStt(Kit("http://127.0.0.1:8080"), "stt")
mono = x.mean(1)
for s in tl["scenes"]:
    seg = mono[int(s["t0"] * sr):int(s["t1"] * sr)]
    gaps = np.concatenate([mono[int(a * sr):int(b * sr)] for a, b in zip([s["t0"]] + [l["t1"] for l in s["lines"]], [l["t0"] for l in s["lines"]] + [s["t1"]]) if b - a > 0.3] or [np.zeros(1)])
    said = np.concatenate([mono[int(l["t0"] * sr):int(l["t1"] * sr)] for l in s["lines"]])
    print(f"{s['id']:8s} speech {db(np.sqrt(np.mean(said ** 2))):6.1f} dB | between lines {db(np.sqrt(np.mean(gaps ** 2))):6.1f} dB")
    for l in s["lines"]:
        a, b = int((l["t0"] - 0.2) * sr), int((l["t1"] + 0.2) * sr)
        heard = stt.transcribe(mono[a:b:3].astype(np.float32))          # 48 kHz -> 16 kHz
        print(f"    {l['who']:8s} wrote {l['text']!r}\n             heard {heard!r}")
