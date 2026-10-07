"""Chat client for OpenAI-compatible providers (Groq by default), built for free-tier quotas.

    llm = ChatClient.for_role("answer")
    reply = llm.chat([{"role": "system", ...}, {"role": "user", ...}], json_mode=True)
    reply.text, reply.usage, reply.cached, reply.latency_s
    reply = llm.chat_stream(messages, on_delta=print)   # the chat UI: text as it is generated

- Responses are cached in .cache/llm.sqlite by a hash of the full request, so re-running an eval
  with unchanged prompts costs nothing and is deterministic.
- A sliding-window limiter keeps under requests/min and tokens/min; a daily ledger refuses to
  start a call that would exceed the provider's tokens/day (raises QuotaExhausted instead).
- `chat_stream` is for the chat UI only. Groq cannot stream in JSON mode, so it sends the same
  request without `response_format`; that request hashes differently, so streamed replies are
  cached apart from the ones the eval ladder measures.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
import time
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from functools import lru_cache
from pathlib import Path

import httpx
from tenacity import retry, retry_if_exception, stop_after_attempt, wait_exponential

from statnav.config import CONFIG_DIR, ROOT, base_config, load_yaml
from statnav.embed import tokens
from statnav.obs.logging import get_logger

log = get_logger("llm")


class QuotaExhausted(RuntimeError):
    pass


class LLMError(RuntimeError):
    pass


@lru_cache(maxsize=1)
def models_config() -> dict:
    base_config()  # loads .env
    return load_yaml(CONFIG_DIR / "models.yaml")


@dataclass
class Reply:
    text: str
    usage: dict
    model: str
    cached: bool
    latency_s: float

    def json(self) -> dict:
        t = self.text.strip()
        if t.startswith("```"):
            t = t.strip("`").removeprefix("json").strip()
        start, end = t.find("{"), t.rfind("}")
        if start < 0 or end < 0:
            raise LLMError(f"no JSON object in reply: {self.text[:200]!r}")
        return json.loads(t[start:end + 1])


class _Store:
    """Response cache and daily token ledger in one sqlite file."""

    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(path, check_same_thread=False)
        self.conn.executescript("""
            CREATE TABLE IF NOT EXISTS responses (key TEXT PRIMARY KEY, model TEXT,
                request TEXT, response TEXT, created TEXT);
            CREATE TABLE IF NOT EXISTS ledger (day TEXT, model TEXT, tokens INTEGER,
                PRIMARY KEY (day, model));
        """)

    def get(self, key: str) -> dict | None:
        row = self.conn.execute("SELECT response FROM responses WHERE key = ?", (key,)).fetchone()
        return json.loads(row[0]) if row else None

    def put(self, key: str, model: str, request: dict, response: dict) -> None:
        with self.conn:
            self.conn.execute("INSERT OR REPLACE INTO responses VALUES (?, ?, ?, ?, ?)",
                              (key, model, json.dumps(request), json.dumps(response),
                               datetime.now(UTC).isoformat()))

    def spent_today(self, model: str) -> int:
        row = self.conn.execute("SELECT tokens FROM ledger WHERE day = ? AND model = ?",
                                (_today(), model)).fetchone()
        return row[0] if row else 0

    def add(self, model: str, n: int) -> None:
        with self.conn:
            self.conn.execute(
                "INSERT INTO ledger VALUES (?, ?, ?) ON CONFLICT (day, model) "
                "DO UPDATE SET tokens = tokens + excluded.tokens", (_today(), model, n))


def _today() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%d")


def _retryable(exc: BaseException) -> bool:
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code == 429 or exc.response.status_code >= 500
    return isinstance(exc, httpx.TransportError)


@dataclass
class _Window:
    rpm: int
    tpm: int
    events: deque = field(default_factory=deque)

    def wait(self, n: int) -> None:
        while True:
            now = time.monotonic()
            while self.events and now - self.events[0][0] > 60:
                self.events.popleft()
            if len(self.events) < self.rpm and sum(t for _, t in self.events) + n <= self.tpm:
                self.events.append((now, n))
                return
            time.sleep(max(1.0, 61 - (now - self.events[0][0])))


_windows: dict[str, _Window] = {}


class ChatClient:
    def __init__(self, role: str, transport: httpx.BaseTransport | None = None,
                 store_path: Path | None = None):
        cfg = models_config()
        r = cfg["roles"][role]
        p = cfg["providers"][r["provider"]]
        self.role, self.model = role, r["model"]
        self.max_tokens = r["max_tokens"]
        self.reasoning_effort = r.get("reasoning_effort")
        self.tokens_per_day = p["tokens_per_day"]
        key = os.environ.get(p["api_key_env"], "")
        if not key and transport is None:
            raise LLMError(f"{p['api_key_env']} is not set (add it to .env)")
        self.http = httpx.Client(base_url=p["base_url"], timeout=p["timeout_seconds"],
                                 transport=transport,
                                 headers={"Authorization": f"Bearer {key}"})
        self.window = _windows.setdefault(self.model, _Window(p["requests_per_minute"],
                                                              p["tokens_per_minute"]))
        self.store = _Store(store_path or ROOT / base_config()["paths"]["cache_dir"]
                            / "llm.sqlite")

    @classmethod
    def for_role(cls, role: str) -> ChatClient:
        return cls(role)

    def spent_today(self) -> int:
        return self.store.spent_today(self.model)

    @retry(retry=retry_if_exception(_retryable), stop=stop_after_attempt(6),
           wait=wait_exponential(multiplier=4, min=5, max=90), reraise=True)
    def _post(self, payload: dict, est: int) -> dict:
        self.window.wait(est)
        t0 = time.perf_counter()
        resp = self.http.post("/chat/completions", json=payload)
        self._http_s = time.perf_counter() - t0  # provider latency, excluding our throttling
        if resp.status_code == 429:
            wait = float(resp.headers.get("retry-after", "0") or 0)
            if wait > 120:  # the daily limit, not a per-minute one
                raise QuotaExhausted(f"{self.model}: provider says retry after {wait:.0f}s")
            time.sleep(min(wait, 60))
        if resp.status_code >= 400 and resp.status_code != 429 and resp.status_code < 500:
            raise LLMError(f"{self.model} {resp.status_code}: {resp.text[:300]}")
        resp.raise_for_status()
        return resp.json()

    def _payload(self, messages: list[dict], max_tokens: int | None) -> dict:
        payload = {"model": self.model, "messages": messages, "temperature": 0,
                   "max_completion_tokens": max_tokens or self.max_tokens}
        if self.reasoning_effort:
            payload["reasoning_effort"] = self.reasoning_effort
        return payload

    def _budget(self, messages: list[dict], payload: dict) -> int:
        """The call's token estimate, after checking it fits today's allowance."""
        est = sum(tokens.count(m["content"]) for m in messages) + payload[
            "max_completion_tokens"]
        if self.spent_today() + est > self.tokens_per_day:
            raise QuotaExhausted(f"{self.model}: {self.spent_today():,} tokens used today; "
                                 f"this call (~{est:,}) would pass {self.tokens_per_day:,}")
        return est

    def chat(self, messages: list[dict], json_mode: bool = False,
             max_tokens: int | None = None) -> Reply:
        payload = self._payload(messages, max_tokens)
        if json_mode:
            payload["response_format"] = {"type": "json_object"}
        key = _key(payload)
        hit = self.store.get(key)
        if hit is not None:
            return Reply(hit["text"], hit["usage"], self.model, True, 0.0)
        est = self._budget(messages, payload)
        data = self._post(payload, est)
        latency = self._http_s
        choice = data["choices"][0]
        text = choice["message"].get("content") or ""
        usage = data.get("usage", {})
        self.store.add(self.model, int(usage.get("total_tokens", est)))
        if choice.get("finish_reason") == "length" and not text:
            raise LLMError(f"{self.model}: ran out of tokens before answering")
        self.store.put(key, self.model, payload, {"text": text, "usage": usage})
        log.info("llm_call", role=self.role, model=self.model, latency_s=round(latency, 2),
                 **{k: usage.get(k) for k in ("prompt_tokens", "completion_tokens")})
        return Reply(text, usage, self.model, False, latency)

    def chat_stream(self, messages: list[dict], on_delta: Callable[[str], None],
                    max_tokens: int | None = None, replay_pause: float = 0.01) -> Reply:
        """Like `chat`, but calls `on_delta` with each piece of text as the model writes it.

        No JSON mode (Groq cannot stream it), so prompts must ask for JSON themselves. A cached
        reply is replayed in word-sized pieces, `replay_pause` seconds apart (about 1.5 s at
        most), so the reader still sees it arrive.
        """
        payload = {**self._payload(messages, max_tokens), "stream": True}
        key = _key(payload)
        hit = self.store.get(key)
        if hit is not None:
            pieces = re.findall(r"\S*\s*", hit["text"])
            pause = min(replay_pause, 1.5 / max(len(pieces), 1))
            for piece in pieces:
                if piece:
                    on_delta(piece)
                    time.sleep(pause)
            return Reply(hit["text"], hit["usage"], self.model, True, 0.0)
        est = self._budget(messages, payload)
        text, usage, finish, latency = self._stream(payload, est, on_delta)
        self.store.add(self.model, int(usage.get("total_tokens", est)))
        if finish == "length" and not text:
            raise LLMError(f"{self.model}: ran out of tokens before answering")
        self.store.put(key, self.model, payload, {"text": text, "usage": usage})
        log.info("llm_stream", role=self.role, model=self.model, latency_s=round(latency, 2),
                 **{k: usage.get(k) for k in ("prompt_tokens", "completion_tokens")})
        return Reply(text, usage, self.model, False, latency)

    @retry(retry=retry_if_exception(_retryable), stop=stop_after_attempt(6),
           wait=wait_exponential(multiplier=4, min=5, max=90), reraise=True)
    def _open(self, payload: dict, est: int) -> httpx.Response:
        """Start a streamed request; retried like `_post` until the response begins."""
        self.window.wait(est)
        resp = self.http.send(self.http.build_request("POST", "/chat/completions", json=payload),
                              stream=True)
        if resp.status_code < 400:
            return resp
        resp.read()
        resp.close()
        if resp.status_code == 429:
            wait = float(resp.headers.get("retry-after", "0") or 0)
            if wait > 120:  # the daily limit, not a per-minute one
                raise QuotaExhausted(f"{self.model}: provider says retry after {wait:.0f}s")
            time.sleep(min(wait, 60))
        if resp.status_code < 500 and resp.status_code != 429:
            raise LLMError(f"{self.model} {resp.status_code}: {resp.text[:300]}")
        resp.raise_for_status()
        raise AssertionError("unreachable")

    def _stream(self, payload: dict, est: int,
                on_delta: Callable[[str], None]) -> tuple[str, dict, str | None, float]:
        t0 = time.perf_counter()
        resp = self._open(payload, est)
        parts: list[str] = []
        usage: dict = {}
        finish = None
        try:
            for line in resp.iter_lines():
                if not line.startswith("data:"):
                    continue
                data = line[5:].strip()
                if data == "[DONE]":
                    break
                chunk = json.loads(data)
                usage = (chunk.get("x_groq") or {}).get("usage") or chunk.get("usage") or usage
                for choice in chunk.get("choices") or []:
                    finish = choice.get("finish_reason") or finish
                    piece = (choice.get("delta") or {}).get("content")
                    if piece:  # gpt-oss also streams `reasoning`, which is not the answer
                        parts.append(piece)
                        on_delta(piece)
        except httpx.HTTPError as exc:
            raise LLMError(f"{self.model}: the stream broke off: {exc}") from exc
        finally:
            resp.close()
        return "".join(parts), usage, finish, time.perf_counter() - t0


def _key(payload: dict) -> str:
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()
