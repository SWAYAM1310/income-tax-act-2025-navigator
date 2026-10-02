"""Run the full ingestion pipeline once and cache the artefacts.

    python -m statnav.ingest.build [--force]

Writes data/parsed/<sha8>-v<PARSER_VERSION>/:
  provisions.jsonl   one row per node (chapter/part/section/sub-section/.../table)
  table_rows.jsonl   one row per table (sub-)row with named cells and Rate/Threshold split
  tables.jsonl       table metadata (title, headers, notes, pages)
  amendments.jsonl   Finance Act 2026 endnotes, linked to provisions
  xrefs.jsonl        cross-references with resolution status
  pages_clean.jsonl  page text without running header/footer and without endnotes (for v1)
  pages_raw.jsonl    plain PyMuPDF get_text() per page, nothing removed (for the naive v0)
  manifest.json      source hash, parser version, counts
Downstream steps (chunking, embeddings, eval) read only these files, never the PDF.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import time
from dataclasses import asdict
from pathlib import Path

import pymupdf

from statnav.config import ROOT, base_config, pdf_path
from statnav.ingest import formulas
from statnav.ingest.pdf_layout import FN_TOKEN_RE, extract
from statnav.ingest.structure import ParseResult, parse
from statnav.ingest.tables import Table
from statnav.ingest.xrefs import Resolver
from statnav.obs.logging import get_logger

PARSER_VERSION = 3
log = get_logger("ingest.build")


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def out_dir(sha: str) -> Path:
    return ROOT / base_config()["paths"]["parsed_dir"] / f"{sha[:8]}-v{PARSER_VERSION}"


def _write_jsonl(path: Path, rows) -> int:
    n = 0
    with path.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
            n += 1
    return n


def _split_rate_threshold(text: str) -> dict[str, str]:
    """Section 393-style column D: 'Rate: 2% ____ Threshold limit: Rs. 20,000.'"""
    m = re.match(r"^\s*Rate\s*:\s*(.*?)\s*_{3,}\s*Threshold limit\s*:\s*(.*)$", text, re.S)
    if not m:
        return {}
    return {"rate": m.group(1).strip(), "threshold": m.group(2).strip()}


def table_row_records(table: Table, table_id: str) -> list[dict]:
    headers = table.headers or [f"col_{k}" for k in range(len(table.letters))]
    out = []
    for row in table.rows:
        for si, sub in enumerate(row.subrows):
            cells = {}
            for ci, cell in enumerate(sub.cells):
                name = headers[ci] if ci < len(headers) and headers[ci] else f"col_{ci}"
                cells[name] = cell.text
            # col A is the serial number; drop the empty cell it leaves behind
            cells = {h: v for h, v in cells.items() if v or not h.lower().startswith("sl")}
            derived = {}
            for v in cells.values():
                derived.update(_split_rate_threshold(v))
            # unlabelled continuation sub-rows get "~2", "~3" so row ids stay unique
            sl = row.sl_no + (sub.label or (f"~{si + 1}" if si else ""))
            # a sub-row's own cells decide its pages (row 3(iii) is on p.457, row 3 began on 456)
            pages = sorted({ln.page for c in sub.cells for ln in c.lines} or row.pages)
            out.append({
                "row_id": f"{table_id}#{sl}",
                "table_id": table_id,
                "sl_no": row.sl_no,
                "subrow": sub.label,
                "sl_label": sl,
                "row_heading": row.heading.text or None,
                "cells": cells,
                "letters": dict(zip(table.letters, [sub.cells[k].text for k in
                                                    range(len(sub.cells))], strict=False)),
                **derived,
                "amendment_markers": sorted({lab for c in sub.cells
                                             for lab in FN_TOKEN_RE.findall(c.raw)}),
                "page_start": pages[0] if pages else table.page_start,
                "page_end": pages[-1] if pages else table.page_end,
            })
    return out


def build(force: bool = False) -> Path:
    src = pdf_path()
    expected = base_config()["source"]["sha256"]
    sha = sha256(src)
    if expected and sha != expected:
        raise SystemExit(f"PDF hash {sha} does not match configs/base.yaml ({expected})")
    out = out_dir(sha)
    if (out / "manifest.json").exists() and not force:
        log.info("cache_hit", dir=str(out))
        return out
    out.mkdir(parents=True, exist_ok=True)
    t0 = time.perf_counter()

    doc = pymupdf.open(src)
    pages = extract(doc)
    lines = [ln for p in pages for ln in p.lines]
    result: ParseResult = parse(lines)
    formula_placement = formulas.inject(result, lines)
    log.info("parsed", nodes=len(result.nodes), tables=len(result.tables),
             footnotes=len(result.footnotes), secs=round(time.perf_counter() - t0, 1))

    # amendments: provision -> footnote keys
    amended: dict[str, list[str]] = {}
    for fn in result.footnotes:
        for nid in fn.linked_nodes:
            amended.setdefault(nid, []).append(fn.key)

    def provision_rows():
        for n in result.nodes.values():
            yield {
                "id": n.id, "kind": n.kind, "number": n.number, "label": n.label,
                "heading": n.heading, "text": n.clean_text, "text_marked": n.text,
                "parent": n.parent, "children": n.children, "chapter": n.chapter,
                "part": n.part, "schedule": n.schedule, "page_start": n.page_start,
                "page_end": n.page_end, "is_amended": n.id in amended,
                "amendments": amended.get(n.id, []),
            }

    counts = {"provisions": _write_jsonl(out / "provisions.jsonl", provision_rows())}

    rows, tables_meta = [], []
    for t in result.tables:
        tid = result.table_owner.get(t.index)
        if tid is None:
            continue
        rows += table_row_records(t, tid)
        tables_meta.append({
            "table_id": tid, "index": t.index, "title": t.title, "headers": t.headers,
            "letters": t.letters, "page_start": t.page_start, "page_end": t.page_end,
            "notes": t.notes, "issues": t.issues, "n_rows": len(t.rows),
        })
    counts["tables"] = _write_jsonl(out / "tables.jsonl", tables_meta)
    counts["table_rows"] = _write_jsonl(out / "table_rows.jsonl", rows)

    counts["amendments"] = _write_jsonl(out / "amendments.jsonl", (
        {**{k: v for k, v in asdict(fn).items() if k != "raw_lines"},
         "linked_node": fn.linked_node} for fn in result.footnotes))

    table_rows: dict[str, list[str]] = {}
    for r in rows:
        table_rows.setdefault(r["table_id"], []).append(r["row_id"])
        base = f"{r['table_id']}#{r['sl_no']}"
        if base not in table_rows[r["table_id"]]:
            table_rows[r["table_id"]].append(base)
    resolver = Resolver(result.nodes, table_rows)
    xrefs = []
    for n in result.nodes.values():
        if n.clean_text:
            xrefs += resolver.extract(n, n.clean_text)
    for r in rows:
        node = result.nodes[r["table_id"]]
        for v in r["cells"].values():
            for x in resolver.extract(node, v):
                x.from_id = r["row_id"]
                xrefs.append(x)
    counts["xrefs"] = _write_jsonl(out / "xrefs.jsonl", (asdict(x) for x in xrefs))

    # clean page text for the v1 baseline: no header/footer, endnote lines removed
    endnote_lines = set()
    for fn in result.footnotes:
        endnote_lines.update(range(fn.line_index, fn.line_index + len(fn.raw_lines)))
    by_page: dict[int, list[str]] = {}
    for k, ln in enumerate(lines):
        if k not in endnote_lines:
            by_page.setdefault(ln.page, []).append(FN_TOKEN_RE.sub("", ln.text))
    counts["pages_clean"] = _write_jsonl(out / "pages_clean.jsonl", (
        {"page": p.number, "text": "\n".join(by_page.get(p.number, []))} for p in pages))
    # untouched PyMuPDF text (headers, footers, endnotes and all) for the naive v0 baseline
    counts["pages_raw"] = _write_jsonl(out / "pages_raw.jsonl", (
        {"page": pg.number + 1, "text": pg.get_text()} for pg in doc))

    manifest = {
        "source_sha256": sha, "parser_version": PARSER_VERSION, "pages": len(pages),
        "counts": counts, "warnings": result.warnings,
        "markers_total": sum(len(p.markers) for p in pages),
        "markers_unplaced": sum(len(p.unplaced_markers) for p in pages),
        "header_footer_residue": sum(
            1 for ln in lines
            if "Income Tax Department" in ln.text or "Downloaded/Printed" in ln.text),
        "formulas": formula_placement,
        "build_seconds": round(time.perf_counter() - t0, 1),
    }
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    log.info("built", dir=str(out), **counts)
    return out


def load_jsonl(path: Path) -> list[dict]:
    with path.open(encoding="utf-8") as f:
        return [json.loads(line) for line in f]


def latest() -> Path:
    """The cached artefact directory for the configured PDF (building it if needed)."""
    return build(force=False)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--force", action="store_true", help="rebuild even if cached")
    print(build(force=ap.parse_args().force))
