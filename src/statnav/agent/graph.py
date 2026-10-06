"""v6/v7: a LangGraph agent over v5's retrieval.

    classify --(out of scope)--> refuse --> END
        \\--(in scope)--> retrieve --> tools --> pack --(generate?)--> generate --> verify?
                                                                    ^                |
                                                                    +--(one retry)---+

- **classify**: deterministic route (`router.route`) plus an LLM scope check on gpt-oss-20b
  (`router.scope`). An out-of-scope question is refused without retrieval or a 120b call.
- **retrieve**: exactly v5 (hybrid ids + cross-reference expansion + endnotes), via
  `retrieve.route.retrieve`, so the agent can only add to what v5 finds.
- **tools**: on the definition route, the defining clause goes to rank 1 (`tools.Definitions`).
- **pack** / **generate**: the same evidence packing, prompt and model as every other version
  (`statnav.answer`), so differences on the ladder come from the graph, not the prompt.
- **verify** (v7, `agent: {verify: true}`): gpt-oss-20b maps each claim to its supporting
  passages (`verify.verify`); a claim with no support sends the answer back to `generate` once,
  with the claim named. `verify_citations: true` also replaces the answer's citations with that
  support (measured worse; off in v7).

Eval retrieval-only runs stop after `pack` (state `generate=False`): routing, the scope check
and the tools are all measured on full dev without spending 120b tokens.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, TypedDict

from langgraph.graph import END, START, StateGraph

from statnav.agent.router import route, scope
from statnav.agent.tools import Definitions, definition_hits
from statnav.agent.verify import verify
from statnav.answer import generate, pack, passages
from statnav.llm.client import Reply  # noqa: TC001 - langgraph resolves State hints at runtime
from statnav.obs.logging import get_logger
from statnav.retrieve.amend import attach
from statnav.retrieve.route import as_dicts, retrieve

if TYPE_CHECKING:
    import psycopg

    from statnav.embed.jina import JinaClient
    from statnav.llm.client import ChatClient

log = get_logger(__name__)


class State(TypedDict, total=False):
    question: str
    k: int | None
    generate: bool
    route: str
    terms: list[str]
    definitions: list[str]
    in_scope: bool
    scope_reason: str
    classify_tokens: int
    hits: list[dict]
    evidence: list[dict]
    out: dict | None
    reply: Reply | None
    error: str | None
    answer_tokens: int
    attempts: int
    retry: list[str] | None
    verify_tokens: int
    verified: bool | None
    unsupported: list[str]
    steps: list[str]


@dataclass
class AgentResult:
    question: str
    route: str
    in_scope: bool
    scope_reason: str
    hits: list[dict]
    evidence: list[dict]
    out: dict | None = None  # {"answer", "citations", "refused"}; None when not generated
    reply: Reply | None = None  # None when refused before generation or not generated
    classify_tokens: int = 0
    definitions: list[str] = field(default_factory=list)
    steps: list[str] = field(default_factory=list)
    error: str | None = None  # a provider error during generation (quota errors propagate)
    answer_tokens: int = 0  # gpt-oss-120b, summed over a v7 retry
    verify_tokens: int = 0  # gpt-oss-20b checker (v7)
    attempts: int = 0  # answer calls made (2 = the checker sent it back once)
    verified: bool | None = None  # None: not checked (v6, refused, or the check itself failed)
    unsupported: list[str] = field(default_factory=list)  # claims still unsupported at the end


class Agent:
    """The v6 graph, bound to one connection, one version config and its LLM clients."""

    def __init__(self, conn: psycopg.Connection, jina: JinaClient, cfg: dict,
                 answer_llm: ChatClient | None, classify_llm: ChatClient | None,
                 verify_llm: ChatClient | None = None) -> None:
        self.conn, self.jina, self.cfg = conn, jina, cfg
        self.opts = cfg.get("agent") or {}
        self.answer_llm, self.classify_llm = answer_llm, classify_llm
        self.verify_llm = verify_llm if self.opts.get("verify") else None
        self.defs = Definitions.from_db(conn) if self.opts.get("definitions") else None
        self.graph = self._build()

    def _build(self):  # noqa: ANN202 - langgraph's compiled type is private
        g = StateGraph(State)
        g.add_node("classify", self._classify)
        g.add_node("refuse", self._refuse)
        g.add_node("retrieve", self._retrieve)
        g.add_node("tools", self._tools)
        g.add_node("pack", self._pack)
        g.add_node("generate", self._generate)
        g.add_node("verify", self._verify)
        g.add_edge(START, "classify")
        g.add_conditional_edges("classify", lambda s: "retrieve" if s["in_scope"] else "refuse",
                                ["retrieve", "refuse"])
        g.add_edge("refuse", END)
        g.add_edge("retrieve", "tools")
        g.add_edge("tools", "pack")
        g.add_conditional_edges("pack", lambda s: "generate" if s["generate"] else END,
                                ["generate", END])
        g.add_conditional_edges("generate",
                                lambda s: "verify" if self._should_verify(s) else END,
                                ["verify", END])
        g.add_conditional_edges("verify", lambda s: "generate" if s.get("retry") else END,
                                ["generate", END])
        return g.compile()

    # -- nodes --------------------------------------------------------------------------
    def _classify(self, s: State) -> State:
        q = s["question"]
        found = self.defs.find(q) if self.defs else []
        r = route(q, bool(found))
        defs = [p for _, pids in found for p in pids] if r == "definition" else []
        in_scope, reason, used = True, "", 0
        if self.opts.get("scope_check") and self.classify_llm is not None:
            v = scope(self.classify_llm, q)
            in_scope, reason, used = v.in_scope, v.reason, v.tokens
        log.debug("agent_classify", route=r, in_scope=in_scope, terms=[t for t, _ in found])
        return {"route": r, "terms": [t for t, _ in found], "definitions": defs,
                "in_scope": in_scope, "scope_reason": reason, "classify_tokens": used,
                "steps": [*s.get("steps", []), "classify"]}

    def _refuse(self, s: State) -> State:
        reason = s.get("scope_reason") or "the question is outside the Income-tax Act, 2025"
        return {"hits": [], "evidence": [], "reply": None,
                "out": {"answer": f"Refused: {reason}", "citations": [], "refused": True},
                "steps": [*s["steps"], "refuse"]}

    def _retrieve(self, s: State) -> State:
        hits = as_dicts(retrieve(self.conn, self.jina, s["question"], self.cfg, s.get("k")))
        return {"hits": hits, "steps": [*s["steps"], "retrieve"]}

    def _tools(self, s: State) -> State:
        if not s.get("definitions"):
            return {}
        version = self.cfg["chunks"]
        extra = definition_hits(self.conn, s["definitions"], version,
                                self.jina.embed_query(s["question"]))
        if self.cfg["retrieval"].get("endnotes"):
            extra = attach(self.conn, extra,
                           structured=self.cfg["retrieval"]["endnotes"] == "structured")
        k = s.get("k") or self.cfg["retrieval"]["k"]
        # the defining clause goes first; the retrieved list keeps its order after it
        front = as_dicts(extra)
        ids = {h["chunk_id"] for h in front}
        hits = (front + [h for h in s["hits"] if h["chunk_id"] not in ids])[:k]
        return {"hits": hits, "steps": [*s["steps"], "definitions"]}

    def _pack(self, s: State) -> State:
        return {"evidence": pack(s["hits"], self.cfg["evidence_budget"]),
                "steps": [*s["steps"], "pack"]}

    def _generate(self, s: State) -> State:
        if not s["evidence"]:
            return {"reply": None, "steps": [*s["steps"], "generate"],
                    "out": {"answer": "Nothing was retrieved for that question.",
                            "citations": [], "refused": True}}
        if self.answer_llm is None:
            raise RuntimeError("this agent has no answer model (retrieval-only)")
        from statnav.llm.client import LLMError, QuotaExhausted

        retry = None
        if s.get("retry"):
            retry = (s["reply"].text, s["retry"])
        try:
            out, reply = generate(self.answer_llm, s["question"], s["evidence"], retry)
        except QuotaExhausted:
            raise
        except LLMError as exc:
            return {"reply": None, "error": str(exc), "steps": [*s["steps"], "generate"],
                    "retry": None,
                    "out": {"answer": f"[error: {exc}]", "citations": [], "refused": False}}
        used = reply.usage.get("total_tokens") or 0
        return {"out": out, "reply": reply, "retry": None,
                "answer_tokens": s.get("answer_tokens", 0) + used,
                "attempts": s.get("attempts", 0) + 1, "steps": [*s["steps"], "generate"]}

    def _should_verify(self, s: State) -> bool:
        out = s.get("out") or {}
        return (self.verify_llm is not None and s.get("reply") is not None
                and not out.get("refused") and bool(out.get("answer")))

    def _verify(self, s: State) -> State:
        out = dict(s["out"])
        v = verify(self.verify_llm, str(out.get("answer") or ""), passages(s["evidence"]),
                   len(s["evidence"]))
        upd: State = {"verify_tokens": s.get("verify_tokens", 0) + v.tokens,
                      "steps": [*s["steps"], "verify"], "retry": None}
        if v.error:  # the check itself failed: keep the answer as generated
            log.debug("agent_verify_error", error=v.error)
            return {**upd, "verified": None, "unsupported": []}
        # Re-deriving citations from the checker's support is off by default: measured on
        # dev_mini it lowered citation precision 0.958 -> 0.896 and recall 0.896 -> 0.854 (the
        # 20b checker cites more loosely than the 120b answer model, and once picked the wrong
        # Schedule XIV paragraph). The verdict still gates a retry.
        if v.citations and self.opts.get("verify_citations"):
            out["citations"] = v.citations
        upd.update(out=out, verified=v.ok, unsupported=v.unsupported)
        if not v.ok and s.get("attempts", 0) < 2:
            upd["retry"] = v.unsupported
        return upd

    # -- entry point --------------------------------------------------------------------
    def stream(self, question: str, k: int | None = None,
               generate: bool = True) -> Iterator[tuple[str, State]]:
        """Yield (node name, state so far) after each node runs; the API streams these."""
        s: State = {"question": question, "k": k, "generate": generate, "steps": []}
        for chunk in self.graph.stream(dict(s), stream_mode="updates"):
            for node, upd in chunk.items():
                s.update(upd or {})
                yield node, s

    def run(self, question: str, k: int | None = None, generate: bool = True) -> AgentResult:
        s: State = {}
        for _, s in self.stream(question, k, generate):  # noqa: B007 - keep the final state
            pass
        return self.result(question, s)

    @staticmethod
    def result(question: str, s: State) -> AgentResult:
        """The final state of a run as an `AgentResult`."""
        return AgentResult(question=question, route=s["route"], in_scope=s["in_scope"],
                           scope_reason=s.get("scope_reason", ""), hits=s.get("hits", []),
                           evidence=s.get("evidence", []), out=s.get("out"),
                           reply=s.get("reply"), classify_tokens=s.get("classify_tokens", 0),
                           definitions=s.get("definitions", []), steps=s.get("steps", []),
                           error=s.get("error"), answer_tokens=s.get("answer_tokens", 0),
                           verify_tokens=s.get("verify_tokens", 0),
                           attempts=s.get("attempts", 0), verified=s.get("verified"),
                           unsupported=s.get("unsupported", []))
