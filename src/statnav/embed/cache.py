"""On-disk cache for Jina calls, so re-indexing, re-running evals and CI never pay twice.

Embeddings are keyed by (model, task, sha256(text)); rerank results by
(model, sha256(query), sha256(document texts)).
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import threading
from pathlib import Path

import numpy as np

_SCHEMA = """
CREATE TABLE IF NOT EXISTS embeddings (
    key TEXT PRIMARY KEY, model TEXT, task TEXT, dim INTEGER, vec BLOB
);
CREATE TABLE IF NOT EXISTS reranks (key TEXT PRIMARY KEY, model TEXT, result TEXT);
"""


def sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


class JinaCache:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(path, check_same_thread=False)
        self._conn.executescript(_SCHEMA)
        self._lock = threading.Lock()

    @classmethod
    def default(cls) -> JinaCache:
        from statnav.config import ROOT, base_config
        return cls(ROOT / base_config()["paths"]["cache_dir"] / "jina.sqlite")

    @staticmethod
    def emb_key(model: str, task: str, text: str) -> str:
        return f"{model}|{task}|{sha(text)}"

    def get_embeddings(self, keys: list[str]) -> dict[str, np.ndarray]:
        out: dict[str, np.ndarray] = {}
        for i in range(0, len(keys), 500):
            part = keys[i:i + 500]
            marks = ",".join("?" * len(part))
            with self._lock:
                rows = self._conn.execute(
                    f"SELECT key, vec FROM embeddings WHERE key IN ({marks})", part).fetchall()
            for k, blob in rows:
                out[k] = np.frombuffer(blob, dtype=np.float32)
        return out

    def put_embeddings(self, model: str, task: str, items: dict[str, np.ndarray]) -> None:
        rows = [(k, model, task, len(v), np.asarray(v, dtype=np.float32).tobytes())
                for k, v in items.items()]
        with self._lock, self._conn:
            self._conn.executemany(
                "INSERT OR REPLACE INTO embeddings VALUES (?, ?, ?, ?, ?)", rows)

    @staticmethod
    def rerank_key(model: str, query: str, docs: list[str]) -> str:
        return f"{model}|{sha(query)}|{sha(json.dumps(docs))}"

    def get_rerank(self, key: str) -> list[dict] | None:
        with self._lock:
            row = self._conn.execute("SELECT result FROM reranks WHERE key = ?", (key,)).fetchone()
        return json.loads(row[0]) if row else None

    def put_rerank(self, key: str, model: str, result: list[dict]) -> None:
        with self._lock, self._conn:
            self._conn.execute("INSERT OR REPLACE INTO reranks VALUES (?, ?, ?)",
                               (key, model, json.dumps(result)))

    def stats(self) -> dict[str, int]:
        with self._lock:
            e = self._conn.execute("SELECT COUNT(*) FROM embeddings").fetchone()[0]
            r = self._conn.execute("SELECT COUNT(*) FROM reranks").fetchone()[0]
        return {"embeddings": e, "reranks": r}
