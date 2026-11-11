"""Brick: the inference kit (llama-swap-kit), reached only through its CONTRACT.md:
roles on an OpenAI-compatible endpoint. Provides the Llm, Stt, Voice and Embedder slots.
Swapping the inference server touches this file only.
"""
import base64
import http.client
import io
import json
import uuid
import wave
from urllib.parse import urlparse

import numpy as np

from .contracts import MIC_RATE


class KitError(RuntimeError):
    pass


class Kit:
    def __init__(self, url: str, timeout: float = 600):
        u = urlparse(url)
        self._addr, self._timeout = (u.hostname, u.port or 80), timeout

    def post(self, path: str, body: bytes, ctype: str = "application/json") -> http.client.HTTPResponse:
        conn = http.client.HTTPConnection(*self._addr, timeout=self._timeout)
        try:
            conn.request("POST", path, body, {"Content-Type": ctype})
            r = conn.getresponse()
        except OSError as e:
            raise KitError(f"inference kit unreachable at {self._addr[0]}:{self._addr[1]} ({e})") from e
        if r.status != 200:
            raise KitError(f"{path} -> {r.status}: {r.read(500).decode(errors='replace')}")
        return r

    def models(self) -> set[str]:
        """Every model id and role the kit serves."""
        try:
            conn = http.client.HTTPConnection(*self._addr, timeout=5)
            conn.request("GET", "/v1/models")
            data = json.loads(conn.getresponse().read())["data"]
        except (OSError, ValueError, KeyError) as e:
            raise KitError(f"cannot list the kit's models ({e})") from e
        return {m["id"] for m in data} | {a for m in data for a in m.get("meta", {}).get("llamaswap", {}).get("aliases", [])}

    def healthy(self) -> bool:
        try:
            conn = http.client.HTTPConnection(*self._addr, timeout=3)
            conn.request("GET", "/health")
            return conn.getresponse().status == 200
        except OSError:
            return False


class KitLlm:
    def __init__(self, kit: Kit, role: str, max_tokens: int, temperature: float, extra: dict | None = None):
        """extra: more fields for every request, e.g. {"chat_template_kwargs": {"enable_thinking": False}}."""
        self._kit, self._base = kit, {"model": role, "stream": True, "max_tokens": max_tokens,
                                      "temperature": temperature, **(extra or {})}

    def stream(self, messages, tools):
        body = dict(self._base, messages=messages)
        if tools:
            body["tools"] = tools
        calls: dict[int, dict] = {}
        for line in self._kit.post("/v1/chat/completions", json.dumps(body).encode()):
            if not line.startswith(b"data: ") or line.startswith(b"data: [DONE]"):
                continue
            choices = json.loads(line[6:]).get("choices") or [{}]
            delta = choices[0].get("delta") or {}
            if delta.get("content"):
                yield "text", delta["content"]
            for tc in delta.get("tool_calls") or []:
                c = calls.setdefault(tc.get("index", 0), {"id": "", "name": "", "arguments": ""})
                fn = tc.get("function") or {}
                c["id"] = tc.get("id") or c["id"]
                c["name"] += fn.get("name") or ""
                c["arguments"] += fn.get("arguments") or ""
        if calls:
            yield "tools", [calls[i] for i in sorted(calls)]


class KitDecider:
    """A decision model served by the kit's llama.cpp (d1): its /v1/systemone endpoint, reached per model."""

    def __init__(self, kit: Kit, model: str):
        self._kit, self._path = kit, f"/upstream/{model}/v1/systemone"

    def decide(self, questions, state=None, images=()):
        body = {"state": state, "questions": questions}
        if images:
            body["images"] = ["data:image/png;base64," + base64.b64encode(i).decode() for i in images]
        return json.loads(self._kit.post(self._path, json.dumps(body).encode()).read())["answers"]


class KitEmbedder:
    def __init__(self, kit: Kit, role: str):
        self._kit, self._role = kit, role

    def embed(self, texts):
        r = self._kit.post("/v1/embeddings", json.dumps({"model": self._role, "input": texts}).encode())
        rows = sorted(json.loads(r.read())["data"], key=lambda d: d["index"])
        v = np.array([d["embedding"] for d in rows], np.float32)
        return v / np.linalg.norm(v, axis=1, keepdims=True)


def _wav(pcm: np.ndarray, rate: int) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes((np.clip(pcm, -1, 1) * 32767).astype("<i2").tobytes())
    return buf.getvalue()


class KitStt:
    def __init__(self, kit: Kit, role: str):
        self._kit, self._role = kit, role

    def transcribe(self, pcm):
        b = uuid.uuid4().hex
        body = (f'--{b}\r\nContent-Disposition: form-data; name="model"\r\n\r\n{self._role}\r\n'
                f'--{b}\r\nContent-Disposition: form-data; name="file"; filename="a.wav"\r\n'
                f'Content-Type: audio/wav\r\n\r\n').encode() + _wav(pcm, MIC_RATE) + f"\r\n--{b}--\r\n".encode()
        r = self._kit.post("/v1/audio/transcriptions", body, f"multipart/form-data; boundary={b}")
        text = json.loads(r.read()).get("text", "").strip()
        return "" if text.startswith(("[", "(")) else text  # whisper's [BLANK_AUDIO] / (silence)


class KitVoice:
    def __init__(self, kit: Kit, role: str, voice: str = ""):
        self._kit, self._body = kit, {"model": role, **({"voice": voice} if voice else {})}

    def synth(self, text):
        r = self._kit.post("/v1/audio/speech", json.dumps(dict(self._body, input=text)).encode())
        with wave.open(io.BytesIO(r.read())) as w:
            pcm = np.frombuffer(w.readframes(w.getnframes()), "<i2").astype(np.float32) / 32768
            if w.getnchannels() > 1:
                pcm = pcm.reshape(-1, w.getnchannels()).mean(1)
            return pcm, w.getframerate()
