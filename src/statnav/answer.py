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

# v9: the same grounding rules, but the answer is written for someone who has never read a
# statute: Markdown sections, a worked example, inline [Cn] markers and follow-up questions.
EXPLAINED_PROMPT = """You explain India's Income-tax Act, 2025 (as amended by the Finance Act, \
2026) to people who are not tax experts.
Grounding rules:
- Use ONLY the numbered context passages. Do not use outside knowledge, and never invent a \
rate, limit, threshold, date or condition.
- Quote numbers, rates, thresholds, periods and dates exactly as the passages state them.
- Read limits literally: "up to Rs. X in aggregate" for several people or payments is one \
combined limit for all of them, not a limit for each.
- End every sentence or bullet that states something from a passage with its label in \
square brackets and no spaces, e.g. [C1] or [C1][C3], including in the "In short" and "What \
this means for you" sections. Also list every passage you used in "citations".
- Set "refused": true, with a one-sentence reason in "answer" and no sections, when the \
question is about something the Act does not contain (Income-tax Rules, forms, circulars, \
notifications, case law, filing procedures, other laws), asks for a personal tax computation \
or advice, or the passages do not contain the answer.
Writing rules:
- Plain English: short sentences, everyday words, speak to the reader as "you". Turn legal \
phrasing ("the assessee shall be allowed a deduction") into plain words ("you can deduct"). \
Name the section once (e.g. "section 126").
- Write "answer" in Markdown with these "### " sections, in this order:
### In short
One or two sentences that answer exactly what was asked (yes/no, the number, or the meaning).
### What this means for you
Two to four sentences explaining it in everyday terms.
{route_block}
### Watch out
Bullets on exceptions, exclusions, provisos and restrictions that are easy to miss (for \
example "not allowed if ..."), only as the passages state them. Leave this section out if the \
passages contain none.
### Example
One simple case of exactly what was asked, in two to four bullets: one person, one payment or \
income, and nothing else added (no second payment, no other deduction, no "if you also ..." \
bullet). Start with "Suppose" \
and use made-up amounts, but take every rate, limit or threshold from a passage and cite it. \
It must agree with every condition and restriction above. Show the arithmetic and end with \
the result. If the passages give no figure to calculate with, describe a short real-life \
situation instead.
### Key terms
One to three bullets, "**term**: meaning [Cn]", only for terms a passage defines (it says \
"X" means ... or "X" includes ...), in that passage's words, other than the term the question \
itself asks about. Never write "as defined elsewhere" \
and never add an age, amount or condition from memory. Leave this section out if no passage \
defines a term you used.
- "follow_ups": two or three short questions the reader might ask next that the Act itself \
answers (no questions about forms, portals or personal advice). Put them only in \
"follow_ups", never as a section of "answer".
Return only JSON: {{"answer": "...", "citations": ["C1"], "follow_ups": ["..."], \
"refused": false}}"""

ROUTE_BLOCKS = {
    "general": """### Conditions to check
Bullets: who qualifies, limits and amounts, how or when the payment or act must happen, and \
any time limits, each as the passages state them.""",
    "table": """### The numbers
Bullets with every field of the table row you rely on (for example the rate, the threshold \
limit, who pays or deducts, and when), each quoted exactly as the row states it.""",
    "amendment": """### What changed
Bullets: the type of change in the endnote's word (substituted, inserted or omitted), the \
wording before (quote it), the wording now (quote it), the amending Act and the date it \
applies from, as the endnote states them. A passage's "wording before" is the old text \
and "wording now" is the current text.""",
    "definition": """### What it includes and excludes
Bullets: what the term covers and, separately, what it does not cover, as the defining \
provision states them.""",
}


def system_prompt(style: str = "basic", route: str | None = None) -> str:
    """The generator's system prompt: the measured one-paragraph prompt (v0-v8) or v9's."""
    if style == "basic":
        return SYSTEM_PROMPT
    if style != "explained":
        raise ValueError(f"unknown prompt style {style!r}")
    block = ROUTE_BLOCKS.get(route or "general", ROUTE_BLOCKS["general"])
    return EXPLAINED_PROMPT.format(route_block=block)


def answer_role(cfg: dict) -> str:
    """The model role (configs/models.yaml) a version answers with."""
    return (cfg.get("generation") or {}).get("role", "answer")


def inline_cites(cfg: dict) -> bool:
    """Whether a version's answers cite with [Cn] markers in the text (v9's explained style)."""
    return (cfg.get("generation") or {}).get("prompt") == "explained"


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


INLINE_CITE = re.compile(r"\[\s*C\s*(\d+)\s*\]")  # the model sometimes writes "[ C1 ]"
_SECTION = re.compile(r"^(?=#{1,6}\s)", re.M)
_TERM = re.compile(r"^\s*[-*]\s*\*\*(.+?)\*\*")
_FOLLOW_UPS = re.compile(r"#{1,6}\s*(?:follow\W?ups?|ask next)\b", re.I)
_KEY_TERMS = re.compile(r"#{1,6}\s*key terms\b", re.I)


def _plain(s: str) -> str:
    """Lower case with the Act's and the model's hyphens, quotes and spaces made ASCII."""
    s = re.sub("[‐-―−]", "-", s.lower())
    s = re.sub("[“”„\"‘’']", '"', s)
    return re.sub(r"\s+", " ", s)


def defined_in(term: str, evidence: list[dict]) -> bool:
    """Whether a passage defines `term` ('"term" means ...' / '"term" includes ...')."""
    t = re.escape(_plain(term).strip(' ":'))
    pat = re.compile(rf'"{t}"[^.;]{{0,40}}?\b(?:means|includes|shall mean)\b')
    return any(pat.search(_plain(h["text"])) for h in evidence)


def tidy(out: dict, evidence: list[dict]) -> dict:
    """Hold an explained answer to the rules the prompt cannot enforce on its own.

    A "Key terms" bullet stays only if a passage defines that term: given room, the model
    explains words from memory (an age for "senior citizen") or invents meanings for clause
    numbers. A "Follow-ups" section written into the text moves to "follow_ups"."""
    answer = str(out.get("answer") or "")
    if out.get("refused") or not answer:
        return out
    kept, extra = [], []
    for sec in _SECTION.split(answer):
        if _FOLLOW_UPS.match(sec):
            extra = [m.group(1).strip() for m in re.finditer(r"^\s*(?:[-*]|\d+[.)])\s+(.+)$",
                                                              sec, re.M)]
            continue
        if _KEY_TERMS.match(sec):
            head, *lines = sec.rstrip("\n").split("\n")
            good = [ln for ln in lines if (m := _TERM.match(ln)) and defined_in(m.group(1),
                                                                                 evidence)]
            if good:
                kept.append("\n".join([head, *good]) + "\n")
            continue
        kept.append(sec)
    out = {**out, "answer": "".join(kept).rstrip()}
    if extra and not out.get("follow_ups"):
        out["follow_ups"] = extra
    return out


def parse_citations(out: dict, evidence: list[dict], inline: bool = False) -> list[dict]:
    """Map the model's "C1"/"[C2]" labels back to the evidence passages they refer to.

    `inline` (v9's explained answers) also counts the [Cn] markers written in the answer text,
    in order of first appearance after the listed ones, so a marker the model forgot to list
    still backs the answer."""
    labels = [str(c).strip("[]C ") for c in out.get("citations") or []]
    if inline:
        labels += INLINE_CITE.findall(str(out.get("answer") or ""))
    cited, seen = [], set()
    for k in labels:
        if k.isdigit() and 1 <= int(k) <= len(evidence) and (not inline or k not in seen):
            seen.add(k)
            cited.append(evidence[int(k) - 1])
    return cited


def follow_ups(out: dict) -> list[str]:
    """Up to three suggested next questions from an explained answer (strings only)."""
    raw = out.get("follow_ups")
    if not isinstance(raw, list):
        return []
    return [q.strip() for q in raw if isinstance(q, str) and q.strip()][:3]


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
             on_text: Callable[[str], None] | None = None, style: str = "basic",
             route: str | None = None) -> tuple[dict, Reply]:
    """One answer call: the parsed {"answer", "citations", "refused"} and the raw reply.

    `style` / `route` pick the system prompt (`system_prompt`).

    `retry` = (the previous reply's text, the claims the v7 checker found unsupported) makes it
    a second turn of the same conversation. `on_text` (the chat UI only, never the evals)
    streams the answer: it is called with each new piece of the "answer" text. Streaming drops
    JSON mode, which Groq cannot stream, so the reply can differ from the measured one; if the
    stream fails before any text arrives, the measured JSON-mode call is used instead.
    Raises `QuotaExhausted` / `LLMError` from the client; callers decide how to surface them. A
    reply that is not valid JSON is kept as a plain, uncited answer.
    """
    from statnav.llm.client import LLMError

    messages = [{"role": "system", "content": system_prompt(style, route)},
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
    if style == "explained":
        out = tidy(out, evidence)
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
    follow_ups: list[str] = field(default_factory=list)  # v9: suggested next questions

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
        self.gen = self.cfg.get("generation") or {}
        self.jina = JinaClient.from_config()
        self.conn = connect(autocommit=True)  # read-only and long-lived; see db.connect
        self.llm = ChatClient.for_role(answer_role(self.cfg))
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
            out, reply = generate(self.llm, question, evidence,
                                  style=self.gen.get("prompt", "basic"))
        except (QuotaExhausted, LLMError) as exc:
            res.error = str(exc)
            res.answer = f"[{type(exc).__name__}: {exc}]"
            return res
        return _fill(res, out, reply, inline_cites(self.cfg))

    def _ask_agent(self, question: str, k: int | None) -> Answer:
        from statnav.llm.client import LLMError, QuotaExhausted

        try:
            r = self.agent.run(question, k)
        except (QuotaExhausted, LLMError) as exc:
            return failed(question, exc)
        return from_agent(r, inline_cites(self.cfg))


def failed(question: str, exc: Exception) -> Answer:
    """A provider failure, shaped so it can never be read as an answer."""
    return Answer(question=question, answer=f"[{type(exc).__name__}: {exc}]", refused=False,
                  error=str(exc))


def from_agent(r: AgentResult, inline: bool = False) -> Answer:
    """An agent run's result as an `Answer` (the chat, the API and the MCP server use this).

    `inline`: the answer is v9's explained style, whose [Cn] markers in the text also cite."""
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
    res = _fill(res, r.out, r.reply, inline)
    res.llm_tokens = r.answer_tokens + r.verify_tokens  # incl. a v7 retry and its checker
    res.verified, res.unsupported = r.verified, r.unsupported
    return res


def _fill(res: Answer, out: dict, reply: Reply, inline: bool = False) -> Answer:
    res.cached = reply.cached
    res.latency_s = round(reply.latency_s, 2)
    res.llm_tokens = reply.usage.get("total_tokens") or 0
    res.answer = out.get("answer") or ""
    res.refused = bool(out.get("refused"))
    res.cited = parse_citations(out, res.evidence, inline)
    res.follow_ups = [] if res.refused else follow_ups(out)
    return res
