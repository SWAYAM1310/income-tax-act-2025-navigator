"""Answer one question about the Act from retrieved passages.

This is the generation path shared by the eval harness (`evals/run.py`) and the interactive
chat (`statnav.chat`), so what the chat prints is what the ladder measures. Keep the prompt and
the evidence packing here; eval-only concerns (oracle context, gold metrics) stay in evals.

    from statnav.answer import Answerer
    with Answerer.for_version("v2") as bot:
        print(bot.ask("how is agricultural income defined").answer)
"""

from __future__ import annotations

from dataclasses import dataclass, field

from statnav.config import CONFIG_DIR, load_yaml

SYSTEM_PROMPT = """You answer questions about India's Income-tax Act, 2025 (as amended by the \
Finance Act, 2026).
Rules:
- Use ONLY the numbered context passages. Do not use outside knowledge.
- Quote key words, numbers, rates, thresholds and periods exactly as the passages state them.
- Name the provision you rely on (e.g. "section 2(5)") and list the passages you used, as \
"C1", "C2", ..., in "citations".
- Set "refused": true, with a one-sentence reason in "answer", when the question is about \
something the Act does not contain (Income-tax Rules, forms, circulars, notifications, case \
law, filing procedures, other laws), asks for a personal tax computation or advice, or the \
passages do not contain the answer.
Return only JSON: {"answer": "...", "citations": ["C1"], "refused": false}"""


def pack(hits: list[dict], budget: int) -> list[dict]:
    """Greedily keep the highest-ranked hits that fit the evidence budget."""
    out, used = [], 0
    for h in hits:
        if used + h["tokens"] > budget:
            continue
        out.append(h)
        used += h["tokens"]
    return out


def user_prompt(question: str, evidence: list[dict]) -> str:
    blocks = []
    for n, h in enumerate(evidence, 1):
        pages = f" (pp. {h['page_start']}-{h['page_end']})" if h.get("page_start") else ""
        blocks.append(f"[C{n}]{pages}\n{h['text']}")
    return f"Question: {question}\n\nContext passages:\n\n" + "\n\n".join(blocks)


def parse_citations(out: dict, evidence: list[dict]) -> list[dict]:
    """Map the model's "C1"/"[C2]" labels back to the evidence passages they refer to."""
    cited = []
    for c in out.get("citations") or []:
        k = str(c).strip("[]C ")
        if k.isdigit() and 1 <= int(k) <= len(evidence):
            cited.append(evidence[int(k) - 1])
    return cited


@dataclass
class Answer:
    question: str
    answer: str
    refused: bool
    cited: list[dict] = field(default_factory=list)
    evidence: list[dict] = field(default_factory=list)
    evidence_tokens: int = 0
    llm_tokens: int = 0
    latency_s: float = 0.0
    cached: bool = False
    error: str | None = None

    @property
    def provisions(self) -> list[str]:
        """Provision ids backing the answer, in citation order, de-duplicated."""
        seen: dict[str, None] = {}
        for h in self.cited:
            for p in h.get("provisions") or []:
                seen.setdefault(p, None)
        return list(seen)


class Answerer:
    """Retrieve for a question and generate a cited answer, using one ladder version."""

    def __init__(self, version: str = "v2") -> None:
        from statnav.embed.jina import JinaClient
        from statnav.index.db import connect
        from statnav.llm.client import ChatClient

        self.version = version
        self.cfg = load_yaml(CONFIG_DIR / "versions" / f"{version}.yaml")
        if self.cfg["retrieval"]["mode"] == "oracle":
            raise ValueError("the oracle version needs gold provisions; it has no chat mode")
        self.chunks = self.cfg["chunks"]
        self.k = self.cfg["retrieval"]["k"]
        self.budget = self.cfg["evidence_budget"]
        self.jina = JinaClient.from_config()
        self.conn = connect()
        self.llm = ChatClient.for_role("answer")

    @classmethod
    def for_version(cls, version: str = "v2") -> Answerer:
        return cls(version)

    def __enter__(self) -> Answerer:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def close(self) -> None:
        self.conn.close()

    def retrieve(self, question: str, k: int | None = None) -> list[dict]:
        from statnav.retrieve.dense import knn

        found = knn(self.conn, self.jina.embed_query(question), self.chunks, k or self.k)
        return [{"chunk_id": h.chunk_id, "text": h.text, "tokens": h.tokens,
                 "provisions": h.meta.get("provisions", []), "page_start": h.page_start,
                 "page_end": h.page_end, "score": round(h.score, 4)} for h in found]

    def ask(self, question: str, k: int | None = None) -> Answer:
        from statnav.llm.client import LLMError, QuotaExhausted

        evidence = pack(self.retrieve(question, k), self.budget)
        res = Answer(question=question, answer="", refused=False, evidence=evidence,
                     evidence_tokens=sum(h["tokens"] for h in evidence))
        if not evidence:
            res.answer = "Nothing was retrieved for that question."
            res.refused = True
            return res
        try:
            reply = self.llm.chat(
                [{"role": "system", "content": SYSTEM_PROMPT},
                 {"role": "user", "content": user_prompt(question, evidence)}],
                json_mode=True,
            )
        except (QuotaExhausted, LLMError) as exc:
            res.error = str(exc)
            res.answer = f"[{type(exc).__name__}: {exc}]"
            return res
        res.cached = reply.cached
        res.latency_s = round(reply.latency_s, 2)
        res.llm_tokens = reply.usage.get("total_tokens") or 0
        try:
            out = reply.json()
        except (LLMError, ValueError):
            out = {"answer": reply.text, "citations": [], "refused": False}
        res.answer = out.get("answer") or ""
        res.refused = bool(out.get("refused"))
        res.cited = parse_citations(out, evidence)
        return res
