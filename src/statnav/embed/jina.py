"""Jina AI client for embeddings and reranking, with caching, batching and rate limiting.

    from statnav.embed.jina import JinaClient
    jc = JinaClient.from_config()
    vecs = jc.embed(["text ..."], task="retrieval.passage")   # np.ndarray (n, 1024)
    hits = jc.rerank("query", ["doc a", "doc b"], top_n=5)    # [{"index", "score"}]

Every call goes through JinaCache first; only cache misses reach the API. `usage` tracks the
tokens actually billed in this process so runs can report their spend.
"""

from __future__ import annotations

import os
import time
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path

import httpx
import numpy as np
from tenacity import retry, retry_if_exception, stop_after_attempt, wait_exponential

from statnav.config import ROOT, base_config
from statnav.embed import tokens
from statnav.embed.cache import JinaCache
from statnav.obs.logging import get_logger

log = get_logger("embed.jina")


class JinaError(RuntimeError):
    pass


def _retryable(exc: BaseException) -> bool:
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code == 429 or exc.response.status_code >= 500
    return isinstance(exc, httpx.TransportError)


@dataclass
class Usage:
    tokens: int = 0
    requests: int = 0
    cache_hits: int = 0
    cache_misses: int = 0


@dataclass
class RateLimiter:
    """Sliding one-minute window over requests and (estimated) tokens."""

    requests_per_minute: int
    tokens_per_minute: int
    _events: deque = field(default_factory=deque)

    def wait(self, n_tokens: int) -> None:
        while True:
            now = time.monotonic()
            while self._events and now - self._events[0][0] > 60:
                self._events.popleft()
            used_tokens = sum(t for _, t in self._events)
            if (len(self._events) < self.requests_per_minute
                    and used_tokens + n_tokens <= self.tokens_per_minute):
                self._events.append((now, n_tokens))
                return
            time.sleep(max(0.5, 60 - (now - self._events[0][0])))


class JinaClient:
    def __init__(self, api_key: str, base_url: str, embed_model: str, rerank_model: str,
                 dimensions: int, batch_size: int, cache: JinaCache, limiter: RateLimiter,
                 timeout: float = 60, transport: httpx.BaseTransport | None = None):
        self.embed_model = embed_model
        self.rerank_model = rerank_model
        self.dimensions = dimensions
        self.batch_size = batch_size
        self.cache = cache
        self.limiter = limiter
        self.usage = Usage()
        self._http = httpx.Client(
            base_url=base_url, timeout=timeout, transport=transport,
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json",
                     "Accept": "application/json"})

    @classmethod
    def from_config(cls, cache_path: Path | None = None,
                    transport: httpx.BaseTransport | None = None) -> JinaClient:
        cfg = base_config()
        j, e, r = cfg["jina"], cfg["embeddings"], cfg["reranker"]
        key = j.get("api_key") or os.environ.get("JINA_API_KEY", "")
        if not key and transport is None:
            raise JinaError("JINA_API_KEY is not set (add it to .env)")
        cache = JinaCache(cache_path or ROOT / cfg["paths"]["cache_dir"] / "jina.sqlite")
        return cls(key, j["base_url"], e["model"], r["model"], e["dimensions"], e["batch_size"],
                   cache, RateLimiter(j["requests_per_minute"], j["tokens_per_minute"]),
                   j["timeout_seconds"], transport)

    # -- HTTP -------------------------------------------------------------------------------
    @retry(retry=retry_if_exception(_retryable), stop=stop_after_attempt(6),
           wait=wait_exponential(multiplier=2, min=2, max=60), reraise=True)
    def _post(self, path: str, payload: dict, est_tokens: int) -> dict:
        self.limiter.wait(est_tokens)
        resp = self._http.post(path, json=payload)
        if resp.status_code >= 400:
            if resp.status_code in (401, 402, 403):
                raise JinaError(f"Jina {resp.status_code}: {resp.text[:300]}")
            resp.raise_for_status()
        data = resp.json()
        self.usage.requests += 1
        self.usage.tokens += int(data.get("usage", {}).get("total_tokens", 0))
        return data

    # -- embeddings --------------------------------------------------------------------------
    def embed(self, texts: list[str], task: str) -> np.ndarray:
        keys = [JinaCache.emb_key(self.embed_model, task, t) for t in texts]
        found = self.cache.get_embeddings(list(dict.fromkeys(keys)))
        missing = [i for i, k in enumerate(keys) if k not in found]
        self.usage.cache_hits += len(texts) - len(missing)
        self.usage.cache_misses += len(missing)
        # de-duplicate identical texts before paying for them
        todo: dict[str, str] = {}
        for i in missing:
            todo.setdefault(keys[i], texts[i])
        items = list(todo.items())
        for b in range(0, len(items), self.batch_size):
            batch = items[b:b + self.batch_size]
            payload = {"model": self.embed_model, "task": task, "dimensions": self.dimensions,
                       "normalized": True, "embedding_type": "float",
                       "input": [t for _, t in batch]}
            data = self._post("/embeddings", payload, sum(tokens.count(t) for _, t in batch))
            rows = sorted(data["data"], key=lambda d: d["index"])
            if len(rows) != len(batch):
                raise JinaError(f"expected {len(batch)} embeddings, got {len(rows)}")
            got = {k: np.asarray(r["embedding"], dtype=np.float32)
                   for (k, _), r in zip(batch, rows, strict=True)}
            self.cache.put_embeddings(self.embed_model, task, got)
            found.update(got)
            log.info("embedded", batch=len(batch), done=b + len(batch), total=len(items),
                     tokens_so_far=self.usage.tokens)
        return np.vstack([found[k] for k in keys]) if keys else np.zeros((0, self.dimensions))

    def embed_query(self, text: str) -> np.ndarray:
        return self.embed([text], task=base_config()["embeddings"]["query_task"])[0]

    # -- rerank ------------------------------------------------------------------------------
    def rerank(self, query: str, docs: list[str], top_n: int | None = None) -> list[dict]:
        if not docs:
            return []
        key = JinaCache.rerank_key(self.rerank_model, query, docs)
        cached = self.cache.get_rerank(key)
        if cached is not None:
            self.usage.cache_hits += 1
            result = cached
        else:
            self.usage.cache_misses += 1
            payload = {"model": self.rerank_model, "query": query, "documents": docs,
                       "top_n": len(docs), "return_documents": False}
            est = tokens.count(query) * len(docs) + sum(tokens.count(d) for d in docs)
            data = self._post("/rerank", payload, est)
            result = [{"index": r["index"], "score": r["relevance_score"]}
                      for r in data["results"]]
            self.cache.put_rerank(key, self.rerank_model, result)
        result = sorted(result, key=lambda r: -r["score"])
        return result[:top_n] if top_n else result

    def ping(self) -> dict:
        """Embed two strings (bypassing the cache) to check the key, model and dimensions."""
        payload = {"model": self.embed_model, "task": "retrieval.query",
                   "dimensions": self.dimensions, "normalized": True,
                   "input": ["agricultural income", "tax deducted at source"]}
        data = self._post("/embeddings", payload, 10)
        dim = len(data["data"][0]["embedding"])
        return {"model": self.embed_model, "dimensions": dim,
                "tokens": data.get("usage", {}).get("total_tokens")}


if __name__ == "__main__":
    print(JinaClient.from_config().ping())
