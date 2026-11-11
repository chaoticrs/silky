"""Brick: wake word. Fills the Wake slot with sherpa-onnx's open-vocabulary keyword spotter:
any English phrases work without training, at well under 1% of one CPU core.
"""
import tempfile
from pathlib import Path

import sherpa_onnx
from sentencepiece import SentencePieceProcessor

from .contracts import MIC_RATE


class SherpaWake:
    def __init__(self, model_dir: Path, phrases: list[str], threshold: float = 0.2, boost: float = 2.0):
        def one(pattern):
            hits = sorted(model_dir.glob(pattern))
            if not hits:
                raise FileNotFoundError(f"{pattern} not in {model_dir}; run setup.ps1")
            return str(hits[0])

        tokens = one("tokens.txt")
        bpe = SentencePieceProcessor(model_file=one("bpe.model"))
        self._names = {p.replace(" ", "_"): p for p in phrases}  # the spotter reports names without spaces
        lines = [f"{' '.join(bpe.encode(p.upper(), out_type=str))} :{boost} #{threshold} @{n}"
                 for n, p in self._names.items()]
        with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False, encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")  # the spotter only takes keywords as a file; one per instance
        self._kws = sherpa_onnx.KeywordSpotter(
            tokens=tokens, encoder=one("encoder*chunk-16*.int8.onnx"), decoder=one("decoder*chunk-16*[!8].onnx"),
            joiner=one("joiner*chunk-16*.int8.onnx"), keywords_file=f.name, num_threads=1, provider="cpu")
        Path(f.name).unlink()
        self._s = self._kws.create_stream()

    def heard(self, frame):
        self._s.accept_waveform(MIC_RATE, frame)
        hit = None
        while self._kws.is_ready(self._s):
            self._kws.decode_stream(self._s)
            if (name := self._kws.get_result(self._s)):
                hit = self._names.get(name, name)
                self._kws.reset_stream(self._s)
        return hit
