"""Run one ladder version on one split and write versioned results.

    python -m evals.run --version v0 --split dev --retrieval-only
    python -m evals.run --version v2 --split dev_mini            # end-to-end with Groq
    python -m evals.run --version oracle --split dev_mini        # generation upper bound
    python -m evals.run --version v2 --split test --final         # the frozen test split
    python -m evals.run --version v0 --split candidates --retrieval-only   # provisional

Writes results/<version>/<split>/{metrics.json, outputs.jsonl, run_meta.json}. LLM and Jina
calls are cached, so an interrupted run (e.g. daily Groq quota) resumes where it stopped.
"""

from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime

from evals.common import (
    CANDIDATES,
    GOLDEN,
    RESULTS_DIR,
    SPLITS_DIR,
    artefacts,
    cite,
    descendants,
    read_jsonl,
    subtree_text,
    write_jsonl,
)
from evals.metrics import aggregate, generation_metrics, gold_targets, retrieval_metrics
from statnav.answer import (
    SYSTEM_PROMPT,
    answer_role,
    inline_cites,
    pack,
    parse_citations,
    user_prompt,
)
from statnav.config import CONFIG_DIR, load_yaml
from statnav.embed import tokens
from statnav.obs.logging import get_logger

log = get_logger("evals.run")


def load_questions(split: str, final: bool) -> list[dict]:
    """Questions of a split. `<split>:<type>` keeps one question type (`dev:amendment`), and
    `<split>:substitution` the amendment questions whose endnote quotes the replaced words --
    the ones `amendment_direction` can score. Their results go to `<split>_<filter>/`."""
    if ":" in split:
        base, keep = split.split(":", 1)
        qs = load_questions(base, final)
        if keep == "substitution":
            from evals.metrics import substitution_pair
            return [q for q in qs if substitution_pair(q)]
        return [q for q in qs if q["type"] == keep]
    if split == "candidates":
        return [c for c in read_jsonl(CANDIDATES) if c["status"] != "rejected"]
    if split == "smoke":  # a handful of unverified candidates, for pipeline checks only
        ids = (CANDIDATES.parent / "smoke_ids.txt").read_text(encoding="utf-8").split()
        by_id = {c["id"]: c for c in read_jsonl(CANDIDATES)}
        return [by_id[i] for i in ids if i in by_id]
    if split == "test" and not final:
        raise SystemExit("the test split is for reported numbers only: pass --final")
    if split == "test":
        from evals.splits import SPLITS_DIR as _S
        from evals.splits import test_digest
        frozen = (_S / "test.sha256").read_text(encoding="utf-8").strip()
        if test_digest((_S / "test.ids").read_text(encoding="utf-8").split()) != frozen:
            raise SystemExit("test.ids no longer matches the frozen test.sha256; refusing to run")
    path = SPLITS_DIR / f"{split}.ids"
    if not path.exists():
        raise SystemExit(f"{path} missing: verify questions (evals.review), then evals.splits")
    ids = path.read_text(encoding="utf-8").split()
    golden = {q["id"]: q for q in read_jsonl(GOLDEN)}
    return [golden[i] for i in ids if i in golden]


def oracle_hits(q: dict, budget: int) -> list[dict]:
    hits, used = [], 0
    for gid in gold_targets(q):
        text = f"{cite(gid)}: {subtree_text(gid)}"
        # the amendment endnotes linked to this subtree are part of the gold context
        nodes = set(descendants(gid))
        for a in artefacts()["amendments"]:
            if nodes & set(a.get("linked_nodes") or []):
                note = " ".join(x for x in (a["header"], a.get("prior_text")) if x)
                text += f"\nEndnote {a['label']}: {note}"
        piece = tokens.decode(tokens.encode(text)[: max(0, budget - used)])
        if not piece:
            break
        used += tokens.count(piece)
        hits.append({"chunk_id": f"oracle:{gid}", "text": piece, "tokens": tokens.count(piece),
                     "provisions": descendants(gid), "page_start": None, "page_end": None})
    return hits


def run(version: str, split: str, retrieval_only: bool, final: bool, limit: int | None) -> dict:
    cfg = load_yaml(CONFIG_DIR / "versions" / f"{version}.yaml")
    questions = load_questions(split, final)[:limit]
    mode = cfg["retrieval"]["mode"]
    budget = cfg["evidence_budget"]
    distractor_k = load_yaml(CONFIG_DIR / "versions" / "v2.yaml")["retrieval"]["k"]

    from statnav.embed.jina import JinaClient
    from statnav.index.db import connect
    from statnav.retrieve.dense import knn
    from statnav.retrieve.route import as_dicts, retrieve

    jina = JinaClient.from_config()
    conn = connect()
    llm = None
    if not retrieval_only:
        from statnav.llm.client import ChatClient
        llm = ChatClient.for_role(answer_role(cfg))
    agent = None
    if cfg.get("agent"):
        from statnav.agent.graph import Agent
        from statnav.llm.client import ChatClient
        # the scope check runs in retrieval-only mode too: it decides what gets retrieved
        classify = ChatClient.for_role("classify") if cfg["agent"].get("scope_check") else None
        checker = ChatClient.for_role("verify") if cfg["agent"].get("verify") else None
        agent = Agent(conn, jina, cfg, llm, classify, checker)

    prev_path = RESULTS_DIR / version / split.replace(":", "_") / "outputs.jsonl"
    prev_latency = ({r["id"]: r.get("latency_s") for r in read_jsonl(prev_path)}
                    if prev_path.exists() else {})
    records, incomplete = [], None
    for n, q in enumerate(questions, 1):
        rec: dict = {"id": q["id"], "type": q["type"], "question": q["question"], "metrics": {}}
        jina_before = jina.usage.tokens
        if mode == "oracle" and not q["should_refuse"]:
            hits = oracle_hits(q, budget)
        elif mode == "oracle":
            # refusals in oracle mode still see realistic (v2) passages as distractors
            found = knn(conn, jina.embed_query(q["question"]), "v2", distractor_k)
            hits = as_dicts(found)
        elif agent is not None:
            from statnav.llm.client import QuotaExhausted
            try:
                res = agent.run(q["question"], generate=llm is not None)
            except QuotaExhausted as exc:
                incomplete = str(exc)
                log.warning("quota_exhausted", at=n, of=len(questions), detail=str(exc))
                break
            hits = res.hits
            rec.update(route=res.route, in_scope=res.in_scope, scope_reason=res.scope_reason,
                       classify_tokens=res.classify_tokens, definitions=res.definitions)
            rec["metrics"]["scope_refused"] = float(not res.in_scope)
        else:
            hits = as_dicts(retrieve(conn, jina, q["question"], cfg))
        rec["retrieved"] = [{k: h[k] for k in ("chunk_id", "provisions") if k in h}
                            for h in hits]
        if mode != "oracle":
            rec["metrics"].update(retrieval_metrics(q, [h["provisions"] for h in hits]))
        rec["jina_tokens"] = jina.usage.tokens - jina_before

        if llm is not None and agent is not None:
            evidence = res.evidence
            rec["evidence_tokens"] = sum(h["tokens"] for h in evidence)
            reply = res.reply
            out = res.out
            if reply is not None:
                rec["latency_s"] = (prev_latency.get(q["id"]) if reply.cached
                                    else round(reply.latency_s, 2))
            # total LLM cost: the 120b answer(s) plus the 20b scope check and checker
            rec["llm_tokens"] = res.answer_tokens + res.classify_tokens + res.verify_tokens
            if res.verified is not None or res.attempts > 1:
                rec.update(verified=res.verified, attempts=res.attempts,
                           unsupported=res.unsupported, verify_tokens=res.verify_tokens)
            cited = parse_citations(out, evidence, inline_cites(cfg))
            rec["answer"] = out.get("answer")
            rec["refused"] = bool(out.get("refused"))
            rec["cited"] = [h["chunk_id"] for h in cited]
            rec["metrics"].update(generation_metrics(q, out, cited))
        elif llm is not None:
            evidence = pack(hits, budget)
            rec["evidence_tokens"] = sum(h["tokens"] for h in evidence)
            from statnav.llm.client import LLMError, QuotaExhausted
            try:
                reply = llm.chat([{"role": "system", "content": SYSTEM_PROMPT},
                                  {"role": "user", "content": user_prompt(q["question"],
                                                                          evidence)}],
                                 json_mode=True)
                # provider latency only (rate-limit waits excluded); a cached reply keeps the
                # latency measured when it was first generated, if an earlier run recorded it
                rec["latency_s"] = (prev_latency.get(q["id"]) if reply.cached
                                    else round(reply.latency_s, 2))
                rec["llm_tokens"] = reply.usage.get("total_tokens")
                try:
                    out = reply.json()
                except (LLMError, ValueError):
                    out = {"answer": reply.text, "citations": [], "refused": False}
            except QuotaExhausted as exc:
                incomplete = str(exc)
                log.warning("quota_exhausted", at=n, of=len(questions), detail=str(exc))
                break
            except LLMError as exc:
                out = {"answer": f"[error: {exc}]", "citations": [], "refused": False}
            cited = parse_citations(out, evidence)
            rec["answer"] = out.get("answer")
            rec["refused"] = bool(out.get("refused"))
            rec["cited"] = [h["chunk_id"] for h in cited]
            rec["metrics"].update(generation_metrics(q, out, cited))
        records.append(rec)
        if n % 10 == 0:
            log.info("progress", done=n, total=len(questions))

    metrics = aggregate(records)
    metrics["incomplete"] = incomplete
    out_dir = RESULTS_DIR / version / split.replace(":", "_")
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "metrics.json").write_text(json.dumps(metrics, indent=2), encoding="utf-8")
    write_jsonl(out_dir / "outputs.jsonl", records)
    meta = {"version": version, "split": split, "config": cfg, "n_questions": len(questions),
            "n_completed": len(records), "retrieval_only": retrieval_only,
            "answer_model": llm.model if llm else None, "timestamp":
                datetime.now(UTC).isoformat(timespec="seconds"),
            "jina_tokens_billed": jina.usage.tokens, "incomplete": incomplete}
    (out_dir / "run_meta.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
    conn.close()
    return metrics


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--version", required=True)
    ap.add_argument("--split", default="dev")
    ap.add_argument("--retrieval-only", action="store_true")
    ap.add_argument("--final", action="store_true", help="required to run the test split")
    ap.add_argument("--limit", type=int)
    a = ap.parse_args()
    m = run(a.version, a.split, a.retrieval_only, a.final, a.limit)
    print(json.dumps({k: v for k, v in m.items() if k != "by_type"}, indent=2))
    print(json.dumps(m.get("by_type", {}), indent=2))


if __name__ == "__main__":
    main()
