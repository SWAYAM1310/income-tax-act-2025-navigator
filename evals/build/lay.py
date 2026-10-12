"""Build the lay-person question set (`evals/data/lay.jsonl`).

The golden set was written in the Act's own terms: most questions name the section, quote the
defined term or copy a table row (`python -m evals.lay_lint`). Real users of the chat do not
know the Act's numbering or vocabulary. This set asks for the same law in their words.

    python -m evals.build.lay --paraphrase       # draft rewrites of dev golden questions (Groq)
    python -m evals.build.lay                    # (re)add the hand-written situations only
    python -m evals.build.lay --accept ID ...    # review: accept, or
    python -m evals.build.lay --reject ID ... --why "gold does not answer it"
    python -m evals.build.lay --edit ID --question "..."   # reword, re-lint, then accept

Two styles:
  paraphrase  a dev golden question rewritten by gpt-oss-20b; the gold labels are copied
              unchanged, so `lay_orig` (the originals) against `lay_dev` measures the cost of
              lay wording on the same gold. Test questions are never paraphrased.
  situation   an everyday question written by hand (`evals/build/lay_situations.py`) whose gold
              provisions were found by reading the Act, not by running the retriever.

Every row must pass the leak lint, and every gold fact must occur verbatim in its gold text.
"""

from __future__ import annotations

import argparse
import csv
import json
import random
from datetime import UTC, datetime

from evals.build.generate import _id, _llm_json
from evals.common import (
    DATA_DIR,
    GOLDEN,
    SPLITS_DIR,
    VERIFICATION_LOG,
    artefacts,
    contains,
    read_jsonl,
    write_jsonl,
)
from evals.lay_lint import gold_text, problems

LAY = DATA_DIR / "lay.jsonl"
SEED = 2026
PER_TYPE = {"lookup": 20, "table": 20, "multi_hop": 12, "amendment": 10, "refusal": 8}

PARAPHRASE_PROMPT = """You help build a test set for a chatbot that explains India's Income-tax \
Act, 2025 to ordinary people. Below is a question written by a tax expert and the part of the \
Act that answers it. Rewrite the question the way an ordinary taxpayer with no legal training \
would type it into a chat box.

Rules:
- Ask for the same information, so the same part of the Act still answers it. Keep the details \
that change the answer (who pays whom, resident or non-resident, the kind of payment or income).
- Never mention a section, Schedule, clause, table, serial number or paragraph. Do not quote the \
Act and do not put any word in quotation marks.
- Use everyday words where an ordinary person would ("farm income", "cut tax from the payment", \
"my employer"). Never copy 5 or more words in a row from the Act text.
- Write it in the first person ("I ...", "my ...") if that is how someone would naturally ask, \
otherwise as a general question. One or two plain sentences, no greeting.
{hint}
Return only JSON: {{"question": "...", "person": "first" or "third"}}

Expert question: {question}

Part of the Act that answers it:
{gold}"""

HINTS = {
    "lookup": "- If the expert asks what a term means, ask what the idea covers or whether "
              "something counts as it, in your own words.",
    "table": "- The expert copied a row of a rate table. Describe the situation in a few words "
             "(who pays whom, for what) and ask how much tax is cut or what the rate is.",
    "multi_hop": "- Keep the question about the same situation; do not add new conditions.",
    "amendment": "- This is about a change made by the Finance Act, 2026. Ask whether the 2026 "
                 "budget changed the rule on this topic, describing the topic in plain words.",
    "refusal": "- This question is outside what the Act covers. Keep the same subject and just "
               "reword it casually.",
}


def lay_row(base: dict, question: str, *, style: str, person: str, key: str,
            pair_of: str | None = None, source: str = "hand-written") -> dict:
    """A lay question with `base`'s gold labels."""
    gold = {k: base.get(k) for k in ("gold_answer", "gold_facts", "gold_provisions",
                                     "gold_table_rows", "gold_amendment", "should_refuse")}
    gold["gold_facts"] = list(gold["gold_facts"] or [])
    gold["gold_provisions"] = list(gold["gold_provisions"] or [])
    gold["gold_table_rows"] = list(gold["gold_table_rows"] or [])
    return {"id": _id("lay_" + base["type"], key), "type": base["type"], "question": question,
            **gold, "style": style, "person": person, "pair_of": pair_of, "source": source,
            "note": base.get("note", ""), "status": "unverified"}


def check(row: dict) -> list[str]:
    """Lint problems plus gold-label problems; empty when the row is usable."""
    out = problems(row)
    a = artefacts()
    for gid in row["gold_provisions"] + row["gold_table_rows"]:
        if gid not in a["provisions"] and gid not in a["rows"]:
            out.append(f"unknown gold id {gid}")
    text = gold_text(row)
    kind = (row.get("gold_amendment") or {}).get("type")
    for f in row["gold_facts"]:
        # a change-type fact ("substituted") is scored by stem, not found verbatim
        if f != kind and not contains(text, f):
            out.append(f"fact not in gold text: {f!r}")
    if row["should_refuse"] == bool(row["gold_provisions"] or row["gold_table_rows"]):
        out.append("a refusal must have no gold provisions, an answerable row must have some")
    return out


def paraphrases(llm, rng: random.Random) -> list[dict]:
    """Rewrite PER_TYPE dev golden questions per type. A rewrite that fails the lint gets one
    retry with the problems listed; if it fails again it is dropped."""
    dev = set((SPLITS_DIR / "dev.ids").read_text(encoding="utf-8").split())
    golden = [q for q in read_jsonl(GOLDEN) if q["id"] in dev]
    out = []
    for kind, n in PER_TYPE.items():
        pool = [q for q in golden if q["type"] == kind]
        rng.shuffle(pool)
        for q in pool[:n]:
            prompt = PARAPHRASE_PROMPT.format(hint=HINTS[kind], question=q["question"],
                                              gold=(gold_text(q) or q["gold_answer"])[:1800])
            row = None
            for _ in range(2):
                res = _llm_json(llm, prompt)
                if not res or not isinstance(res.get("question"), str):
                    continue
                row = lay_row(q, res["question"].strip(), style="paraphrase",
                              person="first" if res.get("person") == "first" else "third",
                              key=q["id"], pair_of=q["id"], source="llm:" + llm.model)
                issues = check(row)
                if not issues:
                    break
                prompt += (f"\n\nYour rewrite {res['question']!r} broke the rules: "
                           f"{'; '.join(issues)}. Write a new one.")
            if row and not check(row):
                out.append(row)
    return out


def situations() -> list[dict]:
    """The hand-written everyday questions, with their gold labels checked."""
    from evals.build.lay_situations import SITUATIONS

    out = []
    for s in SITUATIONS:
        base = {"type": s["type"], "gold_answer": s.get("answer", ""),
                "gold_facts": s.get("facts", []), "gold_provisions": s.get("provisions", []),
                "gold_table_rows": s.get("rows", []), "gold_amendment": s.get("amendment"),
                "should_refuse": s["type"] == "refusal", "note": s.get("note", "")}
        row = lay_row(base, s["q"], style="situation", person=s.get("person", "first"),
                      key="situation:" + s["q"])
        issues = check(row)
        if issues:
            raise SystemExit(f"situation fails its checks: {s['q']!r}: {issues}")
        out.append(row)
    return out


def log(reviewer: str, row: dict, action: str, diff: dict) -> None:
    new = not VERIFICATION_LOG.exists()
    with VERIFICATION_LOG.open("a", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        if new:
            w.writerow(["timestamp", "reviewer", "id", "type", "action", "diff"])
        w.writerow([datetime.now(UTC).isoformat(timespec="seconds"), reviewer, row["id"],
                    row["type"], action, json.dumps(diff, ensure_ascii=False)])


def review(rows: dict[str, dict], ids: list[str], action: str, reviewer: str,
           why: str = "", question: str | None = None) -> None:
    for i in ids:
        row = rows[i]
        diff: dict = {"why": why} if why else {}
        if question:
            diff["question"] = [row["question"], question]
            row["question"] = question
            issues = check(row)
            if issues:
                raise SystemExit(f"{i}: the new wording fails its checks: {issues}")
        row["status"] = "rejected" if action == "reject" else "accepted"
        log(reviewer, row, action, diff)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--paraphrase", action="store_true", help="draft rewrites with gpt-oss-20b")
    ap.add_argument("--accept", nargs="*", default=[])
    ap.add_argument("--reject", nargs="*", default=[])
    ap.add_argument("--edit")
    ap.add_argument("--question", help="new wording for --edit")
    ap.add_argument("--why", default="")
    ap.add_argument("--reviewer", default="claude")
    a = ap.parse_args()
    rows = {r["id"]: r for r in read_jsonl(LAY)}
    if a.accept or a.reject or a.edit:
        review(rows, a.accept, "accept", a.reviewer, a.why)
        review(rows, a.reject, "reject", a.reviewer, a.why)
        if a.edit:
            review(rows, [a.edit], "edit", a.reviewer, a.why, a.question)
        write_jsonl(LAY, list(rows.values()))
        print({s: sum(r["status"] == s for r in rows.values())
               for s in ("unverified", "accepted", "rejected")})
        return
    new = situations()
    if a.paraphrase:
        from statnav.llm.client import ChatClient

        new += paraphrases(ChatClient.for_role("verify"), random.Random(SEED))
    added = 0
    for r in new:
        old = rows.get(r["id"])
        if old is None or (old["status"] == "unverified" and r["style"] == "situation"):
            added += old is None
            rows[r["id"]] = r  # an unreviewed situation follows its source; reviewed rows stay
    write_jsonl(LAY, list(rows.values()))
    by: dict[str, int] = {}
    for r in rows.values():
        by[f"{r['style']}/{r['type']}"] = by.get(f"{r['style']}/{r['type']}", 0) + 1
    print(f"added {added}; {len(rows)} rows: {by} -> {LAY}")


if __name__ == "__main__":
    main()
