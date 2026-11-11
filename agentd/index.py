"""Brick: find files by meaning. Reads the text of the user's documents, embeds it in chunks with
the Embedder slot, and answers a spoken description ("my notes about op-amps") with the files whose
content, or name, is closest in meaning. Everything stays on this PC, in `store`.

refresh() is incremental: only new or changed files are read again. Pictures, media, archives and
installers have no text to read but are still findable through their name and folder; file types
that are neither (program data, game saves...) are left out so they don't crowd the index.
"""
import json
import re
import zipfile
from pathlib import Path
from typing import Callable

import numpy as np

from .contracts import Embedder

TEXT = {".txt", ".md", ".rst", ".csv", ".json", ".tex", ".py", ".js", ".ts", ".c", ".h", ".cpp", ".java",
        ".rs", ".go", ".html", ".css", ".sql", ".ps1", ".sh", ".toml", ".yaml", ".yml", ".ipynb", ".v", ".m", ".ino"}
OFFICE = {".docx": "word/document.xml", ".pptx": "ppt/slides/", ".xlsx": "xl/sharedStrings.xml", ".odt": "content.xml"}
BY_NAME = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".svg", ".mp3", ".wav", ".flac", ".m4a", ".mp4", ".mkv",
           ".mov", ".avi", ".zip", ".rar", ".7z", ".exe", ".msi", ".iso", ".doc", ".ppt", ".xls", ".epub", ".apk"}
KNOWN = TEXT | OFFICE.keys() | BY_NAME | {".pdf"}
SKIP_DIRS = {"node_modules", "__pycache__", "site-packages", "venv", "env", "target", "build", "dist", "AppData"}
QUERY = "Represent this sentence for searching relevant passages: "  # what bge models expect in front of a query
_TAG, _SPACE = re.compile(r"<[^>]+>"), re.compile(r"\s+")


def read_text(path: Path, limit: int = 60_000) -> str:
    """The readable text of a file ('' if it has none or can't be read). At most `limit` characters."""
    ext = path.suffix.lower()
    try:
        if ext in TEXT:
            with path.open(encoding="utf-8", errors="ignore") as f:
                raw = f.read(limit)
        elif ext in OFFICE:
            with zipfile.ZipFile(path) as z:
                parts = sorted(n for n in z.namelist() if n.startswith(OFFICE[ext]) and n.endswith(".xml"))
                raw = _TAG.sub(" ", " ".join(z.read(n).decode("utf-8", "ignore") for n in parts[:40]))
        elif ext == ".pdf":
            from pypdf import PdfReader
            raw = " ".join(page.extract_text() or "" for page in PdfReader(path).pages[:25])
        else:
            return ""
    except Exception:  # a broken or locked file is simply not searchable by content
        return ""
    return _SPACE.sub(" ", raw)[:limit].strip()


class FileIndex:
    def __init__(self, embedder: Embedder, store: Path, folders: list[Path], max_files: int = 4000,
                 max_mb: float = 25, chunk_chars: int = 800):
        self._embedder, self._store, self._folders = embedder, store, folders
        self._max_files, self._max_bytes, self._chunk = max_files, max_mb * 2**20, chunk_chars
        self._files: dict[str, list] = {}   # path -> [mtime, size]
        self._rows: list[list] = []         # one per vector: [path, text of the chunk]
        self._vectors = np.zeros((0, 1), np.float32)
        try:
            meta = json.loads((store / "meta.json").read_text(encoding="utf-8"))
            vectors = np.load(store / "vectors.npy")
            if len(vectors) == len(meta["rows"]):
                self._files, self._rows, self._vectors = meta["files"], meta["rows"], vectors
        except (OSError, ValueError, KeyError):
            pass  # no index yet, or a damaged one: start empty

    def __len__(self) -> int:
        return len(self._files)

    def _walk(self):
        n = 0
        for folder in self._folders:
            stack = [folder]
            while stack:
                try:
                    entries = sorted(stack.pop().iterdir())
                except OSError:
                    continue
                for p in entries:
                    if p.name.startswith((".", "~$")):
                        continue
                    if p.is_dir():
                        if p.name not in SKIP_DIRS:
                            stack.append(p)
                    elif p.suffix.lower() in KNOWN and (n := n + 1) <= self._max_files:
                        yield p

    def _chunks(self, path: Path) -> list[str]:
        name = f"{path.stem.replace('_', ' ').replace('-', ' ')} ({path.suffix.lstrip('.')} file in {path.parent.name})"
        text = read_text(path) if path.stat().st_size <= self._max_bytes else ""
        body = [text[i:i + self._chunk] for i in range(0, len(text), self._chunk - 100)][:60]
        return [name] + [f"{path.stem}: {c}" for c in body]

    def _embed(self, texts: list[str]) -> np.ndarray:
        try:
            return self._embedder.embed(texts)
        except RuntimeError:  # most likely a chunk longer than the model's window: go one by one, shorter
            return np.concatenate([self._embedder.embed([t[:350]]) for t in texts])

    def refresh(self, on_progress: Callable[[int, int], None] = lambda done, total: None) -> tuple[int, int]:
        """Bring the index up to date with the folders. -> (files read this time, files in the index)."""
        seen, todo = {}, []
        for p in self._walk():
            try:
                st = p.stat()
            except OSError:
                continue
            seen[str(p)] = [int(st.st_mtime), st.st_size]
            if self._files.get(str(p)) != seen[str(p)]:
                todo.append(p)
        stale = {str(p) for p in todo} | (self._files.keys() - seen.keys())
        keep = [i for i, r in enumerate(self._rows) if r[0] not in stale]
        rows, vectors = [self._rows[i] for i in keep], [self._vectors[keep]] if keep else []
        batch: list[list] = []

        def flush():
            if batch:
                vectors.append(self._embed([text for _, text in batch]))
                rows.extend(batch)
                batch.clear()

        for done, p in enumerate(todo, 1):
            try:
                batch += [[str(p), c] for c in self._chunks(p)]
            except OSError:
                seen.pop(str(p), None)
            if len(batch) >= 24:
                flush()
                on_progress(done, len(todo))
        flush()
        matrix = np.concatenate(vectors) if vectors else np.zeros((0, 1), np.float32)
        self._files, self._rows, self._vectors = seen, rows, matrix  # rows and vectors swap in together
        if todo or stale:
            self._store.mkdir(parents=True, exist_ok=True)
            np.save(self._store / "vectors.npy", self._vectors)
            (self._store / "meta.json").write_text(json.dumps({"files": seen, "rows": rows}), encoding="utf-8")
        return len(todo), len(seen)

    def search(self, query: str, k: int = 5) -> list[tuple[float, str, str]]:
        """-> up to k (score 0..1, path, the passage that matched), best first, one entry per file."""
        if not self._rows:
            return []
        rows, vectors = self._rows, self._vectors  # refresh() may swap these in from another thread
        if len(rows) != len(vectors):  # caught mid-swap: take the new pair
            rows, vectors = self._rows, self._vectors
        sims = vectors @ self._embedder.embed([QUERY + query])[0]
        hits, used = [], set()
        for i in np.argsort(-sims):
            path, text = rows[i]
            if path not in used:
                used.add(path)
                hits.append((float(sims[i]), path, text[:160]))
                if len(hits) == k:
                    break
        return hits
