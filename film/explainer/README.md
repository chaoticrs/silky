# The 60-second explainer

A narrated product explainer in five beats, drawn entirely as vector shapes: brand blue `#2563EB` on `#F8FAFC`,
set in Inter, with kinetic type that follows the voiceover word by word and quiet UI sound effects.

| Beat | Time | What it says |
|---|---|---|
| The problem | 0:00–0:10 | Assistants send your voice away. What if they didn't? |
| Meet Silky | 0:10–0:20 | Say its name and what you want; models on the laptop do it |
| What it does | 0:20–0:38 | Fixes the selection, finds files by meaning, watches the screen, remembers |
| Fast and local | 0:38–0:50 | Under 0.1 s for a known command, under 0.5 s to choose a tool, on a 4 GB GPU |
| The promise | 0:50–1:00 | No account, no subscription, nobody listening |

```powershell
..\..\.venv\Scripts\python.exe make_audio.py   # 1. narration (kit TTS), effects, pad -> out\explainer.wav, out\timeline.json
node render.mjs                                 # 2. every frame + the soundtrack -> out\silky-explainer.mp4 (about 3 min)
node render.mjs --serve                         #    or watch it live with sound in a browser
node render.mjs --stills 12 33.5                #    or save single frames to check
```
Needs the inference kit running (for the voice), `ffmpeg` on PATH, Microsoft Edge, and `npm install` done once in
`film/` (for puppeteer-core). Inter is loaded from Google Fonts while rendering.

| File | Job |
|---|---|
| `beats.py` | The beats, the voiceover phrases and when each should start, and when each sound effect lands |
| `make_audio.py` | Synthesizes each phrase (cached), estimates when each word is said, makes the effects and music, mixes |
| `explainer.html` | The picture: `draw(t)` sets every element for instant `t`, driven by the timeline |
| `render.mjs` | Steps the page frame by frame in headless Edge and encodes it with the soundtrack |

Unlike the launch film, nothing here is a screen recording: every scene is an illustration (the end card says so).
The numbers are the launch film's measurements (see `../README.md`): the router at 54 and 77 ms and d1 at 0.34 to
0.46 s in the recorded take, and LLM plus d1 at about 3.6 GB of the laptop's 4 GB.
