"""Composition root: the only file that knows which concrete brick fills which slot,
and the only place the conversation flow (wake -> listen -> think -> speak) is written down.
"""
import argparse
import difflib
import json
import os
import re
import sys
import threading
import time
import tomllib
from collections import deque
from pathlib import Path

from .agent import Agent
from .contracts import MIC_RATE, NoUi
from .kit import Kit, KitDecider, KitEmbedder, KitError, KitLlm, KitStt, KitVoice
from .listen import Listener
from .router import Route, Router
from .speak import Speaker, sentences
from .tools import Toolbox, files, linked, lookout, memory, reminders

ROOT = Path(__file__).resolve().parent.parent
_ECHOED_TAG = re.compile(r"^\[as \w+\]\s*")  # small models sometimes repeat the persona tag
YES = ("yes", "yeah", "yep", "sure", "do it", "go ahead", "confirm", "okay", "ok")
LISTED = ("find_files", "search_files_by_meaning")  # tools whose result is a list of files worth showing
STOP = ("stop", "quiet", "be quiet", "shut up", "cancel", "never mind", "nevermind", "enough", "that's enough")


def log(msg: str) -> None:
    print(f"{time.strftime('%H:%M:%S')} {msg}", flush=True)


def _after_wake_word(text: str, phrase: str) -> str | None:
    """'Hey Silky, open notepad' -> 'open notepad'; None if the text doesn't start with the wake phrase.
    Fuzzy, because speech-to-text spells unusual names its own way (Silkie, Kimera)."""
    words = [w for w in text.split()]
    if words and words[0].lower().strip(" ,.!?") in ("hey", "ok", "okay", "hi"):
        words = words[1:]
    n = len(phrase.split())
    head = " ".join(words[:n]).lower().strip(" ,.!?")
    return " ".join(words[n:]) if difflib.SequenceMatcher(None, head, phrase.lower()).ratio() >= 0.7 else None


def _after_wake_word_in(text: str, phrases: list[str]) -> str | None:
    """Like _after_wake_word, but the wake phrase may come anywhere: '...make up everything. Silky, what time
    is it' -> 'what time is it' (the first wake phrase found wins; None if there is none)."""
    words = text.split()
    for i in range(len(words)):
        for phrase in phrases:
            if (rest := _after_wake_word(" ".join(words[i:]), phrase)) is not None:
                return rest
    return None


class Daemon:
    def __init__(self, cfg: dict, ui, mic=None, mute: bool = False):
        k, self._l, a = cfg["kit"], cfg["listen"], cfg["assistant"]
        kit = Kit(k["url"])
        if not kit.healthy():
            raise SystemExit(f"Inference kit is not answering at {k['url']}. Start it first (run.ps1 does that).")
        self._ui, self._mic, self._wake, self._tag, self._persona = ui, mic, None, "", ""
        self._busy, self._background = threading.RLock(), threading.local()  # one turn at a time; see announce
        self._barge: list = []  # mic frames from a barge-in (wake word said over the reply), replayed by _hear
        self._decide, self.features = cfg["decide"], []
        paths = cfg.get("paths", {})  # optional [paths] data / index: other folders for what it stores (demos, tests)
        self._data, self._index_dir = ROOT / paths.get("data", "data"), ROOT / paths.get("index", "index")
        served = kit.models()
        if k["stt_role"] not in served and "stt" in served:   # the tuned role is an extra (setup-kit.ps1)
            log(f"kit has no '{k['stt_role']}' role: using 'stt' (slower on short commands)")
            k = k | {"stt_role": "stt"}
        self._stt = KitStt(kit, k["stt_role"])
        self._listener = Listener(self._l["min_rms"], self._l["silence_s"], self._l["max_s"],
                                  self._turn_model(), self._l["quick_s"], self._l["sure"])
        self._cues = self._make_cues(cfg["cues"], mute)

        # ---- personas: wake phrase -> (name, voice). A new voice engine is one more entry here. ----
        self.personas = {cfg["wake"]["phrase"]: (a["name"].lower(), KitVoice(kit, k["tts_role"], k["voice"]))}
        self._add_chimera(cfg["chimera"])

        # ---- tools that need a live brick: each install() registers them (see tools/__init__.py) ----
        embedder = KitEmbedder(kit, cfg["router"]["embed_role"])
        if cfg["router"]["embed_role"] not in served:          # an extra (setup-kit.ps1): three features need it
            log(f"kit has no '{cfg['router']['embed_role']}' role: instant commands, file search and memory are off")
            cfg = cfg | {"search": cfg["search"] | {"enabled": False}, "memory": {"enabled": False},
                         "router": cfg["router"] | {"enabled": False}}
        self.index = self._add_search(embedder, cfg["search"])
        self._decider = self._make_decider(kit)
        check = self._add_sight(cfg["sight"])
        linked.install_rewrite(KitLlm(kit, k["agent_role"], k["max_tokens"], 0.0, k.get("request")))
        self._reminders = reminders.install(self, self._data / "reminders.json")
        if cfg["memory"]["enabled"]:
            memory.install(embedder, self._data)
            self.features.append("memory")

        self._speaker = None if mute else Speaker(
            self.personas[cfg["wake"]["phrase"]][1],
            on_say=self._on_say, on_level=lambda v, b: ui.emit("level", v=v, bands=b))
        self._tools = Toolbox(cfg["tools"]["policy"], self._confirm, cfg["tools"]["disabled"], check, self._on_result)
        self._menu = self._tools.menu() | {"none": "No tool: a question or small talk the assistant just answers in words"}
        self._agent = Agent(KitLlm(kit, k["agent_role"], k["max_tokens"], k["temperature"], k.get("request")),
                            self._tools, a["prompt"].format(name=a["name"]), on_tool=self._on_tool)
        self._router = self._make_router(embedder, cfg["router"])
        threading.Thread(target=self._agent.warm_up, daemon=True).start()
        if self.index is not None and cfg["search"]["refresh_on_start"] and mic:
            threading.Thread(target=self.refresh_index, daemon=True).start()
        self._reminders.start()

    # -- building the optional bricks: each returns None (and says why) when it cannot be used -------------
    def _make_cues(self, c: dict, mute: bool):
        if mute or not c["enabled"]:
            return None
        from .cues import Cues
        return Cues(c["volume"])

    def _add_chimera(self, c: dict) -> None:
        if not c["enabled"]:
            return
        from .chimera import ChimeraVoice
        try:
            voice = ChimeraVoice(ROOT / "engines" / "chimera")
        except FileNotFoundError as e:
            return log(f"chimera off: {e}")
        self.personas[c["phrase"]] = ("chimera", voice)
        linked.install_voice(voice)

    def _add_search(self, embedder, s: dict):
        if not s["enabled"]:
            return None
        from .index import FileIndex
        index = FileIndex(embedder, self._index_dir, [files.resolve(f) for f in s["folders"]], s["max_files"])
        linked.install_search(index)
        self.features.append("file search")
        return index

    def _make_decider(self, kit: Kit):
        if not self._decide["enabled"]:
            return None
        if self._decide["model"] not in kit.models():          # an extra (setup-kit.ps1)
            return log(f"kit has no '{self._decide['model']}' model: the LLM picks tools by itself, screen features are off")
        decider = KitDecider(kit, self._decide["model"])
        try:  # also loads it, so the first real decision is fast
            decider.decide({"ok": {"type": "noul", "instructions": "Is this a greeting?"}}, state="hello")
        except (KitError, KeyError, ValueError) as e:
            return log(f"decision model off: {e}")
        self.features.append("decision model")
        return decider

    def _add_sight(self, s: dict):
        """-> the check that confirms on screen that an 'open ...' really happened (None without sight)."""
        if not (s["enabled"] and self._decider):
            return lambda name, args, result: result
        from . import screen
        from .sight import Sight
        # looks take the turn lock: a background watch waits while the agent is answering instead of
        # competing with the LLM for the GPU (measured: the LLM runs about twice as slow otherwise)
        sight = Sight(self._decider, screen.grab, screen.titles, s["sure"], self._busy)
        self.features.append("screen")
        return lookout.install(sight, self, s["watch_every_s"], s["watch_timeout_min"],
                               s["verify_s"] if s["verify"] else 0, log)

    def _turn_model(self):
        if not self._l["smart_turn"] or not self._mic:
            return None
        from .turn import SmartTurn
        try:
            return SmartTurn(ROOT / "models" / "turn" / "smart-turn-v3.2-cpu.onnx")
        except (FileNotFoundError, ImportError) as e:
            return log(f"smart turn off: {e}")

    def _make_router(self, embedder, r: dict):
        if not r["enabled"]:
            return None
        try:
            routes = [Route(**x) for x in tomllib.loads((ROOT / "routes.toml").read_text(encoding="utf-8"))["route"]]
            return Router(embedder, routes, r["threshold"], r["margin"])
        except (KitError, OSError) as e:
            return log(f"fast path off: {e}")

    def refresh_index(self, verbose: bool = False) -> None:
        if self.index is None:
            return log("file search is off (search.enabled)")
        t = time.time()
        try:
            read, total = self.index.refresh(lambda d, n: verbose and log(f"  indexing {d}/{n}"))
            log(f"file index: {total} files, {read} read in {time.time() - t:.0f}s")
        except KitError as e:
            log(f"file index not updated: {e}")

    # -- what the bricks report back: all of it goes to the log and the overlay ------------------------------
    def _on_say(self, text: str) -> None:
        """A sentence starts playing: caption it, and pass on its motion if the voice recorded one."""
        self._ui.emit("said", text=text)
        for _, voice in self.personas.values():
            if hasattr(voice, "motion") and (track := voice.motion(text)):
                self._ui.emit("motion", track=track)

    def _on_tool(self, name: str, arguments: str = "") -> None:
        log(f"  tool {name} {arguments}")
        self._ui.emit("tool", name=name)

    def _on_result(self, name: str, result: str, seconds: float) -> None:
        ok = not result.startswith(("error", "cancelled"))
        self._ui.emit("done", name=name, ok=ok, ms=round(seconds * 1000))
        if ok and name in LISTED and files.LAST:
            self._ui.emit("card", title=f"{len(files.LAST)} file" + ("s" if len(files.LAST) > 1 else ""),
                          rows=[{"label": p.name, "sub": p.parent.name, "open": str(p)} for p in files.LAST[:6]])

    def _timed(self, step: str, started: float) -> float:
        seconds = time.time() - started
        self._ui.emit("timing", step=step, ms=round(seconds * 1000))
        return seconds

    def _cue(self, cue: str, wait: bool = False) -> None:
        if self._cues:
            self._cues.play(cue, "chimera" if self._persona == "chimera" else "", wait)

    def open_listed(self, path: str) -> None:
        """The overlay asks to open a file from a card: only files a tool has just listed are opened."""
        if Path(path) in files.LAST:
            os.startfile(path)

    def use_persona(self, phrase: str) -> None:
        """Answer as the persona that owns this wake phrase (unknown phrase = the main one)."""
        name, voice = self.personas.get(phrase) or next(iter(self.personas.values()))
        self._persona = name
        self._ui.emit("persona", name=name)
        self._tag = "" if voice is next(iter(self.personas.values()))[1] else f"[as {name.capitalize()}] "
        if self._speaker:
            self._speaker.voice = voice

    # -- conversation flow ------------------------------------------------------------------------
    def run(self, wake, by_transcript: bool) -> None:
        """Wait for a wake phrase until the mic source ends. `wake` must spot list(self.personas).
        by_transcript: transcribe whatever is said and wake when it starts with a wake phrase. Reliable for any
        word, but uses the CPU whenever someone talks. Otherwise the spotter alone decides (near-zero CPU,
        but it misses unusual words); either way the spotter is what interrupts speech."""
        self._wake = wake
        names = " / ".join(f'"{p}"' for p in self.personas)
        log(f"ready: say {names}  |  {len(self._menu) - 1} tools  |  " + ", ".join(self.features))
        while True:
            try:
                self._idle_transcript() if by_transcript else self._idle_spotter()
            except EOFError:
                return
            except Exception as e:  # one failed turn (the kit restarting, a bad reply) must not end the assistant
                log(f"  turn failed: {type(e).__name__}: {e}")
                self._barge = []
                self._cue("error")
                self._ui.emit("state", s="idle")
                time.sleep(1)  # if it keeps failing, don't spin

    def _idle_spotter(self) -> None:
        recent = deque(maxlen=15)  # 1.5 s: the wake word is recognised a moment after it is said
        while True:
            frame = self._mic.read()
            recent.append(frame)
            self._listener.observe(frame)
            if (phrase := self._wake.heard(frame)):
                log(f"wake: {phrase}")
                self.use_persona(phrase)
                self._cue("wake")  # not waited for: the command is usually already being spoken
                heard = self._hear(self._l["start_timeout_s"], list(recent))
                rest = _after_wake_word(heard, phrase)
                return self._converse(heard if rest is None else rest)

    def _idle_transcript(self) -> None:
        pcm = self._listener.capture(self._mic, 3600.0)
        if pcm is None or len(pcm) < (self._l["silence_s"] + 0.3) * MIC_RATE:  # a click, not speech
            return
        try:
            text = self._stt.transcribe(pcm)
        except KitError as e:  # not a turn yet: just keep listening
            return log(f"  stt error: {e}")
        for phrase in self.personas:
            if (rest := _after_wake_word(text, phrase)) is not None:
                log(f"wake: {phrase} (heard {text!r})")
                self.use_persona(phrase)
                self._ui.emit("state", s="thinking" if rest else "listening")
                self._ui.emit("heard", text=text)
                self._cue("heard" if rest else "wake", wait=not rest)  # only a bare name leaves us listening
                return self._converse(rest)

    def _converse(self, text: str) -> None:
        """`text` = what was said in the same breath as the wake word ('' = nothing yet, so listen for it)."""
        text = text or self._hear(self._l["start_timeout_s"])
        while text:
            self.answer(text)
            if self._barge:  # cut short by the wake word: what was said after it is the next request
                text = self._hear(self._l["start_timeout_s"])
            else:
                text = self._hear(self._l["follow_up_s"]) if self._l["follow_up_s"] else ""
        self._ui.emit("state", s="idle")

    def _hear(self, timeout_s: float, lead: list = ()) -> str:
        self._ui.emit("state", s="listening")
        barged, self._barge = self._barge, []
        lead = list(lead) or barged
        if not lead:
            self._mic.flush()
        pcm = self._listener.capture(self._mic, timeout_s, lambda v: self._ui.emit("level", v=v), lead)
        if pcm is None:
            return ""
        self._ui.emit("state", s="thinking")
        self._cue("heard")
        t = time.time()
        try:
            text = self._stt.transcribe(pcm)
        except KitError as e:
            log(f"  stt error: {e}")
            self._cue("error")
            return ""
        log(f"heard ({self._timed('stt', t):.2f}s stt): {text!r}")
        if barged:  # the replay holds the end of the reply, the wake word that cut it off, and the new request
            rest = _after_wake_word_in(text, list(self.personas))
            if not rest:  # just the name (or no clear one): it has stopped talking and listens
                return self._hear(self._l["start_timeout_s"])
            if rest.lower().strip(" .!?,") in STOP:  # "Silky, stop": stopping was the whole request
                return ""
            text = rest
        self._ui.emit("heard", text=text)
        return text

    def answer(self, text: str) -> None:
        """One user turn: think, act, speak."""
        with self._busy:
            self._answer(text)

    def _answer(self, text: str) -> None:
        self._ui.emit("state", s="thinking")
        t, first = time.time(), True
        if self._fast_path(text):
            return self._finish_speaking()
        try:
            for s in sentences(self._agent.respond(self._tag + text, self._pick_tool(text))):
                if first:
                    log(f"  first sentence after {self._timed('reply', t):.2f}s")
                    first = False
                if (s := _ECHOED_TAG.sub("", s)):
                    self._say(s)
        except Exception as e:
            log(f"  error: {e}")
            self._cue("error")
            self._say("Sorry, something went wrong talking to the model.")
        self._finish_speaking()

    def _fast_path(self, text: str) -> bool:
        """Known command? Run its tool and speak the canned reply without touching the LLM."""
        if not self._router:
            return False
        t = time.time()
        try:
            route, score = self._router.match(text)
        except KitError as e:
            log(f"  fast path error: {e}")
            return False
        if not route:
            log(f"  no route (best {score:.2f}, {time.time() - t:.3f}s) -> LLM")
            return False
        self._on_tool(route.tool, json.dumps(route.args))
        result = self._tools.call(route.tool, json.dumps(route.args))
        if result.startswith(("error", "cancelled")):
            return False  # let the LLM explain or try another way
        log(f"  routed {route.tool} {route.args or ''} (score {score:.2f}, {self._timed('route', t):.3f}s, no LLM)")
        reply = route.reply.format(result=result)
        self._agent.note(text, reply)
        self._say(reply)
        return True

    def _pick_tool(self, text: str) -> str:
        """-> a hint naming the tool the decision model is sure this request needs ('' = the LLM decides).
        (A "call no tool" hint was tried for plain talk and made LFM3's answers worse, so there is none.)"""
        if not (self._decider and self._decide["tools"]):
            return ""
        t = time.time()
        try:
            a = self._decider.decide({"tool": {
                "type": "choice", "instructions": "Which tool must the assistant call to do what the user asked?",
                "criteria": self._menu}}, state=f'The user said to their voice assistant: "{text}"')["tool"]
        except (KitError, KeyError) as e:
            log(f"  decision model error: {e}")
            return ""
        log(f"  decided {a['choice']} ({a['confidence']:.2f}, {self._timed('decide', t):.3f}s)")
        if a["confidence"] < self._decide["sure"]:
            return ""
        return f"Call the {a['choice']} tool for this request." if a["choice"] != "none" else ""

    def _say(self, sentence: str) -> None:
        log(f"  say: {sentence}")
        self._ui.emit("state", s="speaking")
        if self._speaker:
            self._speaker.say(sentence)
        else:
            self._ui.emit("said", text=sentence)

    def _finish_speaking(self) -> None:
        """Wait for speech to end; saying the wake word cuts it short."""
        if not self._speaker:
            return
        if not self._mic or getattr(self._background, "on", False):  # typed mode or a background turn: just wait
            return self._speaker.wait()
        done = threading.Event()
        threading.Thread(target=lambda: (self._speaker.wait(), done.set()), daemon=True).start()
        self._mic.flush()
        recent, barged = deque(maxlen=15), False  # 1.5 s: the wake word is recognised a moment after it is said
        while not done.is_set():
            try:
                frame = self._mic.read()
                recent.append(frame)
                if self._wake.heard(frame) and not barged:
                    log("  interrupted")
                    self._speaker.stop()
                    barged = True
            except EOFError:
                done.wait()
        if barged:  # keep the wake word and what followed, for _hear to replay: "Silky, stop. What time is it?"
            self._barge = list(recent)

    # -- Host slot: background features (reminders, screen watches) speak through this ---------------------
    def announce(self, event: str, then: str = "") -> None:
        self._background.on = True  # this thread must not listen to the mic: the main loop owns it
        with self._busy:
            log(f"  announce: {event}")
            self._ui.emit("state", s="speaking")
            self._cue("notify", wait=True)
            try:
                for sentence in sentences(self._agent.respond(
                        f"[an event, not something the user said] {event}",
                        "Do not call a tool. Tell the user this in one short sentence.")):
                    if (sentence := _ECHOED_TAG.sub("", sentence)):
                        self._say(sentence)
            except Exception as e:
                log(f"  error: {e}")
                self._say(event)
            if then and self._is_command(then):
                self._answer(then)
            self._finish_speaking()
            self._ui.emit("state", s="idle")

    def _is_command(self, then: str) -> bool:
        """A follow-up is carried out only if it asks for more than being told (which has just happened)."""
        if not self._decider:
            return False
        try:
            a = self._decider.decide({"act": {"type": "noul", "instructions":
                                              "Does this ask for something to be done other than telling, notifying or reminding the user?"}},
                                     state=f'Instruction: "{then}"')
            return a["act"]["noul"] >= 0.5
        except (KitError, KeyError):
            return False

    # -- confirming risky tools -----------------------------------------------------------------------
    def _agreed(self, question: str, reply: str) -> bool:
        """Did the spoken reply mean yes? The decision model judges it ('go for it', 'nah, leave it');
        without one, only a reply that starts with a plain yes-word counts."""
        if self._decider and reply:
            try:
                a = self._decider.decide(
                    {"yes": {"type": "noul", "instructions": "Did the user clearly agree that the assistant should go ahead?"}},
                    state=f'The assistant asked: "{question}" The user replied: "{reply}"')
                return a["yes"]["noul"] >= 0.8
            except (KitError, KeyError):
                pass
        return reply.startswith(YES)

    def _confirm(self, question: str) -> bool:
        if not self._mic or getattr(self._background, "on", False):  # typed mode and background turns can't hear a yes
            log("  risky tool declined: confirmation needs the microphone (or tools.policy = \"auto\")")
            return False
        self._say(question)
        self._finish_speaking()
        reply = self._hear(self._l["start_timeout_s"]).lower().strip(" .!,")
        ok = self._agreed(question, reply)
        log(f"  confirm: {ok}")
        return ok


def main() -> None:
    ap = argparse.ArgumentParser(prog="agentd", description="Local voice agent daemon")
    ap.add_argument("--config", type=Path, default=ROOT / "config.toml")
    ap.add_argument("--text", help="answer this one typed command and exit (no microphone, no wake word)")
    ap.add_argument("--wav", help="use a 16 kHz mono WAV file as the microphone, exit when it ends")
    ap.add_argument("--mute", action="store_true", help="don't speak (captions and log only)")
    ap.add_argument("--as", dest="persona", default="", help="with --text: the wake phrase to act as, e.g. chimera")
    ap.add_argument("--index", action="store_true", help="bring the file-search index up to date and exit")
    ap.add_argument("--doctor", action="store_true", help="check that everything the daemon needs is in place, and exit")
    ap.add_argument("--no-overlay", action="store_true")
    args = ap.parse_args()
    sys.stdout.reconfigure(errors="replace")  # a model emoji must not crash a cp1252 console
    cfg = tomllib.loads(args.config.read_text(encoding="utf-8"))
    if args.doctor:
        from .doctor import report
        raise SystemExit(report(cfg, ROOT))
    if args.index:
        return Daemon(cfg, NoUi(), mute=True).refresh_index(verbose=True)

    def work(ui):
        if args.text:
            d = Daemon(cfg, ui, mute=args.mute)
            if hasattr(ui, "on_open"):
                ui.on_open = d.open_listed
            d.use_persona(args.persona)
            d.answer(args.text)
            ui.emit("state", s="idle")
            return
        from .mic import DeviceMic, FileMic
        from .wake import SherpaWake
        w = cfg["wake"]
        d = Daemon(cfg, ui, FileMic(args.wav) if args.wav else DeviceMic(), mute=args.mute)
        if hasattr(ui, "on_open"):
            ui.on_open = d.open_listed
        d.run(SherpaWake(ROOT / "models" / "kws", list(d.personas), w["threshold"], w["boost"]),
              by_transcript=w["engine"] == "transcript")

    o = cfg["overlay"]
    if o["enabled"] and not args.no_overlay:
        from .overlay import Overlay
        head = ROOT / "engines" / "chimera" / "head.js"  # Chimera's own 3D head, if setup-chimera.ps1 built it
        skins = {"chimera": head} if cfg["chimera"]["head"] and head.exists() else {}
        ui = Overlay(o["width"], o["height"], o["margin"], o["linger_s"], skins, o["card_s"])
        ui.run(lambda: work(ui))
    else:
        work(NoUi())


if __name__ == "__main__":
    main()
