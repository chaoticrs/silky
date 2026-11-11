# agentd architecture

A voice agent daemon built from small bricks. Each brick does one job and plugs into a slot defined in
`agentd/contracts.py`. Bricks never import each other; `agentd/app.py` is the only file that knows which
brick fills which slot and how a conversation flows.

```
mic ──> wake ──> listen ──> stt ──> router ──(known command)──> tools ──> canned reply ─┐
                                      └──(anything else)──> agent <──> tools ───────────┤
overlay <── events ── app.py ──> speak (voice of the persona that was woken) <──────────┘
                    (stt, llm, tts and embeddings are the inference kit, reached through kit.py)
```

| Brick | Job | Slot it fills | Replace it when |
|---|---|---|---|
| `mic.py` | Microphone frames (or a WAV file for tests) | `Mic` | different audio input |
| `wake.py` | Spot the wake phrase (sherpa-onnx keyword spotter) | `Wake` | different wake engine |
| `listen.py` | Cut one utterance out of the mic stream | used directly | you want a model-based VAD |
| `kit.py` | Talk to llama-swap-kit by role | `Llm`, `Stt`, `Voice`, `Embedder` | the inference server changes |
| `router.py` | Fast path: match the command to a known intent by embedding, no text generated | used directly | different decision model |
| `agent.py` | Chat loop with tool calls and short history | used directly | different agent strategy |
| `chimera.py` | Chimera voice: keeps `engines/chimera/chimera-say.exe` running, holds its settings | `Voice` | n/a |
| `tools/` | What the agent can do on the PC, plus the safety policy. Plain modules register stateless tools; `linked`, `lookout`, `reminders` and `memory` have an `install(...)` that the app calls with the live brick they need | `Tools` | adding abilities |
| `cues.py` | Short synthesized tones (woke, heard, news, error), one timbre per persona | used directly | different sounds |
| `doctor.py` | `--doctor`: checks kit roles, audio devices and local files, and says how to fix each | n/a | n/a |
| `speak.py` | Sentence queue, playback, loudness + spectrum | used directly | different audio output |
| `turn.py` | End-of-turn decision model (Smart Turn, ONNX, ~30 ms): has the speaker finished? | `TurnEnd` | optional; `listen.py` falls back to a fixed silence |
| `screen.py` | Screenshot as PNG and the open windows' titles (Win32 + zlib only) | n/a | n/a |
| `sight.py` | Yes/no questions about the screen, and waiting until one becomes true | uses `Decider` | n/a |
| `index.py` | Files by meaning: reads, chunks and embeds documents; incremental; stored in `index/` | uses `Embedder` | n/a |
| `overlay/` | The window; `web/index.html` is the entire look (network, state ring, tool chips, timings, file cards) | `Ui` | restyling |
| `app.py` | Wiring and conversation flow | n/a | changing the flow |

## Rules
- Import another brick only through `contracts.py` types. Only `app.py` imports concrete bricks.
- Everything external (inference kit, audio devices, WebView, Windows APIs) sits inside exactly one brick.
- User-tunable values live in `config.toml`, read once in `app.py` and passed in as plain arguments.
- `tests/test_contracts.py` pins each brick's promises using fakes. Run it after changing a brick.

## Recipes
**Add a tool:** write a typed function with `@tool("one-line description")` in a module under `agentd/tools/`
(add `risky=True` if it changes, deletes or executes anything) and import the module in `tools/__init__.py`.
The JSON schema comes from the signature.

**Add a fast-path command:** add a `[[route]]` to `routes.toml` (tool, fixed args, example phrasings, reply).
Only commands with no free-form argument belong there. The router refuses anything below `router.threshold`
or too close to a second intent, and those go to the LLM.

**Add a persona / voice engine:** a persona is a wake phrase, a name and a `Voice` (a class with
`synth(text) -> (float32 samples, sample_rate)`). Add one entry to `self.personas` in `app.py`, the way
`_add_chimera` does. `speak.py` handles queueing and playback, the overlay animates from the audio itself,
and `PERSONA_HUES` in `overlay/web/index.html` gives it its own colours.

**Chimera** lives in `engines/`: `chimera-src` (upstream clone), `chimera-say` (our 100-line Rust wrapper with
its contract in the file header), `chimera-head` (two small files that bundle upstream's own 3D head renderer and
its engine as wasm into one script) and `chimera/` (the built exe, dictionary and `head.js`). `setup-chimera.ps1`
rebuilds it all.

**Skins:** a persona can replace the overlay's network with its own look. `Overlay(skins={persona: script})`
sends the script's URL with the persona event; the script registers itself with `ui.skin(...)` (contract in
`overlay/web/index.html`). Chimera's skin replays the `motion` event: what the voice's body did during the
sentence, recorded by `chimera-say` and handed over by `ChimeraVoice.motion(text)` as the audio starts.

**Background features** (a reminder coming due, a screen watch firing) never touch audio or the LLM
themselves. They call the `Host` slot, `announce(event, then)`, which `app.py` implements: it waits for the
turn in progress, plays the news tone, lets the LLM word the event, and carries out `then` if it is a command.

**How a request is decided** (all in `app.py`): the embedding router answers known commands outright (10 ms);
otherwise the `Decider` (d1, `KitDecider` in `kit.py`) picks the tool (0.1 s) and the LLM is given a one-line hint
naming it, so it only writes the arguments and the reply. The same `Decider` judges a spoken yes/no for risky
tools and, through `sight.py`, looks at the screen: `Toolbox(check=...)` lets the app confirm on screen that an
"open" really happened, and `watch_screen` waits in the background for something to appear. A background watch
takes the turn lock for each look, so it never competes with a turn in progress.

**Change the wake word:** `wake.phrase` in `config.toml`.

**Restyle the overlay:** edit `overlay/web/index.html`; open it with `?demo` in a browser to preview all
states without the daemon. The page receives `ui.on({type, ...})` with the events listed under `Ui` in
`contracts.py`.
