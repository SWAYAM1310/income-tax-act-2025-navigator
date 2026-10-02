"""Load the structured ingestion artefacts into Postgres (no API calls).

    python -m statnav.index.load

Replaces provisions, tables, table_rows, amendments, amendment_links and cross_refs with the
contents of the cached artefacts. Chunks are written separately by statnav.index.build.
"""

from __future__ import annotations

import json

from psycopg.types.json import Jsonb

from statnav.index.db import apply_schema, connect
from statnav.ingest.build import latest, load_jsonl
from statnav.obs.logging import get_logger

log = get_logger("index.load")

STRUCTURED = ["amendment_links", "amendments", "cross_refs", "table_rows", "tables", "provisions"]


def _copy(conn, table: str, columns: list[str], rows) -> int:
    n = 0
    with conn.cursor() as cur, cur.copy(
            f"COPY {table} ({', '.join(columns)}) FROM STDIN") as cp:
        for row in rows:
            cp.write_row(row)
            n += 1
    return n


def load() -> dict[str, int]:
    d = latest()
    prov = load_jsonl(d / "provisions.jsonl")
    tables = load_jsonl(d / "tables.jsonl")
    rows = load_jsonl(d / "table_rows.jsonl")
    amend = load_jsonl(d / "amendments.jsonl")
    xrefs = load_jsonl(d / "xrefs.jsonl")

    counts: dict[str, int] = {}
    with connect() as conn:
        apply_schema(conn)
        conn.execute(f"TRUNCATE {', '.join(STRUCTURED)}")
        counts["provisions"] = _copy(conn, "provisions", [
            "id", "kind", "number", "label", "heading", "text", "parent_id", "chapter", "part",
            "schedule", "page_start", "page_end", "is_amended", "ord"], (
            (p["id"], p["kind"], p["number"], p["label"], p["heading"], p["text"], p["parent"],
             p["chapter"], p["part"], p["schedule"], p["page_start"], p["page_end"],
             p["is_amended"], k) for k, p in enumerate(prov)))
        counts["tables"] = _copy(conn, "tables", [
            "table_id", "title", "headers", "notes", "page_start", "page_end"], (
            (t["table_id"], t["title"] or None, Jsonb(t["headers"]), Jsonb(t["notes"]),
             t["page_start"], t["page_end"]) for t in tables))
        counts["table_rows"] = _copy(conn, "table_rows", [
            "row_id", "table_id", "sl_no", "subrow", "row_heading", "cells", "rate", "threshold",
            "page_start", "page_end"], (
            (r["row_id"], r["table_id"], r["sl_no"], r["subrow"], r["row_heading"],
             Jsonb(r["cells"]), r.get("rate"), r.get("threshold"), r["page_start"],
             r["page_end"]) for r in rows))
        counts["amendments"] = _copy(conn, "amendments", [
            "key", "label", "type", "amending_act", "effective_date", "header", "prior_text",
            "target_desc", "page"], (
            (a["key"], a["label"], a["type"], a["amending_act"], a["effective_date"], a["header"],
             a["prior_text"], a["target_desc"], a["page"]) for a in amend))
        counts["amendment_links"] = _copy(conn, "amendment_links", ["key", "provision_id"], (
            (a["key"], nid) for a in amend for nid in dict.fromkeys(a["linked_nodes"])))
        counts["cross_refs"] = _copy(conn, "cross_refs", [
            "from_id", "raw", "ref_type", "to_id", "resolution"], (
            (x["from_id"], x["raw"], x["ref_type"], x["to_id"], x["resolution"])
            for x in xrefs))
        conn.commit()
    log.info("loaded", source=str(d), **counts)
    return counts


if __name__ == "__main__":
    print(json.dumps(load(), indent=2))
