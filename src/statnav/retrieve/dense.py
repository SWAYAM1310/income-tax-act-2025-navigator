"""Dense retrieval over pgvector: embed the question with Jina, cosine k-NN within one version."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import psycopg
from psycopg import sql

from statnav.embed.jina import JinaClient

VERSIONS = {"v0", "v1", "v2"}


@dataclass
class Hit:
    chunk_id: str
    provision_id: str | None
    score: float
    text: str
    tokens: int
    page_start: int
    page_end: int
    meta: dict


def knn(conn: psycopg.Connection, qvec: np.ndarray, version: str, k: int = 10) -> list[Hit]:
    if version not in VERSIONS:
        raise ValueError(f"unknown version {version}")
    conn.execute("SET hnsw.ef_search = 100")
    # the version is a literal (not a bound parameter) so the planner can use that version's
    # partial HNSW index
    # embed_text = text plus the v2 breadcrumb (section heading, chapter): the generator needs
    # that context too, and `tokens` already counts it
    q = sql.SQL(
        "SELECT id, provision_id, 1 - (embedding <=> %s) AS score, embed_text, tokens, "
        "page_start, page_end, meta FROM chunks WHERE version = {v} "
        "ORDER BY embedding <=> %s LIMIT %s"
    ).format(v=sql.Literal(version))
    rows = conn.execute(q, (qvec, qvec, k)).fetchall()
    return [Hit(*r) for r in rows]


def search(conn: psycopg.Connection, client: JinaClient, query: str, version: str,
           k: int = 10) -> list[Hit]:
    return knn(conn, client.embed_query(query), version, k)
