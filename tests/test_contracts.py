"""Contract tests: pin what each brick promises, using fakes for its neighbours.
Run:  .venv/Scripts/python.exe -m tests.test_contracts
"""
import numpy as np

from agentd.agent import Agent
from agentd.contracts import FRAME
from agentd.listen import Listener
from agentd.speak import sentences
from agentd.tools.registry import Toolbox, tool


@tool("test: echo")
def _echo(text: str, times: int = 1) -> str:
    return text * times


@tool("test: danger", risky=True)
def _danger() -> str:
    return "boom"


def test_sentences():
    out = list(sentences(["Hello the", "re, **world**. This is ", "the second one! tail"]))
    assert out == ["Hello there, world.", "This is the second one!", "tail"], out


def test_toolbox():
    asked = []
    box = Toolbox("confirm", lambda q: asked.append(q) or False)
    spec = next(s for s in box.specs() if s["function"]["name"] == "_echo")["function"]["parameters"]
    assert spec["required"] == ["text"] and spec["properties"]["times"] == {"type": "integer"}
    assert box.call("_echo", '{"text": "ab", "times": 2}') == "abab"
    assert box.call("_danger", "{}").startswith("cancelled") and asked
    assert box.call("nope", "{}").startswith("error") and box.call("_echo", "{bad").startswith("error")
    assert Toolbox("auto", lambda q: False).call("_danger", "{}") == "boom"
    assert "_danger" not in [s["function"]["name"] for s in Toolbox("readonly", lambda q: True).specs()]


class FakeLlm:
    def __init__(self):
        self.seen = []

    def stream(self, messages, tools):
        self.seen.append(messages)
        if messages[-1]["role"] == "user":
            yield "tools", [{"id": "1", "name": "_echo", "arguments": '{"text": "hi"}'}]
        else:
            yield "text", "It said "
            yield "text", messages[-1]["content"]


def test_agent():
    llm, used = FakeLlm(), []
    agent = Agent(llm, Toolbox("auto", lambda q: True), "sys", history_turns=2, on_tool=lambda name, arguments: used.append(name))
    assert "".join(agent.respond("go")) == "It said hi" and used == ["_echo"]
    roles = [m["role"] for m in llm.seen[-1]]
    assert roles == ["system", "user", "assistant", "tool"], roles
    for _ in range(3):
        list(agent.respond("again"))
    assert sum(m["role"] == "user" for m in llm.seen[-1]) == 2  # history is capped


class FakeMic:
    def __init__(self, pcm):
        self.frames = [pcm[i:i + FRAME] for i in range(0, len(pcm) - FRAME + 1, FRAME)]

    def read(self):
        if not self.frames:
            raise EOFError
        return self.frames.pop(0)

    def flush(self):
        pass


def test_listener():
    quiet = lambda s: np.zeros(int(16000 * s), np.float32)
    voice = (0.2 * np.sin(np.arange(16000) * 0.2)).astype(np.float32)
    got = Listener(silence_s=0.5).capture(FakeMic(np.concatenate([quiet(1), voice, quiet(2)])), 3.0)
    assert got is not None and 1.4 <= len(got) / 16000 <= 2.0, len(got) / 16000
    assert Listener().capture(FakeMic(quiet(3)), 1.0) is None

    class Sure:  # a TurnEnd that always says "finished": the utterance ends at quick_s, not silence_s
        def finished(self, pcm):
            return 0.95
    clip = np.concatenate([quiet(1), voice, quiet(2)])
    early = Listener(silence_s=1.5, turn=Sure(), quick_s=0.3).capture(FakeMic(clip), 3.0)
    late = Listener(silence_s=1.5).capture(FakeMic(clip), 3.0)
    assert len(late) - len(early) >= 16000, (len(early), len(late))


class FakeEmbedder:
    """Bag of words over a tiny vocabulary: enough to give direction to the router's maths."""
    VOCAB = ["time", "volume", "up", "down", "joke"]

    def embed(self, texts):
        v = np.array([[1.0 * (w in t.split()) for w in self.VOCAB] + [0.01] for t in texts], np.float32)
        return v / np.linalg.norm(v, axis=1, keepdims=True)


def test_router():
    from agentd.router import Route, Router
    up, down = Route("media_key", ["volume up"], {"action": "volume_up"}), Route("media_key", ["volume down"])
    r = Router(FakeEmbedder(), [Route("get_time", ["time"]), up, down], threshold=0.8, margin=0.1)
    assert r.match("Volume up!")[0] is up and r.match("time")[0].tool == "get_time"
    assert r.match("volume")[0] is None      # ties between two routes are refused
    assert r.match("tell a joke")[0] is None  # unknown intent goes to the LLM


def test_chimera_settings(tmp=None):
    import tempfile
    from pathlib import Path
    from agentd.chimera import ChimeraVoice
    d = Path(tempfile.mkdtemp())
    (d / "chimera-say.exe").write_bytes(b"")
    v = ChimeraVoice(d)
    assert "rate 2" in v.adjust(rate=9, breathiness=None) and v.settings["breathiness"] == 0.15  # clamped; None kept
    assert v.adjust("female", pitch_hz=180) and v.settings["female"] == 1 and v.settings["rate"] == 1
    assert v.adjust("robot").startswith("error") and ChimeraVoice(d).settings["pitch_hz"] == 180  # persisted


class WordEmbedder:
    """Each word lands in one of 64 slots: texts that share words point the same way."""

    def embed(self, texts):
        import zlib
        v = np.full((len(texts), 64), 0.01, np.float32)
        for row, text in zip(v, texts):
            for word in text.lower().replace(":", " ").replace(".", " ").split():
                row[zlib.crc32(word.encode()) % 64] += 1
        return v / np.linalg.norm(v, axis=1, keepdims=True)


def _tmp():
    import tempfile
    from pathlib import Path
    return Path(tempfile.mkdtemp())


def test_cues():
    from agentd.cues import CUES, RATE, render
    for cue in CUES:
        for persona in ("", "chimera"):
            pcm = render(cue, persona, 0.2)
            assert pcm.dtype == np.float32 and 0.04 * RATE < len(pcm) < RATE and abs(float(np.abs(pcm).max()) - 0.2) < 1e-3
    assert not np.allclose(render("wake"), render("wake", "chimera"))  # each persona has its own sound


def test_index():
    from agentd.index import FileIndex
    d = _tmp()
    (d / "docs").mkdir()
    (d / "docs" / "amplifier notes.txt").write_text("the operational amplifier has a very high gain", encoding="utf-8")
    (d / "docs" / "shopping.md").write_text("buy milk eggs and bread from the market", encoding="utf-8")
    (d / "docs" / "save.sim1").write_text("ignored program data", encoding="utf-8")
    index = FileIndex(WordEmbedder(), d / "store", [d / "docs"])
    assert index.refresh() == (2, 2) and index.refresh() == (0, 2)       # incremental; unknown file types are left out
    assert index.search("operational amplifier gain")[0][1].endswith("amplifier notes.txt")
    assert FileIndex(WordEmbedder(), d / "store", [d / "docs"]).search("bread and milk")[0][1].endswith("shopping.md")  # persisted
    (d / "docs" / "shopping.md").unlink()
    assert index.refresh() == (0, 1) and len(index.search("milk")) == 1   # a deleted file leaves the index


def test_memory():
    from agentd.tools.memory import Memory
    d = _tmp()
    m = Memory(WordEmbedder(), d)
    m.add("The bike lock code is 4172.")
    m.add("The landlord is called Mr Sharma.")
    hit = Memory(WordEmbedder(), d).find("what is the bike lock code")     # persisted, found by meaning
    assert hit and m.facts[hit[0][1]]["text"].startswith("The bike lock")
    assert m.find("quantum chromodynamics") == []                           # nothing close enough: say so
    assert m.drop(hit[0][1]).startswith("The bike") and len(m.facts) == 1


def test_reminders():
    import time
    from agentd.tools.reminders import Reminders, clock_time
    now = time.mktime((2026, 11, 11, 15, 0, 0, 0, 0, -1))
    assert clock_time("6 pm", now) - now == 3 * 3600 and clock_time("18:30", now) - now == 3.5 * 3600
    assert clock_time("9am", now) - now == 18 * 3600 and clock_time("soon", now) is None   # past today -> tomorrow

    class Host:
        said = []

        def announce(self, event, then=""):
            self.said.append(event)
    d = _tmp()
    r = Reminders(Host(), d / "r.json")
    r.add("stretch", time.time() + 0.3)
    r.add("call mom", time.time() + 3600)
    r.add("missed one", time.time() - 600)
    assert len(Reminders(Host(), d / "r.json").items) == 3                  # survives a restart
    r.start()
    time.sleep(0.9)
    assert len(Host.said) == 2 and "stretch" in " ".join(Host.said) and "while the assistant was not running" in " ".join(Host.said)
    assert r.cancel("mom") == 1 and r.items == []


def test_sight_and_lookout():
    from agentd.sight import Sight
    from agentd.tools import lookout
    looks = []

    class Decider:
        def decide(self, questions, state=None, images=()):
            looks.append((state, images))
            yes = 0.9 if len(looks) >= 3 else 0.1                           # it shows up on the third look
            return {k: {"noul": yes} if q["type"] == "noul" else {"choice": "code", "confidence": 0.8}
                    for k, q in questions.items()}
    sight = Sight(Decider(), lambda window_only=False: b"png", lambda: ["Notes - Notepad"], sure=0.6)
    assert sight.wait_until("is it there", 5, 0.01) and len(looks) == 4     # yes twice in a row, not once
    assert "Notes - Notepad" in looks[0][0] and looks[0][1] == [b"png"]      # the model gets titles and picture
    assert sight.describe("is it there").startswith("yes (90% sure)")

    class Host:
        def announce(self, event, then=""):
            pass
    check = lookout.install(sight, Host(), verify_s=1, log=lambda m: None)
    assert "confirmed" in check("open_app", {"name": "notepad"}, "opened notepad")
    assert check("get_time", {}, "noon") == "noon"                           # only tools that change the screen


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("ok", name)
