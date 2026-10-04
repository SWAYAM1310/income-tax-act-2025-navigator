"""Hybrid retrieval for v3: dense + full-text + exact provision ids, fused with RRF.

Three retrievers with complementary failure modes:

- **dense** (`dense.knn`) matches meaning, and is what v0-v2 used. It cannot match a number, so
  it scores ~0.06 recall@5 on amendment questions, which always name their provision.
- **full-text** (`fts`) matches literal tokens, including section numbers. Postgres' `simple`
  configuration keeps stop words and `ts_rank` applies no IDF, so a natural question ANDed
  together matches nothing (verified: 0 rows). We therefore strip stop words and OR the
  informative terms, then rank by cover density.
- **exact ids** (`by_ids`) parses "section 483(1)" out of the question and looks the provision
  up directly. This is the precise fix for amendment retrieval.

Reciprocal rank fusion combines them: a chunk's score is the weighted sum of 1/(c + rank) over
the lists it appears in, so each retriever votes without needing comparable scores.
"""

from __future__ import annotations

import re

import numpy as np
import psycopg

from statnav.retrieve.dense import Hit, knn
from statnav.retrieve.ids import expand

RRF_C = 60  # the usual constant: rank 1 scores 1/61, rank 10 scores 1/70

# `simple` keeps stop words and ts_rank has no IDF, so question words would otherwise dominate
STOPWORDS = frozenset(("a", "an", "and", "any", "are", "as", "at", "be", "been", "by", "can",
    "did", "do", "does", "for", "from", "had", "has", "have", "how", "in", "into", "is", "it",
    "its", "make", "made", "may", "must", "not", "of", "on", "or", "shall", "should", "such",
    "than", "that", "the", "their", "there", "these", "this", "those", "to", "under", "upon",
    "was", "were", "what", "when", "where", "which", "who", "whom", "why", "will", "with",
    "within", "would", "you", "your", "act", "section", "sub", "provision", "provisions",
    "clause", "para", "paragraph"))


def terms(query: str) -> list[str]:
    """Informative lowercase lexemes from `query`, de-duplicated, order preserved.

    Restricted to `[a-z0-9]+` so the result is always a safe `to_tsquery` input.
    """
    out: dict[str, None] = {}
    for tok in re.findall(r"[A-Za-z0-9]+", query.lower()):
        if tok.isdigit() or (len(tok) >= 3 and tok not in STOPWORDS):
            out.setdefault(tok, None)
    return list(out)


def fts(conn: psycopg.Connection, query: str, version: str, k: int = 10) -> list[Hit]:
    """Full-text hits, ranked by cover density over an OR of the query's informative terms."""
    ts = terms(query)
    if not ts:
        return []
    rows = conn.execute(
        "SELECT id, provision_id, ts_rank_cd(tsv, q) AS score, embed_text, tokens, "
        "page_start, page_end, meta "
        "FROM chunks, to_tsquery('simple', array_to_string(%s::text[], ' | ')) AS q "
        "WHERE version = %s AND tsv @@ q ORDER BY score DESC, id LIMIT %s",
        (ts, version, k),
    ).fetchall()
    return [Hit(*r) for r in rows]


_COLS = ("SELECT id, provision_id, 0.0 AS score, embed_text, tokens, page_start, page_end, "
         "meta FROM chunks ")


#: An exact match this small is a heading stub -- "393. [Payments to residents]" with all the
#: content in child chunks. It is poor evidence on its own, and the exact-match boost put it
#: above the table rows that answer the question (table hit@1 0.833 -> 0.000). Stubs are only
#: dropped from the *exact* list; `under_ids` still returns them, so nothing becomes
#: unreachable -- they just stop out-ranking real content.
STUB_TOKENS = 60


def containers(conn: psycopg.Connection, ids: list[str], version: str) -> set[str]:
    """Those `ids` whose content lives in *other*, deeper chunks.

    Section 393 is a container: its own chunk is a heading and the rates are in
    `s393:tbl1#...` chunks. Section 483 is not: `v2:s483` holds `s483(1)` itself. The
    distinction is structural, so it separates "the question names the answer" (amendment)
    from "the question names where to look" (table) without needing to know the question type.
    """
    if not ids:
        return set()
    rows = conn.execute(
        "SELECT ref, EXISTS (SELECT 1 FROM chunks c,"
        "   jsonb_array_elements_text(c.meta->'provisions') p"
        "   WHERE c.version = %s AND (p LIKE ref || '(%%' OR p LIKE ref || ':%%')"
        "     AND NOT (c.meta->'provisions' ? ref))"
        " FROM unnest(%s::text[]) AS ref",
        (version, ids),
    ).fetchall()
    return {ref for ref, is_container in rows if is_container}


def by_ids(conn: psycopg.Connection, ids: list[str], version: str, k: int = 10, *,
           stub_tokens: int = STUB_TOKENS, drop_containers: bool = True) -> list[Hit]:
    """Chunks whose provisions contain one of `ids` exactly, most specific reference first.

    This is what an amendment question needs: "How was section 483(1) amended" wants the
    provision it names, not something inside it. Two kinds of match are skipped, because both
    out-ranked the content that actually answers the question: heading stubs (`STUB_TOKENS`)
    and containers whose content sits in deeper chunks (`drop_containers`). Neither becomes
    unreachable -- `under_ids` still returns them; they just lose the exact-match boost.
    """
    if not ids:
        return []
    rows = conn.execute(
        _COLS + "WHERE version = %s AND meta->'provisions' ?| %s", (version, ids)
    ).fetchall()
    rank = {pid: n for n, pid in enumerate(ids)}
    skip = containers(conn, ids, version) if drop_containers else set()
    hits = [h for h in (Hit(*r) for r in rows)
            if h.tokens >= stub_tokens
            # keep it if it matches any reference that is not merely a container
            and any(p in rank and p not in skip for p in (h.meta.get("provisions") or []))]

    def best(h: Hit) -> tuple[int, int]:
        covered = [rank[p] for p in (h.meta.get("provisions") or []) if p in rank]
        # tie-break by chunk size so the tightest chunk covering the reference wins
        return (min(covered) if covered else len(ids), h.tokens)

    return sorted(hits, key=best)[:k]


def under_ids(conn: psycopg.Connection, ids: list[str], version: str, qvec: np.ndarray,
              k: int = 10) -> list[Hit]:
    """Chunks *under* any of `ids` (descendants included), ordered by dense similarity.

    This is what a table question needs. Naming "section 393" has to reach `s393:tbl1#3(i)`,
    because the section's own chunk is a 36-token heading stub with all the content in its
    table rows; boosting the exact match alone put that stub at rank 1 and drove table hit@1
    to 0.000. Here the ids give the candidate *set* (precision) and the embedding gives the
    *order* (relevance), so the best-matching row surfaces.
    """
    if not ids:
        return []
    rows = conn.execute(
        _COLS + "WHERE version = %s AND EXISTS ("
        "  SELECT 1 FROM jsonb_array_elements_text(meta->'provisions') p,"
        "       unnest(%s::text[]) AS ref"
        # a descendant is the reference followed by a bracket or a path separator, so `s39`
        # cannot match `s393`
        "  WHERE p = ref OR p LIKE ref || '(%%' OR p LIKE ref || ':%%'"
        ") ORDER BY embedding <=> %s LIMIT %s",
        (version, ids, qvec, k),
    ).fetchall()
    return [Hit(*r) for r in rows]


def rrf(lists: list[tuple[list[Hit], float]], k: int = 10, c: int = RRF_C) -> list[Hit]:
    """Reciprocal rank fusion of weighted ranked lists, highest fused score first."""
    scores: dict[str, float] = {}
    best: dict[str, Hit] = {}
    for hits, weight in lists:
        for rank, h in enumerate(hits, 1):
            scores[h.chunk_id] = scores.get(h.chunk_id, 0.0) + weight / (c + rank)
            best.setdefault(h.chunk_id, h)
    order = sorted(scores, key=lambda cid: (-scores[cid], cid))
    out = []
    for cid in order[:k]:
        h = best[cid]
        out.append(Hit(h.chunk_id, h.provision_id, round(scores[cid], 6), h.text, h.tokens,
                       h.page_start, h.page_end, h.meta))
    return out


#: v3 enables dense + ids. FTS is implemented and tested but off by default: measured on the
#: 124 answerable dev questions it lowers overall recall@5 (0.871 vs 0.887 without it) because
#: it costs lookup (0.800 vs 0.914), even when restricted to rare terms. It does lift multi-hop
#: (0.719 vs 0.656), so it is kept for the cross-reference work in v4.
DEFAULT_RETRIEVERS = ("dense", "ids", "under")


def search(conn: psycopg.Connection, qvec: np.ndarray, query: str, version: str,
           k: int = 10, *, pool: int = 30, retrievers: tuple[str, ...] | list[str] = (),
           weights: dict | None = None) -> list[Hit]:
    """Fuse the enabled retrievers with RRF.

    `pool` is how deep each retriever goes before fusion; `k` is how many survive it. The ids
    weight is insensitive in practice (1.0 to 5.0 all scored 0.887 on dev): exact id hits are
    few and land high regardless.
    """
    w = {"dense": 1.0, "fts": 1.0, "ids": 1.0, "under": 1.0, **(weights or {})}
    want = tuple(retrievers) or DEFAULT_RETRIEVERS
    sources = {
        "dense": lambda: knn(conn, qvec, version, pool),
        "fts": lambda: fts(conn, query, version, pool),
        "ids": lambda: by_ids(conn, expand(query), version, pool),
        "under": lambda: under_ids(conn, expand(query), version, qvec, pool),
    }
    unknown = set(want) - set(sources)
    if unknown:
        raise ValueError(f"unknown retrievers: {sorted(unknown)}")
    return rrf([(sources[name](), w[name]) for name in want], k=k)
