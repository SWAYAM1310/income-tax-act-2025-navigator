"""Deterministic metrics (no LLM judge). Each function takes one question's record."""

from __future__ import annotations

import re
import statistics

from evals.common import artefacts, contains, descendants, norm


def gold_targets(q: dict) -> list[str]:
    """Ids that retrieval must surface: table rows when given, else the gold provisions."""
    if q["type"] == "multi_hop":
        return q["gold_provisions"] + q["gold_table_rows"]
    return q["gold_table_rows"] or q["gold_provisions"]


def _expand(gid: str) -> set[str]:
    """A provision counts as found if any chunk covers it or one of its descendants."""
    if gid in artefacts()["rows"]:
        return {gid}
    return set(descendants(gid))


def covered(chunk_provisions: list[str], gid: str) -> bool:
    return bool(_expand(gid) & set(chunk_provisions))


# -- retrieval -----------------------------------------------------------------------------
def retrieval_metrics(q: dict, ranked: list[list[str]]) -> dict:
    """ranked: the covered-provision lists of the retrieved chunks, best first."""
    gold = gold_targets(q)
    if not gold:
        return {}
    out = {}
    for k in (1, 5, 10):
        top = [p for chunk in ranked[:k] for p in chunk]
        found = [g for g in gold if covered(top, g)]
        out[f"recall@{k}"] = len(found) / len(gold)
        out[f"hit@{k}"] = float(bool(found))
    rr = 0.0
    for rank, chunk in enumerate(ranked, 1):
        if any(covered(chunk, g) for g in gold):
            rr = 1 / rank
            break
    out["mrr"] = rr
    return out


# -- generation ----------------------------------------------------------------------------
REFUSAL_HINT = re.compile(r"\b(cannot|can't|unable to|not (?:covered|contained|in the "
                          r"(?:act|provided))|outside (?:the )?scope|does not (?:contain|"
                          r"address|cover))\b", re.I)
NUM_TOKEN = re.compile(r"\d[\d,]*(?:\.\d+)?\s?%?")
TYPE_STEMS = {"substituted": ("substitut", "replac"), "inserted": ("insert", "added"),
              "omitted": ("omit", "delet", "removed"), "renumbered": ("renumber",)}


def token_f1(pred: str, gold: str) -> float:
    p, g = norm(pred).split(), norm(gold).split()
    if not p or not g:
        return 0.0
    common = 0
    pool = list(g)
    for t in p:
        if t in pool:
            pool.remove(t)
            common += 1
    if not common:
        return 0.0
    prec, rec = common / len(p), common / len(g)
    return 2 * prec * rec / (prec + rec)


_STOP_WORDS = ("a an the of to in on for by or and is are be been being as at from with that "
               "which this such any its it his her their under shall may")
_NUMBER_WORDS = ("one two three four five six seven eight nine ten eleven twelve fifteen twenty "
                 "thirty forty fifty sixty seventy eighty ninety hundred thousand lakh crore")
STOPWORDS = frozenset(_STOP_WORDS.split())
_NUMERALS = frozenset(_NUMBER_WORDS.split())
FACT_COVERAGE = 0.8


def _stem(t: str) -> str:
    for suf in ("ing", "ed", "es", "s", "ly"):
        if len(t) > len(suf) + 3 and t.endswith(suf):
            return t[: -len(suf)]
    return t


def _content(text: str) -> list[str]:
    toks = (t.strip(".") for t in re.findall(r"[\w%.]+", norm(text)))
    return [_stem(t) for t in toks if t and t not in STOPWORDS]


def fact_match(answer: str, fact: str) -> bool:
    """Exact (normalised) containment, or soft: >= 80% of the fact's content words appear in
    the answer and every number in the fact appears exactly. Tolerates paraphrase such as
    'up to thirty days' vs 'not exceeding thirty days' without letting wrong numbers pass."""
    if contains(answer, fact):
        return True
    words = _content(fact)
    if not words:
        return False
    have = set(_content(answer))
    is_num = [any(ch.isdigit() for ch in w) or w in _NUMERALS for w in words]
    if any(n and w not in have for w, n in zip(words, is_num, strict=True)):
        return False
    return sum(w in have for w in words) / len(words) >= FACT_COVERAGE


def generation_metrics(q: dict, out: dict, cited_chunks: list[dict]) -> dict:
    """out: {"answer", "refused"}; cited_chunks: [{"provisions": [...], "text": ...}]."""
    answer = out.get("answer") or ""
    refused = bool(out.get("refused"))
    m = {"refused": float(refused), "should_refuse": float(q["should_refuse"])}
    if q["should_refuse"]:
        return m
    facts = q["gold_facts"]
    if facts:
        exact = [contains(answer, f) for f in facts]
        soft = [fact_match(answer, f) for f in facts]
        m["fact_recall"] = sum(soft) / len(facts)
        m["all_facts"] = float(all(soft))
        m["fact_recall_exact"] = sum(exact) / len(facts)
        m["all_facts_exact"] = float(all(exact))
    gold = gold_targets(q)
    if cited_chunks:
        good = [c for c in cited_chunks if any(covered(c["provisions"], g) for g in gold)]
        m["citation_precision"] = len(good) / len(cited_chunks)
    else:
        m["citation_precision"] = 0.0
    cited_ids = [p for c in cited_chunks for p in c["provisions"]]
    m["citation_recall"] = (sum(covered(cited_ids, g) for g in gold) / len(gold)) if gold else 0.0
    # grounding: every number in the answer appears in some cited passage
    nums = {n.strip() for n in NUM_TOKEN.findall(answer) if len(n.strip()) > 1}
    if nums:
        cited_text = " ".join(c["text"] for c in cited_chunks)
        m["grounded_numbers"] = sum(contains(cited_text, n) for n in nums) / len(nums)
    if q["type"] == "table":
        m["table_exact"] = m.get("all_facts_exact", 0.0)  # tables stay strict
    if q["type"] == "amendment" and q.get("gold_amendment"):
        ga = q["gold_amendment"]
        m["amendment_type"] = float(any(s in answer.lower() for s in TYPE_STEMS[ga["type"]]))
        if ga.get("prior_text"):
            m["prior_text_f1"] = token_f1(answer, ga["prior_text"])
    return m


# -- aggregation ---------------------------------------------------------------------------
def mean(xs: list[float]) -> float | None:
    return round(sum(xs) / len(xs), 4) if xs else None


def pct(xs: list[float], p: float) -> float | None:
    if not xs:
        return None
    s = sorted(xs)
    return round(s[min(len(s) - 1, int(round(p * (len(s) - 1))))], 3)


def aggregate(records: list[dict]) -> dict:
    out: dict = {"n": len(records)}
    keys = sorted({k for r in records for k in r.get("metrics", {})})
    for k in keys:
        if k in ("refused", "should_refuse"):
            continue
        out[k] = mean([r["metrics"][k] for r in records if k in r["metrics"]])
    gen = [r for r in records if "refused" in r.get("metrics", {})]
    if gen:
        tp = sum(1 for r in gen if r["metrics"]["refused"] and r["metrics"]["should_refuse"])
        fp = sum(1 for r in gen if r["metrics"]["refused"] and not r["metrics"]["should_refuse"])
        fn = sum(1 for r in gen if not r["metrics"]["refused"] and r["metrics"]["should_refuse"])
        out["refusal_precision"] = round(tp / (tp + fp), 4) if tp + fp else None
        out["refusal_recall"] = round(tp / (tp + fn), 4) if tp + fn else None
    by_type: dict = {}
    for t in sorted({r["type"] for r in records}):
        rs = [r for r in records if r["type"] == t]
        by_type[t] = {"n": len(rs)}
        for k in keys:
            vals = [r["metrics"][k] for r in rs if k in r["metrics"]]
            if vals and k not in ("refused", "should_refuse"):
                by_type[t][k] = mean(vals)
    out["by_type"] = by_type
    lat = [r["latency_s"] for r in records if r.get("latency_s") is not None]
    if lat:
        out["latency_p50_s"], out["latency_p95_s"] = pct(lat, 0.5), pct(lat, 0.95)
    for k in ("llm_tokens", "jina_tokens", "evidence_tokens"):
        vals = [r[k] for r in records if r.get(k) is not None]
        if vals:
            out[f"{k}_mean"] = round(statistics.mean(vals), 1)
    return out
