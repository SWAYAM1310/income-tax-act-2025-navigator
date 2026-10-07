"""Answer one question about the Act from retrieved passages.

This is the generation path shared by the eval harness (`evals/run.py`) and the interactive
chat (`statnav.chat`), so what the chat prints is what the ladder measures. Keep the prompt and
the evidence packing here; eval-only concerns (oracle context, gold metrics) stay in evals.

    from statnav.answer import Answerer
    with Answerer.for_version("v2") as bot:
        print(bot.ask("how is agricultural income defined").answer)
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from statnav.config import CONFIG_DIR, load_yaml

if TYPE_CHECKING:
    from statnav.agent.graph import AgentResult
    from statnav.llm.client import ChatClient, Reply

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


def passages(evidence: list[dict]) -> str:
    """The numbered "[C1] ..." blocks, exactly as the generator (and the v7 checker) sees them."""
    blocks = []
    for n, h in enumerate(evidence, 1):
        pages = f" (pp. {h['page_start']}-{h['page_end']})" if h.get("page_start") else ""
        blocks.append(f"[C{n}]{pages}\n{h['text']}")
    return "\n\n".join(blocks)


def user_prompt(question: str, evidence: list[dict]) -> str:
    return f"Question: {question}\n\nContext passages:\n\n" + passages(evidence)


RETRY_PROMPT = """A reviewer checked your answer against the passages and found statements \
that no passage supports:
{unsupported}
Answer again. State only what the passages say, and cite every passage you rely on. Return \
only JSON in the same format."""


def parse_citations(out: dict, evidence: list[dict]) -> list[dict]:
    """Map the model's "C1"/"[C2]" labels back to the evidence passages they refer to."""
    cited = []
    for c in out.get("citations") or []:
        k = str(c).strip("[]C ")
        if k.isdigit() and 1 <= int(k) <= len(evidence):
            cited.append(evidence[int(k) - 1])
    return cited


class AnswerTextStream:
    """Pull the "answer" string out of a JSON reply while it is still arriving.

    `feed(delta)` returns the answer characters that `delta` completed, decoded (escapes such as
    `\"`, `\n` and `₹` are resolved even when split across deltas). Everything outside
    the "answer" value (other keys, a code fence) is ignored.
    """

    _START = re.compile(r'"answer"\s*:\s*"')
    _ESCAPES = {'"': '"', "\\": "\\", "/": "/", "b": "\b", "f": "\f", "n": "\n", "r": "\r",
                "t": "\t"}

    def __init__(self) -> None:
        self.buf = ""
        self.pos: int | None = None  # where the undecoded answer text starts in `buf`
        self.done = False
        self.text = ""

    def feed(self, delta: str) -> str:
        if self.done:
            return ""
        self.buf += delta
        if self.pos is None:
            m = self._START.search(self.buf)
            if not m:
                return ""
            self.pos = m.end()
        out, i, buf = [], self.pos, self.buf
        while i < len(buf):
            c = buf[i]
            if c == '"':
                self.done = True
                i += 1
                break
            if c != "\\":
                out.append(c)
                i += 1
                continue
            if i + 1 >= len(buf):
                break  # the escape's second half has not arrived yet
            e = buf[i + 1]
            if e == "u":
                if i + 6 > len(buf):
                    break
                try:
                    out.append(chr(int(buf[i + 2:i + 6], 16)))
                except ValueError:
                    out.append(buf[i:i + 6])
                i += 6
            else:
                out.append(self._ESCAPES.get(e, e))
                i += 2
        self.pos = i
        piece = "".join(out)
        self.text += piece
        return piece


def generate(llm: ChatClient, question: str, evidence: list[dict],
             retry: tuple[str, list[str]] | None = None,
             on_text: Callable[[str], None] | None = None) -> tuple[dict, Reply]:
    """One answer call: the parsed {"answer", "citations", "refused"} and the raw reply.

    `retry` = (the previous reply's text, the claims the v7 checker found unsupported) makes it
    a second turn of the same conversation. `on_text` (the chat UI only, never the evals)
    streams the answer: it is called with each new piece of the "answer" text. Streaming drops
    JSON mode, which Groq cannot stream, so the reply can differ from the measured one; if the
    stream fails before any text arrives, the measured JSON-mode call is used instead.
    Raises `QuotaExhausted` / `LLMError` from the client; callers decide how to surface them. A
    reply that is not valid JSON is kept as a plain, uncited answer.
    """
    from statnav.llm.client import LLMError

    messages = [{"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt(question, evidence)}]
    if retry:
        previous, unsupported = retry
        messages += [{"role": "assistant", "content": previous},
                     {"role": "user", "content": RETRY_PROMPT.format(
                         unsupported="\n".join(f"- {c}" for c in unsupported))}]
    reply = None
    if on_text is not None:
        parser = AnswerTextStream()

        def forward(delta: str) -> None:
            piece = parser.feed(delta)
            if piece:
                on_text(piece)
        try:
            reply = llm.chat_stream(messages, forward)
        except LLMError:
            if parser.text:
                raise
    if reply is None:
        reply = llm.chat(messages, json_mode=True)
    try:
        out = reply.json()
    except (LLMError, ValueError):
        out = {"answer": reply.text, "citations": [], "refused": False}
    return out, reply


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
    route: str | None = None  # agent versions only: amendment | definition | table | general
    classify_tokens: int = 0  # agent versions only: gpt-oss-20b scope-check tokens
    verified: bool | None = None  # v7: every claim supported (None: not checked)
    unsupported: list[str] = field(default_factory=list)  # v7: claims no passage supports

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
        self.conn = connect(autocommit=True)  # read-only and long-lived; see db.connect
        self.llm = ChatClient.for_role("answer")
        self.agent = None
        if self.cfg.get("agent"):
            from statnav.agent.graph import Agent

            classify = (ChatClient.for_role("classify")
                        if self.cfg["agent"].get("scope_check") else None)
            checker = ChatClient.for_role("verify") if self.cfg["agent"].get("verify") else None
            self.agent = Agent(self.conn, self.jina, self.cfg, self.llm, classify, checker)

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
        from statnav.retrieve.route import as_dicts, retrieve

        return as_dicts(retrieve(self.conn, self.jina, question, self.cfg, k))

    def ask(self, question: str, k: int | None = None) -> Answer:
        from statnav.llm.client import LLMError, QuotaExhausted

        if self.agent is not None:
            return self._ask_agent(question, k)
        evidence = pack(self.retrieve(question, k), self.budget)
        res = Answer(question=question, answer="", refused=False, evidence=evidence,
                     evidence_tokens=sum(h["tokens"] for h in evidence))
        if not evidence:
            res.answer = "Nothing was retrieved for that question."
            res.refused = True
            return res
        try:
            out, reply = generate(self.llm, question, evidence)
        except (QuotaExhausted, LLMError) as exc:
            res.error = str(exc)
            res.answer = f"[{type(exc).__name__}: {exc}]"
            return res
        return _fill(res, out, reply)

    def _ask_agent(self, question: str, k: int | None) -> Answer:
        from statnav.llm.client import LLMError, QuotaExhausted

        try:
            r = self.agent.run(question, k)
        except (QuotaExhausted, LLMError) as exc:
            return failed(question, exc)
        return from_agent(r)


def failed(question: str, exc: Exception) -> Answer:
    """A provider failure, shaped so it can never be read as an answer."""
    return Answer(question=question, answer=f"[{type(exc).__name__}: {exc}]", refused=False,
                  error=str(exc))


def from_agent(r: AgentResult) -> Answer:
    """An agent run's result as an `Answer` (the chat, the API and the MCP server use this)."""
    res = Answer(question=r.question, answer="", refused=False, route=r.route,
                 classify_tokens=r.classify_tokens, evidence=r.evidence,
                 evidence_tokens=sum(h["tokens"] for h in r.evidence))
    if r.error:
        res.error = r.error
        res.answer = r.out["answer"]
        return res
    if r.reply is None:  # refused before generation
        res.answer = r.out["answer"]
        res.refused = bool(r.out["refused"])
        return res
    res = _fill(res, r.out, r.reply)
    res.llm_tokens = r.answer_tokens + r.verify_tokens  # incl. a v7 retry and its checker
    res.verified, res.unsupported = r.verified, r.unsupported
    return res


def _fill(res: Answer, out: dict, reply: Reply) -> Answer:
    res.cached = reply.cached
    res.latency_s = round(reply.latency_s, 2)
    res.llm_tokens = reply.usage.get("total_tokens") or 0
    res.answer = out.get("answer") or ""
    res.refused = bool(out.get("refused"))
    res.cited = parse_citations(out, res.evidence)
    return res
