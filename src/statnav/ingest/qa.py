"""Ingestion scorecard: how much of the Act did the parser recover, and how cleanly?

    python -m statnav.ingest.qa          # prints the scorecard, writes qa.json next to the cache
"""

from __future__ import annotations

import json
import re
from collections import Counter

from statnav.ingest.build import latest, load_jsonl

EXPECTED_SECTIONS = 536
EXPECTED_SCHEDULES = 16
EXPECTED_CHAPTERS = 23

# (metric, threshold) the build must meet; tests/test_qa.py enforces these
THRESHOLDS = {
    "sections_found": EXPECTED_SECTIONS,
    "chapters_found": EXPECTED_CHAPTERS,
    "schedules_found": EXPECTED_SCHEDULES,
    "footnote_link_rate": 0.95,
    "marker_placement_rate": 1.0,
    "xref_internal_resolved_rate": 0.93,
    "table_sl_sequence_ok_rate": 0.9,
}


def _sl_key(sl: str) -> tuple[int, str]:
    m = re.match(r"(\d+)([A-Z]*)", sl)
    return (int(m.group(1)), m.group(2)) if m else (0, sl)


def scorecard() -> dict:
    d = latest()
    manifest = json.loads((d / "manifest.json").read_text(encoding="utf-8"))
    prov = load_jsonl(d / "provisions.jsonl")
    amend = load_jsonl(d / "amendments.jsonl")
    xrefs = load_jsonl(d / "xrefs.jsonl")
    tables = load_jsonl(d / "tables.jsonl")
    rows = load_jsonl(d / "table_rows.jsonl")

    kinds = Counter(p["kind"] for p in prov)
    internal = [x for x in xrefs if x["resolution"] != "external"]
    res = Counter(x["resolution"] for x in internal)

    seq_ok = 0
    for t in tables:
        sls = []
        for r in rows:
            if r["table_id"] == t["table_id"] and r["sl_no"] not in sls:
                sls.append(r["sl_no"])
        keys = [_sl_key(s) for s in sls]
        if sls and keys == sorted(keys) and keys[0][0] == 1 and len(set(keys)) == len(keys):
            seq_ok += 1

    card = {
        "pages": manifest["pages"],
        "sections_found": len({p["label"] for p in prov if p["kind"] == "section"}),
        "chapters_found": kinds["chapter"],
        "schedules_found": kinds["schedule"],
        "parts_found": kinds["part"] + kinds["schedule-part"],
        "provision_nodes": len(prov),
        "provision_kinds": dict(kinds),
        "duplicate_ids": sum(1 for w in manifest["warnings"] if w.startswith("duplicate")),
        "header_footer_residue": manifest["header_footer_residue"],
        "markers_total": manifest["markers_total"],
        "marker_placement_rate":
            1 - manifest["markers_unplaced"] / max(manifest["markers_total"], 1),
        "footnotes_parsed": len(amend),
        "footnote_types": dict(Counter(a["type"] for a in amend)),
        "footnotes_with_prior_text": sum(1 for a in amend if a["prior_text"]),
        "footnote_link_rate": sum(1 for a in amend if a["linked_nodes"]) / max(len(amend), 1),
        "amended_provisions": sum(1 for p in prov if p["is_amended"]),
        "xrefs_total": len(xrefs),
        "xrefs_external": len(xrefs) - len(internal),
        "xref_resolution": dict(res),
        "xref_internal_resolved_rate": (res["exact"] + res["inferred"]) / max(len(internal), 1),
        "tables": len(tables),
        "table_rows": len(rows),
        "tables_with_issues": sum(1 for t in tables if t["issues"]),
        "table_sl_sequence_ok_rate": seq_ok / max(len(tables), 1),
        "rows_with_rate_threshold": sum(1 for r in rows if "rate" in r),
    }
    card["passed"] = {k: (card[k] >= v) for k, v in THRESHOLDS.items()}
    (d / "qa.json").write_text(json.dumps(card, indent=2), encoding="utf-8")
    return card


def main() -> None:
    card = scorecard()
    width = max(len(k) for k in card)
    for k, v in card.items():
        if k == "passed":
            continue
        mark = ""
        if k in THRESHOLDS:
            mark = "  PASS" if card["passed"][k] else f"  FAIL (need >= {THRESHOLDS[k]})"
        val = f"{v:.3f}" if isinstance(v, float) else v
        print(f"{k:<{width}}  {val}{mark}")


if __name__ == "__main__":
    main()
