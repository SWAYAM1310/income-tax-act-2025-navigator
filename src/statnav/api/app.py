"""HTTP API over the navigator.

    python -m statnav.api                 # uvicorn on http://127.0.0.1:8000 (docs at /docs)

- `POST /query` streams one answer as server-sent events: a `step` event per agent node
  (classify, retrieve, definitions, pack, generate, verify); `evidence` as soon as the passages
  are packed; `token` events with the answer text as the model writes it (`attempt` goes up when
  a v7 retry rewrites the answer); then `evidence` again, `answer` and `done` (or `error`).
  Non-agent versions send only `evidence`, `answer` and `done`. Streamed answers come from a
  chat-only call without JSON mode (Groq cannot stream it), so they can differ slightly from
  the answers the eval ladder measures; `answer` is the final word.
- `GET /provisions/{id}`, `GET /tables/{table_id}/rows`, `GET /amendments/{id}` serve the Act
  itself from Postgres (`statnav.repo`), so the frontend can show what a citation points at.
- `GET /evals?split=dev_mini` returns each ladder version's committed metrics.

Answers go through `statnav.answer` / `statnav.agent`, exactly the path the eval ladder
measures. One process serves one user at a time: a lock serialises answering, because the
database connection and the Groq clients (per-minute token windows) are not shared safely.
"""

from __future__ import annotations

import json
import os
import threading
import time
from collections import deque
from collections.abc import Callable, Iterator
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from statnav import repo
from statnav.answer import Answer, Answerer, failed, from_agent, inline_cites
from statnav.config import CONFIG_DIR, ROOT

DEFAULT_VERSION = "v9"
#: versions a user can ask (the oracle needs gold provisions)
VERSIONS = sorted(p.stem for p in (CONFIG_DIR / "versions").glob("v*.yaml"))
RESULTS = ROOT / "results"


class QueryIn(BaseModel):
    question: str = Field(min_length=3, max_length=1000)
    version: str = DEFAULT_VERSION
    k: int | None = Field(default=None, ge=1, le=20)


class Services:
    """Long-lived answerers (one per version, created on first use) and a repo connection."""

    def __init__(self, answerer: Callable[[str], Answerer] = Answerer.for_version,
                 connect: Callable | None = None) -> None:
        self._make_answerer = answerer
        self._connect = connect
        self._bots: dict[str, Answerer] = {}
        self._conn = None
        self.lock = threading.Lock()

    def bot(self, version: str) -> Answerer:
        if version not in self._bots:
            self._bots[version] = self._make_answerer(version)
        return self._bots[version]

    @property
    def conn(self):  # noqa: ANN201 - a psycopg connection
        if self._conn is None:
            if self._connect is None:
                from statnav.index.db import connect
                self._connect = lambda: connect(autocommit=True)
            self._conn = self._connect()
        return self._conn


class RateLimit:
    """At most `limit` questions per client in any `window` seconds (0 = unlimited).

    In memory, so it resets when the process restarts; that is enough to stop one visitor
    from spending the whole shared Groq quota on a public deployment.
    """

    def __init__(self, limit: int, window: float = 3600.0,
                 clock: Callable[[], float] = time.monotonic) -> None:
        self.limit, self.window, self._clock = limit, window, clock
        self._seen: dict[str, deque[float]] = {}
        self._lock = threading.Lock()

    def retry_after(self, client: str) -> int:
        """0 and the question counted if `client` may ask now, else seconds until it may."""
        if self.limit <= 0:
            return 0
        now = self._clock()
        with self._lock:
            q = self._seen.setdefault(client, deque())
            while q and q[0] <= now - self.window:
                q.popleft()
            if len(q) >= self.limit:
                return max(1, int(q[0] + self.window - now) + 1)
            q.append(now)
            return 0


def client_ip(request: Request) -> str:
    """The visitor's address: behind a proxy (Railway) it is the first X-Forwarded-For hop."""
    fwd = request.headers.get("x-forwarded-for", "")
    if fwd.strip():
        return fwd.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def _env_origins() -> list[str]:
    return [o.strip().rstrip("/") for o in os.environ.get("STATNAV_CORS_ORIGINS", "").split(",")
            if o.strip()]


def _sse(event: str, data: object) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


def _passage(h: dict, n: int) -> dict:
    return {"label": f"C{n}", "chunk_id": h["chunk_id"], "provisions": h.get("provisions", []),
            "page_start": h.get("page_start"), "page_end": h.get("page_end"),
            "tokens": h.get("tokens"), "text": h.get("text", "")}


def answer_payload(res: Answer, version: str) -> dict:
    """The JSON shape of an answer, shared by the API and the MCP server."""
    return {
        "question": res.question, "version": version, "answer": res.answer,
        "refused": res.refused, "error": res.error, "route": res.route,
        "verified": res.verified, "unsupported": res.unsupported, "follow_ups": res.follow_ups,
        "citations": [{"chunk_id": h["chunk_id"], "provisions": h.get("provisions", []),
                       "page_start": h.get("page_start"), "page_end": h.get("page_end")}
                      for h in res.cited],
        "evidence_tokens": res.evidence_tokens, "llm_tokens": res.llm_tokens,
        "classify_tokens": res.classify_tokens, "cached": res.cached,
        "latency_s": res.latency_s,
    }


def _step(node: str, s: dict) -> dict:
    """What a frontend needs to show progress after one agent node."""
    out: dict = {"node": node}
    if node == "classify":
        out.update(route=s.get("route"), in_scope=s.get("in_scope"),
                   reason=s.get("scope_reason") or None, terms=s.get("terms") or [])
    elif node == "retrieve":
        out["passages"] = len(s.get("hits") or [])
    elif node == "tools":
        out.update(passages=len(s.get("hits") or []), definitions=s.get("definitions") or [])
    elif node == "pack":
        ev = s.get("evidence") or []
        out.update(passages=len(ev), tokens=sum(h["tokens"] for h in ev))
    elif node == "verify":
        out.update(verified=s.get("verified"), unsupported=s.get("unsupported") or [])
    return out


def stream_answer(services: Services, q: QueryIn) -> Iterator[str]:
    from statnav.llm.client import LLMError, QuotaExhausted

    with services.lock:
        try:
            bot = services.bot(q.version)
            if bot.agent is not None:
                state: dict = {}
                for node, upd in bot.agent.stream(q.question, q.k, tokens=True):
                    if node == "token":
                        yield _sse("token", upd)
                        continue
                    state = upd
                    yield _sse("step", _step(node, state))
                    if node == "pack":
                        yield _sse("evidence", [_passage(h, n)
                                                for n, h in enumerate(state["evidence"], 1)])
                res = from_agent(bot.agent.result(q.question, state), inline_cites(bot.cfg))
            else:
                res = bot.ask(q.question, q.k)
        except (QuotaExhausted, LLMError) as exc:
            res = failed(q.question, exc)
        except Exception as exc:  # noqa: BLE001 - surface any failure as an event, not a 500
            yield _sse("error", {"message": f"{type(exc).__name__}: {exc}"})
            yield _sse("done", {})
            return
    yield _sse("evidence", [_passage(h, n) for n, h in enumerate(res.evidence, 1)])
    if res.error:
        yield _sse("error", {"message": res.error})
    yield _sse("answer", answer_payload(res, q.version))
    yield _sse("done", {})


def eval_summary(split: str, results: Path = RESULTS) -> dict:
    """Each version's metrics for `split`, as committed under results/<version>/<split>/."""
    keys = ("recall@5", "mrr", "hit@1", "fact_recall", "citation_precision", "citation_recall",
            "grounded_numbers", "table_exact", "amendment_type", "refusal_precision",
            "refusal_recall", "scope_precision", "scope_recall", "evidence_tokens_mean",
            "llm_tokens_mean")
    rows = []
    for d in sorted(results.glob(f"*/{split}")):
        try:
            m = json.loads((d / "metrics.json").read_text(encoding="utf-8"))
            meta = json.loads((d / "run_meta.json").read_text(encoding="utf-8"))
        except FileNotFoundError:
            continue
        rows.append({"version": d.parent.name,
                     "description": (meta.get("config") or {}).get("description"),
                     "retrieval_only": meta.get("retrieval_only"),
                     "n": meta.get("n_questions"), "n_completed": meta.get("n_completed"),
                     "complete": (meta.get("n_completed") == meta.get("n_questions")
                                  and not meta.get("incomplete")),
                     "metrics": {k: m.get(k) for k in keys if m.get(k) is not None},
                     "by_type": {t: {k: v for k, v in d_.items() if k in keys or k == "n"}
                                 for t, d_ in (m.get("by_type") or {}).items()}})
    order = {v: n for n, v in enumerate([*VERSIONS, "oracle"])}
    rows.sort(key=lambda r: order.get(r["version"], 99))
    return {"split": split, "versions": rows}


def create_app(services: Services | None = None, rate_limit: int | None = None) -> FastAPI:
    """`rate_limit`: questions per client per hour; None reads STATNAV_RATE_LIMIT (unset = off).

    STATNAV_CORS_ORIGINS (comma-separated) adds origins allowed to call the API, e.g. the
    deployed frontend.
    """
    svc = services or Services()
    if rate_limit is None:
        rate_limit = int(os.environ.get("STATNAV_RATE_LIMIT") or 0)
    limiter = RateLimit(rate_limit)
    app = FastAPI(title="Income-tax Act, 2025 navigator",
                  description="Cited answers about India's Income-tax Act, 2025 (as amended by "
                              "the Finance Act, 2026). Not tax advice.")
    app.state.services = svc
    # the Vite dev server (Phase 10) runs on its own port; a deployed frontend comes from env
    app.add_middleware(CORSMiddleware, allow_origins=["http://localhost:5173",
                                                      "http://127.0.0.1:5173", *_env_origins()],
                       allow_methods=["GET", "POST"], allow_headers=["*"])

    @app.get("/health")
    def health() -> dict:
        return {"status": "ok", "default_version": DEFAULT_VERSION, "versions": VERSIONS}

    @app.post("/query")
    def query(q: QueryIn, request: Request) -> StreamingResponse:
        if q.version not in VERSIONS:
            raise HTTPException(422, f"version must be one of {VERSIONS}")
        wait = limiter.retry_after(client_ip(request))
        if wait:
            minutes = max(1, round(wait / 60))
            raise HTTPException(429, f"Question limit reached ({limiter.limit} an hour). "
                                     f"Try again in about {minutes} min.",
                                headers={"Retry-After": str(wait)})
        return StreamingResponse(stream_answer(svc, q), media_type="text/event-stream",
                                 headers={"Cache-Control": "no-cache"})

    @app.get("/provisions/{pid}")
    def get_provision(pid: str) -> dict:
        with svc.lock:
            p = repo.provision(svc.conn, pid)
        if p is None:
            raise HTTPException(404, f"no provision {pid!r}")
        return p

    @app.get("/tables/{table_id}/rows")
    def get_rows(table_id: str, sl_no: str | None = None) -> list[dict]:
        with svc.lock:
            rows = repo.table_rows(svc.conn, table_id, sl_no)
        if not rows:
            raise HTTPException(404, f"no rows for {table_id!r}" + (f" Sl. No. {sl_no}"
                                                                     if sl_no else ""))
        return rows

    @app.get("/amendments/{pid}")
    def get_amendments(pid: str, descendants: bool = True) -> list[dict]:
        with svc.lock:
            return repo.amendments(svc.conn, pid, descendants)

    @app.get("/evals")
    def evals(split: str = Query("dev_mini", pattern=r"^[a-z_]+$")) -> dict:
        return eval_summary(split)

    return app

