"""Shared helpers for the eval pipeline: paths, artefact access, text normalisation."""

from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path

from statnav.config import ROOT
from statnav.ingest.build import latest, load_jsonl

EVAL_DIR = ROOT / "evals"
DATA_DIR = EVAL_DIR / "data"
CANDIDATES = DATA_DIR / "candidates.jsonl"
GOLDEN = DATA_DIR / "golden.jsonl"
VERIFICATION_LOG = DATA_DIR / "verification_log.csv"
SPLITS_DIR = EVAL_DIR / "splits"
RESULTS_DIR = ROOT / "results"

TYPES = ["lookup", "multi_hop", "table", "amendment", "refusal"]


@lru_cache(maxsize=1)
def artefacts() -> dict:
    d = latest()
    prov = {p["id"]: p for p in load_jsonl(d / "provisions.jsonl")}
    rows = {r["row_id"]: r for r in load_jsonl(d / "table_rows.jsonl")}
    return {
        "provisions": prov,
        "rows": rows,
        "tables": {t["table_id"]: t for t in load_jsonl(d / "tables.jsonl")},
        "amendments": load_jsonl(d / "amendments.jsonl"),
        "xrefs": load_jsonl(d / "xrefs.jsonl"),
    }


_NUM_WORDS = {w: n for n, w in enumerate([
    "zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten",
    "eleven", "twelve", "thirteen", "fourteen", "fifteen", "sixteen", "seventeen", "eighteen",
    "nineteen", "twenty"])}
_NUM_WORDS.update({"thirty": 30, "forty": 40, "fifty": 50, "sixty": 60, "seventy": 70,
                   "eighty": 80, "ninety": 90, "hundred": 100})
_SCALE = {"lakh": 100_000, "lakhs": 100_000, "crore": 10_000_000, "crores": 10_000_000}


def _money(t: str) -> str:
    """Canonicalise rupee amounts to 'rs<integer>' so that 'Rs. 50,00,000', '₹50 lakh' and
    'Fifty lakh rupees' all read 'rs5000000'."""
    t = t.replace("₹", " rs ")

    def scaled(m: re.Match) -> str:
        num = m.group(1).replace(",", "")
        val = float(num) if num[0].isdigit() else _NUM_WORDS[num]
        return f" rs{int(round(val * _SCALE[m.group(2)]))} "

    words = "|".join(_NUM_WORDS)
    t = re.sub(rf"(?:\brs\.?\s*)?\b(\d[\d,]*(?:\.\d+)?|{words})\s+(lakhs?|crores?)\b"
               r"(?:\s+rupees)?", scaled, t)
    t = re.sub(r"\brs\.?\s*(\d[\d,]*)(?:\.0+)?\b", lambda m: f" rs{m.group(1).replace(',', '')} ",
               t)
    t = re.sub(r"\b(\d[\d,]*)\s+rupees\b", lambda m: f" rs{m.group(1).replace(',', '')} ", t)
    return t


def norm(text: str) -> str:
    """Lowercase, unify quotes/dashes, canonicalise money, drop punctuation noise."""
    t = _money(text.lower())
    t = re.sub(r"[“”‘’'`\"]", "", t)
    t = re.sub(r"[—–‑-]", " ", t)
    t = re.sub(r"[^\w%.,/()\s]", " ", t)
    t = re.sub(r"(?<=\d),(?=\d)", "", t)  # 20,000 == 20000; 5,00,000 == 500000
    return re.sub(r"\s+", " ", t).strip(" .,;")


def contains(haystack: str, needle: str) -> bool:
    return norm(needle) in norm(haystack)


def descendants(pid: str) -> list[str]:
    prov = artefacts()["provisions"]
    out, todo = [], [pid]
    while todo:
        n = todo.pop()
        out.append(n)
        if n in prov:
            todo.extend(prov[n]["children"])
    return out


def subtree_text(pid: str, limit: int | None = None) -> str:
    prov = artefacts()["provisions"]
    if pid in artefacts()["rows"]:
        r = artefacts()["rows"][pid]
        return "; ".join(f"{k}: {v}" for k, v in r["cells"].items() if v)
    parts = []
    for n in sorted(descendants(pid), key=lambda i: list(prov).index(i) if i in prov else 0):
        p = prov.get(n)
        if p and p["text"]:
            parts.append(f"{p['label'] or ''} {p['text']}".strip())
    text = " ".join(parts)
    return text[:limit] if limit else text


def cite(pid: str) -> str:
    """Human citation for a provision or table row id."""
    a = artefacts()
    if pid in a["rows"]:
        r = a["rows"][pid]
        owner = a["provisions"][r["table_id"]]
        base = owner["number"].replace(" (Table)", "").replace(" (Table ", " (Table ")
        return f"{base}, Table Sl. No. {r['sl_label']}"
    p = a["provisions"][pid]
    if p["schedule"]:
        return p["number"]
    return f"section {p['number']}"


def read_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with path.open(encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
