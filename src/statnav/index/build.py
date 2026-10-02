"""Chunk the Act for one ladder version, embed with Jina, and store the vectors in pgvector.

    python -m statnav.index.build --version v2 --dry-run   # token estimate only, no API calls
    python -m statnav.index.build --version v2             # embed (cached) and load
    python -m statnav.index.build --version all --yes      # all versions, skip the >1M prompt

Only texts missing from the Jina cache are sent, so rebuilding is free once embedded.
"""

from __future__ import annotations

import argparse
import json
import sys

from psycopg.types.json import Jsonb

from statnav.config import base_config
from statnav.embed import tokens
from statnav.embed.cache import JinaCache
from statnav.embed.jina import JinaClient
from statnav.index.chunkers import Chunk, build_chunks
from statnav.index.db import apply_schema, connect
from statnav.ingest.build import latest, load_jsonl
from statnav.obs.logging import get_logger

log = get_logger("index.build")
VERSIONS = ["v0", "v1", "v2"]


def load_artefacts() -> dict:
    d = latest()
    files = {"pages_raw": "pages_raw.jsonl", "pages_clean": "pages_clean.jsonl",
             "provisions": "provisions.jsonl", "rows": "table_rows.jsonl",
             "tables": "tables.jsonl"}
    return {k: load_jsonl(d / f) for k, f in files.items()}


def estimate(chunks: list[Chunk], cache: JinaCache, model: str, task: str) -> dict:
    keys = [JinaCache.emb_key(model, task, c.embed_text) for c in chunks]
    cached = cache.get_embeddings(list(dict.fromkeys(keys)))
    todo = {k: c.embed_text for k, c in zip(keys, chunks, strict=True) if k not in cached}
    return {"chunks": len(chunks), "cached": len(chunks) - len(todo),
            "to_embed": len(todo), "est_tokens": sum(tokens.count(t) for t in todo.values())}


def store(version: str, chunks: list[Chunk], vectors, model: str) -> int:
    with connect() as conn:
        apply_schema(conn)
        conn.execute("DELETE FROM chunks WHERE version = %s", (version,))
        with conn.cursor() as cur, cur.copy(
                "COPY chunks (id, version, provision_id, text, embed_text, tokens, page_start, "
                "page_end, meta, model, embedding) FROM STDIN") as cp:
            for c, v in zip(chunks, vectors, strict=True):
                cp.write_row((c.id, c.version, c.provision_id, c.text, c.embed_text, c.tokens,
                              c.page_start, c.page_end, Jsonb(c.meta), model, v))
        # one HNSW index per version keeps filtered k-NN exact-ish and fast
        conn.execute(f"CREATE INDEX IF NOT EXISTS chunks_hnsw_{version} ON chunks USING hnsw "
                     f"(embedding vector_cosine_ops) WHERE version = '{version}'")
        conn.commit()
    return len(chunks)


def build(version: str, dry_run: bool, yes: bool) -> dict:
    cfg = base_config()
    model, task = cfg["embeddings"]["model"], cfg["embeddings"]["passage_task"]
    chunks = build_chunks(version, load_artefacts())
    cache = JinaCache.default()
    est = estimate(chunks, cache, model, task)
    log.info("estimate", version=version, model=model, **est)
    if dry_run:
        return est
    limit = cfg["jina"]["confirm_above_tokens"]
    if est["est_tokens"] > limit and not yes:
        sys.exit(f"{version}: ~{est['est_tokens']:,} Jina tokens to embed (> {limit:,}). "
                 "Re-run with --yes to confirm.")
    client = JinaClient.from_config()
    vectors = client.embed([c.embed_text for c in chunks], task=task)
    n = store(version, chunks, vectors, model)
    out = {**est, "stored": n, "jina_tokens_billed": client.usage.tokens,
           "jina_requests": client.usage.requests}
    log.info("indexed", version=version, **out)
    return out


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--version", default="v2", choices=VERSIONS + ["all"])
    ap.add_argument("--dry-run", action="store_true", help="estimate tokens, call nothing")
    ap.add_argument("--yes", action="store_true", help="skip the large-run confirmation")
    a = ap.parse_args()
    results = {v: build(v, a.dry_run, a.yes) for v in (VERSIONS if a.version == "all"
                                                         else [a.version])}
    print(json.dumps(results, indent=2))
