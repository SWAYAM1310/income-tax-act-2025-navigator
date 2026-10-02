"""Human verification of golden-dataset candidates. Only accepted items enter golden.jsonl.

    python -m evals.review                     # review all unverified candidates
    python -m evals.review --type table        # one question type
    python -m evals.review --reviewer swayam    # name recorded in the verification log

For each candidate the gold evidence (provision text / table row / prior wording) is shown.
Keys: [a]ccept  [e]dit then accept  [r]eject  [s]kip  [q]uit. Progress is saved after every
decision, so you can stop and resume any time. Every decision is appended to
evals/data/verification_log.csv with a timestamp and the before/after diff.
"""

from __future__ import annotations

import argparse
import csv
import json
import textwrap
from datetime import UTC, datetime

from evals.common import (
    CANDIDATES,
    GOLDEN,
    VERIFICATION_LOG,
    artefacts,
    cite,
    contains,
    read_jsonl,
    subtree_text,
    write_jsonl,
)

WRAP = 100


def _show(c: dict, n: int, total: int) -> None:
    a = artefacts()
    print("\n" + "=" * WRAP)
    print(f"[{n}/{total}] {c['id']}  type={c['type']}  source={c['source']}  ({c['note']})")
    print("-" * WRAP)
    print(textwrap.fill("Q: " + c["question"], WRAP))
    print(textwrap.fill("Gold answer: " + c["gold_answer"][:600], WRAP))
    print(f"Gold facts (must appear in an answer): {c['gold_facts']}")
    if c["should_refuse"]:
        print("Expected behaviour: REFUSE (out of scope)")
    for pid in c["gold_provisions"] + c["gold_table_rows"]:
        if pid in a["provisions"] or pid in a["rows"]:
            text = subtree_text(pid)
            print(f"\n  Evidence {cite(pid)} [{pid}]:")
            print(textwrap.indent(textwrap.fill(text[:900] + ("..." if len(text) > 900 else ""),
                                                WRAP - 4), "    "))
            missing = [f for f in c["gold_facts"] if not contains(text, f)]
            if missing and c["type"] not in ("multi_hop", "amendment"):
                print(f"    ! facts not found in this evidence: {missing}")
    if c.get("gold_amendment") and c["gold_amendment"].get("prior_text"):
        print("\n  Prior text (before Finance Act 2026):")
        print(textwrap.indent(textwrap.fill(c["gold_amendment"]["prior_text"][:700], WRAP - 4),
                              "    "))
    print("-" * WRAP)


def _edit(c: dict) -> dict:
    new = dict(c)
    q = input("  New question (Enter = keep): ").strip()
    if q:
        new["question"] = q
    f = input("  New facts separated by | (Enter = keep, '-' = none): ").strip()
    if f == "-":
        new["gold_facts"] = []
    elif f:
        new["gold_facts"] = [x.strip() for x in f.split("|") if x.strip()]
    g = input("  New gold answer (Enter = keep): ").strip()
    if g:
        new["gold_answer"] = g
    return new


def _log(reviewer: str, c_before: dict, c_after: dict, action: str) -> None:
    VERIFICATION_LOG.parent.mkdir(parents=True, exist_ok=True)
    new_file = not VERIFICATION_LOG.exists()
    diff = {k: [c_before.get(k), c_after.get(k)] for k in ("question", "gold_facts", "gold_answer")
            if c_before.get(k) != c_after.get(k)}
    with VERIFICATION_LOG.open("a", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        if new_file:
            w.writerow(["timestamp", "reviewer", "id", "type", "action", "diff"])
        w.writerow([datetime.now(UTC).isoformat(timespec="seconds"), reviewer, c_after["id"],
                    c_after["type"], action, json.dumps(diff, ensure_ascii=False)])


def rebuild_golden() -> int:
    accepted = [c for c in read_jsonl(CANDIDATES) if c["status"] == "accepted"]
    write_jsonl(GOLDEN, [{k: v for k, v in c.items() if k != "status"} for c in accepted])
    return len(accepted)


def bulk_accept(reviewer: str, kind: str | None) -> int:
    """Accept every unverified candidate without per-item review, on the reviewer's explicit
    instruction. Logged as 'bulk-accept' so the dataset's provenance stays visible."""
    cands = read_jsonl(CANDIDATES)
    n = 0
    for c in cands:
        if c["status"] == "unverified" and (not kind or c["type"] == kind):
            before = dict(c)
            c["status"] = "accepted"
            _log(reviewer, before, c, "bulk-accept (user instruction)")
            n += 1
    write_jsonl(CANDIDATES, cands)
    rebuild_golden()
    return n


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--type")
    ap.add_argument("--reviewer", default="reviewer")
    ap.add_argument("--accept-all", action="store_true",
                    help="accept all unverified candidates without per-item review (logged)")
    a = ap.parse_args()
    if a.accept_all:
        n = bulk_accept(a.reviewer, a.type)
        print(f"bulk-accepted {n}; golden set now has {rebuild_golden()} questions")
        return
    cands = read_jsonl(CANDIDATES)
    todo = [c for c in cands if c["status"] == "unverified" and (not a.type or c["type"] == a.type)]
    print(f"{len(todo)} candidates to review "
          f"({sum(c['status'] == 'accepted' for c in cands)} already accepted).")
    by_id = {c["id"]: c for c in cands}
    for n, c in enumerate(todo, 1):
        _show(c, n, len(todo))
        while True:
            k = input("[a]ccept [e]dit [r]eject [s]kip [q]uit > ").strip().lower()[:1]
            if k in ("a", "e", "r", "s", "q"):
                break
        if k == "q":
            break
        if k == "s":
            continue
        before = dict(c)
        after = _edit(c) if k == "e" else dict(c)
        after["status"] = "rejected" if k == "r" else "accepted"
        by_id[c["id"]] = after
        _log(a.reviewer, before, after, {"a": "accept", "e": "edit+accept", "r": "reject"}[k])
        write_jsonl(CANDIDATES, list(by_id.values()))
        rebuild_golden()
    total = rebuild_golden()
    print(f"\n{total} accepted questions in {GOLDEN}")


if __name__ == "__main__":
    main()
