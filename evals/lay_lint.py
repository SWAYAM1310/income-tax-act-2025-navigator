"""Does a question leak the answer's location or wording? The lay set must not.

A real user does not know the Act's numbering or vocabulary, so a lay question fails the lint if
it names a provision, quotes a term, or copies a run of the gold text:

    python -m evals.lay_lint            # lint evals/data/lay.jsonl and the old golden set

The old golden set is linted too, for the record: most of its questions name a section, which is
why the ids/under retrievers and the definitions tool score so well on it.
"""

from __future__ import annotations

import argparse
import re
from collections import Counter

from evals.common import GOLDEN, artefacts, norm, read_jsonl, subtree_text
from statnav.retrieve.ids import provision_refs

#: a provision named without the parser's exact shapes: "Schedule III", "Sl. No. 4",
#: "sub-section (2)", "clause (b)", "paragraph 4", "Table 2"
_NAMED = re.compile(
    r"\b(?:sections?|schedules?|sub-sections?|clauses?|paragraphs?|para|tables?|items?|"
    r"chapters?)\s*\(?\s*(?:\d|[IVXL]{1,6}\b|\(\w{1,4}\))"
    r"|\bSl\.?\s*No\b|\bserial (?:number|no)\b", re.I)
#: double or curly quotes, or ASCII single quotes that are not apostrophes ("I'm", "don't")
_QUOTED = re.compile(r"[\"“”‘’]([^\"“”‘’]{2,})[\"“”‘’]|(?<!\w)'([^']{2,60})'(?!\w)")
_STOP_WORDS = (
    "a an the of to in on for by or and is are be been being as at from with that which this "
    "such any its it his her their under shall may if i my me we our you your do does did can "
    "what how when who whom whose why where will would should there than then so not no have has "
    "had was were also into other")
_STOP = set(_STOP_WORDS.split())
#: shortest copied run of content words that counts as a leak
NGRAM = 5


def content_words(text: str) -> list[str]:
    return [w for w in re.findall(r"[\w%]+", norm(text)) if w not in _STOP]


def _grams(words: list[str], n: int) -> set[tuple[str, ...]]:
    return {tuple(words[i:i + n]) for i in range(len(words) - n + 1)}


def gold_text(q: dict) -> str:
    """The gold provisions' text, plus the gold endnote for an amendment question (its facts,
    such as the change type or the earlier wording, live there)."""
    a = artefacts()
    ids = list(q.get("gold_provisions") or []) + list(q.get("gold_table_rows") or [])
    text = " ".join(subtree_text(i) for i in ids if i in a["rows"] or i in a["provisions"])
    key = (q.get("gold_amendment") or {}).get("footnote")
    note = next((x for x in a["amendments"] if x["key"] == key), None) if key else None
    if note:
        text += " " + " ".join(x for x in (note["header"], note.get("prior_text")) if x)
    return text


def copied_run(question: str, gold: str, n: int = NGRAM) -> str | None:
    """The first run of `n` content words the question shares with the gold text."""
    shared = _grams(content_words(question), n) & _grams(content_words(gold), n)
    return " ".join(sorted(shared)[0]) if shared else None


def problems(q: dict) -> list[str]:
    """Why `q` is not a lay question; empty when it passes."""
    text = q["question"]
    out = []
    refs = provision_refs(text)
    if refs or _NAMED.search(text):
        out.append("names a provision: " + (", ".join(refs) or _NAMED.search(text).group(0)))
    m = _QUOTED.search(text)
    if m:
        out.append(f"quotes a term: {m.group(0)}")
    run = copied_run(text, gold_text(q))
    if run:
        out.append(f"copies the gold text: '{run}'")
    return out


def report(rows: list[dict]) -> dict:
    """How many rows fail, by type and by reason."""
    by_type: Counter = Counter()
    by_reason: Counter = Counter()
    failed = 0
    for q in rows:
        p = problems(q)
        if p:
            failed += 1
            by_type[q["type"]] += 1
            for r in p:
                by_reason[r.split(":", 1)[0]] += 1
    return {"n": len(rows), "failed": failed, "by_type": dict(by_type),
            "by_reason": dict(by_reason)}


def main() -> None:
    from evals.common import DATA_DIR

    ap = argparse.ArgumentParser()
    ap.add_argument("--show", action="store_true", help="print each failing lay question")
    a = ap.parse_args()
    print("golden:", report(read_jsonl(GOLDEN)))
    lay = [q for q in read_jsonl(DATA_DIR / "lay.jsonl") if q.get("status") != "rejected"]
    print("lay:", report(lay))
    if a.show:
        for q in lay:
            if problems(q):
                print(q["id"], problems(q), "|", q["question"])


if __name__ == "__main__":
    main()
