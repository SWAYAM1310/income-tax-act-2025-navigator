"""One dispatch point from a version config to a retriever.

Both the eval harness and the chat go through `retrieve()`, so a version behaves the same
wherever it runs and the ladder cannot drift from what the chatbot shows.
"""

from __future__ import annotations

import psycopg

from statnav.embed.jina import JinaClient
from statnav.retrieve.amend import attach, style_of
from statnav.retrieve.dense import Hit, knn
from statnav.retrieve.hybrid import search as hybrid_search


def retrieve(conn: psycopg.Connection, jina: JinaClient, question: str, cfg: dict,
             k: int | None = None) -> list[Hit]:
    """Top hits for `question` under the retrieval section of a version config."""
    r = cfg["retrieval"]
    mode = r["mode"]
    version = cfg["chunks"]
    top = k or r["k"]
    if mode == "dense":
        hits = knn(conn, jina.embed_query(question), version, top)
    elif mode == "hybrid":
        hits = hybrid_search(
            conn, jina.embed_query(question), question, version, top,
            pool=r.get("pool", 30),
            retrievers=r.get("retrievers", ()),
            weights=r.get("weights"),
            xref=r.get("xref"),
        )
    else:
        raise ValueError(f"retrieval mode {mode!r} has no chat/eval path")
    # what changed lives in the Act's endnotes, not in the provision text
    # `endnotes: structured` (v6) states the change type in words; `explicit` (v8) also the
    # wording before and after
    style = style_of(r)
    if style:
        hits = attach(conn, hits, style)
    return hits


def as_dicts(hits: list[Hit]) -> list[dict]:
    """The plain-dict shape the generator and the eval records use."""
    return [{"chunk_id": h.chunk_id, "text": h.text, "tokens": h.tokens,
             "provisions": h.meta.get("provisions", []), "page_start": h.page_start,
             "page_end": h.page_end, "score": round(h.score, 4)} for h in hits]
