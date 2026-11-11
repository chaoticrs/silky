# The explainer

A fast, narrated product explainer, about 56 seconds long, in five beats. It is drawn as vector shapes in brand
blue `#2563EB` on `#F8FAFC`, set in Inter, with kinetic type that follows the voiceover word by word and quiet
UI sound effects. Two real recordings of Silky at work sit in the middle of it.

| Beat | About | What it shows |
|---|---|---|
| The problem | 0:00–0:05 | Assistants send your voice away. What if they didn't? |
| Meet Silky | 0:05–0:12 | Say its name and what you want; models on the laptop do the rest |
| What it does | 0:12–0:38 | **Real take:** "fix the grammar of this and put it back". **Real take:** "find my notes about amplifiers". Then quick illustrated scenes: watching the screen, remembering |
| Fast and local | 0:38–0:46 | Under 0.1 s for a known command, under 0.5 s to choose a tool, on a 4 GB GPU |
| Private | 0:46–0:56 | No account, no subscription, nobody listening |

```powershell
..\..\.venv\Scripts\python.exe make_audio.py   # 1. narration (kit TTS), the takes' sound, effects, pad -> out\explainer.wav, out\timeline.json
node render.mjs                                 # 2. every frame + the soundtrack -> out\silky-explainer.mp4 (about 3 min)
node render.mjs --serve                         #    or watch it live with sound in a browser
node render.mjs --stills 12 33.5                #    or save single frames to check
```
Needs the inference kit running (for the voice), `ffmpeg` on PATH, Microsoft Edge, `npm install` done once in
`film/` (for puppeteer-core), and the launch film's cut of its recorded take (`film/out/frames/`, `cut_*.npy`,
`cut.json`: run `film/record.py` and `film/cut.py` if they are missing). Inter is loaded from Google Fonts.

| File | Job |
|---|---|
| `beats.py` | The sequence: voiceover phrases and recorded takes back to back, the beats, when each sound effect lands |
| `make_audio.py` | Synthesizes each phrase (cached), estimates when each word is said, lays in the takes' own sound, makes the effects and music, mixes |
| `explainer.html` | The picture: `draw(t)` sets every element for instant `t`, driven by the timeline |
| `render.mjs` | Steps the page frame by frame in headless Edge (waiting for each recorded frame) and encodes it with the soundtrack |

## What is real and what is illustrated
Real: the two takes are the launch film's screen recordings of the actual daemon answering spoken commands, at real
speed with their own sound (the command goes in through the microphone slot and Silky answers out loud). The chips
over them ("chose a tool · 0.34 s", "rewrite selection ✓ · 315 ms" and so on) are what the daemon logged during that
take, at the moment it logged them. Each take already contains one cut, and it is marked on screen ("cut · 3.6 s skipped").
The takes' commands were spoken by a synthesized voice; see `../README.md` for how the take was staged.

Illustrated: everything else, including the light-themed overlay in the drawn scenes. The numbers in beat 4 are the
launch film's measurements: the router at 54 and 77 ms and d1 at 0.34 to 0.46 s in the recorded take, and the LLM
plus d1 at about 3.6 GB of the laptop's 4 GB. The end card says which parts are real.
