# The launch film

An 80-second film about the assistant, made entirely on the laptop it runs on. Its proof scenes are screen
recordings of the real daemon answering spoken commands; the narration is the kit's own text-to-speech, the
music is synthesized in `make_audio.py`, and every frame is rendered here.

```powershell
..\.venv\Scripts\python.exe record.py     # 1. film the assistant at work (takes over the screen for ~3 min)
..\.venv\Scripts\python.exe cut.py        # 2. cut the take into proof shots: frames, sound, the daemon's own timings
..\.venv\Scripts\python.exe make_audio.py # 3. narration + footage sound + music -> out\soundtrack.wav, out\timeline.json
npm install                                 #    once: puppeteer-core, to drive headless Edge
node render.mjs                             # 4. every frame + the soundtrack -> out\silky-launch.mp4  (about 4 min)
node render.mjs --serve                     #    or watch it live in a browser instead
```
Needs the inference kit running, `ffmpeg` on PATH and Microsoft Edge.

| File | Job |
|---|---|
| `record.py`, `stage.html` | Runs the real daemon on a staged desktop, speaks commands into its microphone slot, records the screen |
| `cut.py` | Which stretches of the take are used (`CUTS`), and what the daemon reported during them |
| `script.py` | The scenes in order: narration lines and which shots play where |
| `make_audio.py` | Synthesizes narration (cached), composes the music, mixes in the footage sound, writes the timeline |
| `film.html` | The picture, driven by the timeline |
| `render.mjs` | Runs the page on a virtual clock in headless Edge and pipes the frames to ffmpeg |
| `qa_audio.py` | Checks the narration in the mix with speech-to-text (written for the first cut) |

## What is real and what is staged
Real: every command enters as audio through the daemon's microphone slot and goes through the whole product
(wake word, end-of-turn model, speech to text, router, decision model, LLM, tools, speech, overlay). The tools
act on the real clipboard, keyboard and screen. The times captioned beside the footage are the ones the daemon
logged in that take. A cut inside a shot is marked on screen; sped-up shots are labelled and silent.

Staged: the desktop (a page drawn full screen, so nothing private is in shot), the six documents it searches,
the note it corrects and the download it waits for. The commands are spoken by a synthesized voice so a take
can be repeated; it was not tried with a person speaking.

| On screen | Measurement |
|---|---|
| under 0.1 s for a command it knows | embedding router, no LLM call: 54 and 77 ms in the recorded take (6 to 30 ms when nothing else is running) |
| under 0.5 s choosing the right tool | d1 decision model: 0.34 to 0.46 s in the recorded take, while the screen was being captured (about 0.12 s in a quiet benchmark) |
| 4 GB, every model at once | d1 and LFM3 loaded together use about 3.6 GB; speech models run on the CPU |
