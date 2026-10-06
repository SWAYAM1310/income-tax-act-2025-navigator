"""Does the v7 checker catch a wrong answer? A mutation test.

dev_mini has almost no wrong answers left by v6 (grounded numbers 1.000), so an end-to-end run
shows what the checker costs but not whether it catches anything. This takes answers that a
version got right, corrupts one number in each (30 days -> 91 days, 2% -> 7%), and asks the
checker about both versions against the same evidence:

- **catch rate**: share of corrupted answers flagged as having an unsupported claim;
- **false-flag rate**: share of the original, correct answers flagged.

    python -m evals.verifier_check --version v6 --split dev_mini

Costs two gpt-oss-20b calls per eligible answer (~2.5K tokens each); the evidence is rebuilt
by re-running the agent without generation, so it is exactly what the answer was written from.
"""

from __future__ import annotations

import argparse
import json
import re

from evals.common import RESULTS_DIR, read_jsonl
from statnav.config import CONFIG_DIR, load_yaml
from statnav.obs.logging import get_logger

log = get_logger(__name__)

#: a standalone number (not part of "173(c)", "4(3)" or a label like "C2")
_NUM = re.compile(r"(?<![\w(.\-‑])(\d[\d,]*)(?![\d,]*\)|\(|\w)")
#: the number is a provision / serial / act number rather than a quantity
_LABEL_BEFORE = re.compile(
    r"(?:sections?|paragraph|clause|sub-section|sub‑section|serial number|sl\.? ?no\.?|"
    r"no\.?|table|item|schedule|chapter|rule|of|part|\)\s*(?:or|and|,))\s*$", re.I)


def mutate(answer: str) -> str | None:
    """`answer` with its first quantity (rate, amount, period, threshold) changed, or None.

    Only quantities are corrupted: provision and serial numbers are a different error class,
    and answers often restate the section the question named, which the checker would rightly
    see as unsupported by nothing.
    """
    for m in _NUM.finditer(answer):
        raw = m.group(1).replace(",", "")
        if not raw.isdigit() or 1900 <= int(raw) <= 2100:  # leave years alone
            continue
        if _LABEL_BEFORE.search(answer[max(0, m.start() - 20): m.start()]):
            continue
        n = int(raw)
        new = n * 3 + 1  # never equal, and never a plausible re-reading of the same figure
        return answer[: m.start(1)] + str(new) + answer[m.end(1):]
    return None


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--version", default="v6", help="whose correct answers to corrupt")
    ap.add_argument("--split", default="dev_mini")
    ap.add_argument("--limit", type=int)
    a = ap.parse_args()

    from statnav.agent.graph import Agent
    from statnav.agent.verify import verify
    from statnav.answer import passages
    from statnav.embed.jina import JinaClient
    from statnav.index.db import connect
    from statnav.llm.client import ChatClient

    cfg = load_yaml(CONFIG_DIR / "versions" / f"{a.version}.yaml")
    rows = [r for r in read_jsonl(RESULTS_DIR / a.version / a.split / "outputs.jsonl")
            if not r.get("refused") and r["metrics"].get("fact_recall") == 1.0]
    conn, jina = connect(), JinaClient.from_config()
    classify = ChatClient.for_role("classify") if (cfg.get("agent") or {}).get("scope_check") \
        else None
    agent = Agent(conn, jina, cfg, None, classify)
    checker = ChatClient.for_role("verify")
    out = []
    for r in rows[: a.limit]:
        bad = mutate(r["answer"])
        if bad is None:
            continue
        ev = agent.run(r["question"], generate=False).evidence
        block = passages(ev)
        orig, corrupt = verify(checker, r["answer"], block, len(ev)), verify(checker, bad, block,
                                                                              len(ev))
        out.append({"id": r["id"], "type": r["type"], "answer": r["answer"], "mutated": bad,
                    "orig_flagged": not orig.ok, "orig_error": orig.error,
                    "mutated_flagged": not corrupt.ok, "mutated_error": corrupt.error,
                    "mutated_unsupported": corrupt.unsupported,
                    "tokens": orig.tokens + corrupt.tokens})
        log.info("checked", id=r["id"], orig_flagged=not orig.ok, mutated_flagged=not corrupt.ok)
    conn.close()
    n = len(out)
    summary = {"version": a.version, "split": a.split, "n": n,
               "catch_rate": round(sum(x["mutated_flagged"] for x in out) / n, 4) if n else None,
               "false_flag_rate": round(sum(x["orig_flagged"] for x in out) / n, 4) if n else None,
               "checker_errors": sum(bool(x["orig_error"] or x["mutated_error"]) for x in out),
               "tokens": sum(x["tokens"] for x in out)}
    dest = RESULTS_DIR / "v7" / a.split
    dest.mkdir(parents=True, exist_ok=True)
    (dest / f"verifier_check_{a.version}.json").write_text(
        json.dumps({"summary": summary, "items": out}, indent=2, ensure_ascii=False),
        encoding="utf-8")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
