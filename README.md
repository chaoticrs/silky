# agentd

A voice assistant that lives on your Windows laptop and runs entirely on it. Say its name, say what you
want, and local models do it: open things, find files by what they are about, work with your clipboard and
selection, watch the screen for you, set reminders, remember things. It answers out loud while a small
overlay in the top-right corner shows what it is doing.

It runs on top of [llama-swap-kit](https://github.com/chaoticrs/llama-swap-kit). Nothing leaves the laptop
except what a tool explicitly opens (a web search goes to your browser).

| Listening | Speaking | Found files (click to open) |
|---|---|---|
| ![listening](docs/silky-listening.png) | ![speaking](docs/silky-speaking.png) | ![files](docs/silky-files.png) |

Say **"Chimera"** instead of "Silky" and the same assistant answers in a physically modelled synthetic voice,
shown as Chimera's own 3D head with the tongue, jaw and lips replaying each sentence:

| Thinking | Speaking |
|---|---|
| ![chimera thinking](docs/chimera-thinking.png) | ![chimera speaking](docs/chimera-speaking.png) |

## Run
```powershell
powershell -ExecutionPolicy Bypass -File setup.ps1   # once: Python env + wake-word and end-of-turn models (26 MB)
.\run.ps1                                            # starts the inference kit too, if it is not running
.\run.ps1 --doctor                                   # checks everything it needs and says how to fix what is missing
```
Say **"Silky"**, then your command, in one breath or two. Say the name again while it talks to interrupt.
After a reply it keeps listening for a few seconds, so follow-ups need no wake word.

```powershell
.\run.ps1 --text "open notepad"        # typed command, no microphone
.\run.ps1 --as chimera --text "hello"  # typed command answered as the Chimera persona
.\run.ps1 --text "..." --mute          # no speech either
.\run.ps1 --wav clip.wav --no-overlay  # use a 16 kHz mono WAV as the microphone
.\run.ps1 --index                      # build or update the file-search index and exit
```

## Things to ask for
| | Examples |
|---|---|
| Apps and the web | "open notepad", "open youtube", "search the web for ..." |
| The machine | "what time is it", "how is my battery", "volume up", "skip this song", "lock the screen" |
| Files by meaning | "find my notes about op-amps", "where is my internship offer letter"; the matches appear as a card, click one to open it |
| Clipboard and selection | "summarize what I copied", "explain what I've selected", "fix the grammar of this and put it back" |
| The screen | "is there an error on my screen?", "tell me when the download finishes", "when the installer is done, lock the screen" |
| Reminders | "set a 10 minute timer", "at 6 pm remind me to call mom", "what reminders do I have" |
| Memory | "remember that my bike lock code is 4172", "what is my bike lock code" |
| Chimera's voice | "make your voice deeper", "sound like a child", "reset your voice" |

After "open ..." it looks at the screen and tells you whether the app really appeared. Reminders survive a
restart. Memory, reminders and the file index are plain files under `data/` and `index/`.

## How a command is handled
1. **Wake.** What you say is transcribed and checked for the name (`wake.engine = "transcript"`; reliable for
   any name, uses the CPU while someone talks). `"spotter"` is a tiny always-on keyword model: almost free,
   but it misses unusual names often.
2. **End of turn.** A small audio model judges that you have finished after a 0.3 s pause, instead of waiting
   out a fixed 0.8 s.
3. **Decide.** Known commands are matched by embedding against [routes.toml](routes.toml) and run at once
   (about 10 ms, no LLM). Otherwise a decision model (d1) picks the tool in about 0.1 s with no text
   generated, and the LLM only fills in the arguments and words the reply.
4. **Act and check.** Risky tools ask first. Tools that should change the screen are verified by looking at it.
5. **Speak.** Sentence by sentence, so the first words come before the reply is complete.

The overlay shows each step's time as it happens (`stt .91 · decide .11 · reply .64`), a chip per tool call
(green = worked, amber = failed), and short tones tell you it woke, heard you, or has news. Each persona has
its own sound.

## Configure
Everything is in [config.toml](config.toml): names and wake phrases, which kit roles to use, how patient to
be, which features are on (`cues`, `memory`, `search`, `decide`, `sight`, `chimera`), and tool safety:

| `tools.policy` | Behaviour |
|---|---|
| `confirm` (default) | Risky tools (`delete_file`, `run_powershell`, `forget`) ask "Should I ...?" and need a spoken yes |
| `auto` | Nothing asks |
| `readonly` | Risky tools are not offered to the model at all |

## What it needs from the kit
Roles `agent` (the LLM), `stt-command`, `tts` and `embed`, plus the model `d1` (LiquidAI d1-2B GGUF with its
projector) for decisions and the screen. `run.ps1 --doctor` lists which are present. Without `embed` or `d1`
the features built on them switch themselves off and the rest keeps working.

On a 4 GB card, d1 and the LLM only stay loaded together with small buffers (`-b 2048 -ub 2048 -c 4096`, the
Q8 projector) and manual VRAM budgets in the kit registry (`vram_mb` 1850 and 1900 with `mem_manual: true`);
otherwise the kit swaps them on every step. If the LLM has a thinking mode, `kit.request` switches it off
(LFM3 here: 0.8 s per decision thinking, 0.35 s not). On battery the GPU runs about four times slower.

## Limits worth knowing
- The screen model judges coarse things (is this app open, is there a dialog) and cannot read small text.
- The Chimera voice is a physical simulation, not a neural voice: striking, but not always easy to understand.
  The caption shows what it said.
- A small LLM occasionally calls a tool it did not need, or words an answer oddly. The decision model in
  front of it removes most wrong tool choices, not all.

How it is built and how to extend it: [ARCHITECTURE.md](ARCHITECTURE.md).
