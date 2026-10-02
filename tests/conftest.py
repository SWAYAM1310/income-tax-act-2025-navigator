import json

import pytest

from statnav.config import pdf_path
from statnav.ingest.build import latest, load_jsonl


@pytest.fixture(scope="session")
def parsed():
    """Cached ingestion artefacts (built once from the PDF if missing, ~25s)."""
    if not pdf_path().exists():
        pytest.skip("source PDF not present")
    d = latest()
    prov = {p["id"]: p for p in load_jsonl(d / "provisions.jsonl")}
    return {
        "dir": d,
        "manifest": json.loads((d / "manifest.json").read_text(encoding="utf-8")),
        "provisions": prov,
        "rows": {r["row_id"]: r for r in load_jsonl(d / "table_rows.jsonl")},
        "tables": {t["table_id"]: t for t in load_jsonl(d / "tables.jsonl")},
        "amendments": load_jsonl(d / "amendments.jsonl"),
        "xrefs": load_jsonl(d / "xrefs.jsonl"),
    }
