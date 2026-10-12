"""Retrieval on lay questions against the same gold in the Act's words.

    python -m evals.lay_report                     # v0 v2 v3 v5 v6 v8 on lay_dev / lay_orig
    python -m evals.lay_report --versions v8 v10 --split lay_test

Reads `results/<v>/<split>/outputs.jsonl` written by `evals.run --retrieval-only`. Prints, per
version: recall@5 / MRR / hit@1 overall, by type and by style; for the paraphrases, the same
questions' originals (`lay_orig`), so the gap is the cost of lay wording alone; and how often the
scope check refused an answerable lay question.
"""

from __future__ import annotations

import argparse
import statistics

from evals.common import RESULTS_DIR, read_jsonl
from evals.splits import LAY

METRICS = ("recall@5", "mrr", "hit@1")


def _mean(recs: list[dict], m: str) -> float | None:
    vals = [r["metrics"][m] for r in recs if m in r["metrics"]]
    return round(statistics.mean(vals), 3) if vals else None


def _cell(recs: list[dict]) -> str:
    vals = [_mean(recs, m) for m in METRICS]
    return " / ".join("-" if v is None else f"{v:.3f}" for v in vals) + f" (n={len(recs)})"


def summary(version: str, split: str) -> dict | None:
    path = RESULTS_DIR / version / split / "outputs.jsonl"
    if not path.exists():
        return None
    lay = {q["id"]: q for q in read_jsonl(LAY)}
    recs = read_jsonl(path)
    answerable = [r for r in recs if not lay[r["id"]]["should_refuse"]]
    out = {"all": _cell(answerable)}
    for t in ("lookup", "table", "multi_hop", "amendment"):
        out[t] = _cell([r for r in answerable if r["type"] == t])
    for s in ("situation", "paraphrase"):
        out[s] = _cell([r for r in answerable if lay[r["id"]]["style"] == s])
    para = [r for r in answerable if lay[r["id"]]["style"] == "paraphrase"]
    orig_path = RESULTS_DIR / version / "lay_orig" / "outputs.jsonl"
    if orig_path.exists():
        orig = {r["id"]: r for r in read_jsonl(orig_path)}
        pairs = [orig[lay[r["id"]]["pair_of"]] for r in para if lay[r["id"]]["pair_of"] in orig]
        out["paraphrase originals"] = _cell(pairs)
    scoped = [r for r in recs if "scope_refused" in r["metrics"]]
    if scoped:
        wrong = [r for r in scoped if r["metrics"]["scope_refused"]
                 and not lay[r["id"]]["should_refuse"]]
        caught = [r for r in scoped if r["metrics"]["scope_refused"]
                  and lay[r["id"]]["should_refuse"]]
        n_ans = sum(not lay[r["id"]]["should_refuse"] for r in scoped)
        n_ref = len(scoped) - n_ans
        out["scope: answerable refused"] = f"{len(wrong)}/{n_ans}"
        out["scope: refusals caught"] = f"{len(caught)}/{n_ref}"
        out["_wrongly_refused"] = [r["id"] for r in wrong]
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--versions", nargs="*", default=["v0", "v2", "v3", "v5", "v6", "v8"])
    ap.add_argument("--split", default="lay_dev")
    ap.add_argument("--show", action="store_true", help="list wrongly refused question ids")
    a = ap.parse_args()
    rows = {v: summary(v, a.split) for v in a.versions}
    rows = {v: s for v, s in rows.items() if s}
    keys = list(dict.fromkeys(k for s in rows.values() for k in s if not k.startswith("_")))
    print(f"| {a.split}: recall@5 / MRR / hit@1 | " + " | ".join(rows) + " |")
    print("|---|" + "---|" * len(rows))
    for k in keys:
        print(f"| {k} | " + " | ".join(s.get(k, "-") for s in rows.values()) + " |")
    if a.show:
        for v, s in rows.items():
            print(v, "wrongly refused:", s.get("_wrongly_refused", []))


if __name__ == "__main__":
    main()
