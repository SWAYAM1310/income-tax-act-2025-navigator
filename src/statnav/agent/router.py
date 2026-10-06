"""Decide what kind of question this is, and whether the Act can answer it at all.

Two separate decisions with different costs:

- **route** is deterministic (regexes over the question). It picks which tools run after
  retrieval. Routing by pattern is free, reproducible and easy to audit, and the patterns it needs
  are narrow ("meaning of", "amended by the Finance Act, 2026").
- **scope** uses gpt-oss-20b, because "is this answerable from the Act's text?" has an open-ended
  negative class (Rules, forms, circulars, case law, the e-filing portal, other statutes, current
  events...). An out-of-scope question is refused before retrieval, so it also costs no
  gpt-oss-120b tokens. The generator's own refusal rule stays as a backstop.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from statnav.llm.client import ChatClient, LLMError
from statnav.retrieve.ids import provision_refs

ROUTES = ("amendment", "definition", "table", "general")

_AMEND = re.compile(r"\b(amend\w*|finance act,?\s+2026|inserted|substituted|omitted)\b", re.I)
_DEFINE = re.compile(
    r"\b(meaning of|definition of|defined|define|what is meant by|what does .{1,80} mean)\b",
    re.I)
_TABLE = re.compile(r"\b(rate|threshold|TDS|TCS|Sl\.?\s*No|serial number|table)\b", re.I)


def route(question: str, has_term: bool) -> str:
    """One of `ROUTES`. `has_term`: the question names a term the Act defines."""
    if _AMEND.search(question) and provision_refs(question):
        return "amendment"
    if has_term and _DEFINE.search(question):
        return "definition"
    if _TABLE.search(question):
        return "table"
    return "general"


#: Judge the *topic*, never the content. The first prompt let gpt-oss-20b decide from memory
#: whether the Act covers something, and it refused 5 of 124 answerable dev questions with
#: reasons like "The Act does not define 'zero coupon bond'" (s2(112) does). The classifier has
#: not seen the text; whether the Act contains the answer is retrieval's and the generator's job.
SCOPE_PROMPT = """You screen questions for a search tool over India's Income-tax Act, 2025 \
(as amended by the Finance Act, 2026). You have NOT seen the Act's text, so never decide \
whether the Act defines, contains or specifies something: a later step checks that.
Judge only the topic. A question is out of scope only when it is clearly about one of:
- Income-tax Rules, forms (e.g. ITR forms), CBDT circulars or notifications;
- court or tribunal decisions;
- tax treaty terms, or laws other than the Income-tax Act, 2025;
- using the e-filing portal, or a taxpayer's own case, refund or notice;
- current facts, people, statistics or interest rates, or future bills;
- personal tax advice or a computation of someone's tax.
Everything else that asks what the Act says is in scope, including definitions, rates, \
thresholds, time limits, conditions, procedures the Act lays down, and amendments. Vague or \
oddly worded questions about the Act are in scope. If unsure, answer in scope.
Return only JSON: {"in_scope": true, "reason": "<one short sentence>"}"""


@dataclass
class Scope:
    in_scope: bool
    reason: str
    tokens: int
    cached: bool


def scope(llm: ChatClient, question: str) -> Scope:
    """Ask the classifier whether the Act can answer `question`. Errors propagate."""
    reply = llm.chat([{"role": "system", "content": SCOPE_PROMPT},
                      {"role": "user", "content": question}], json_mode=True)
    tokens = reply.usage.get("total_tokens") or 0
    try:
        out = reply.json()
    except (LLMError, ValueError):
        # unparseable verdicts fail open: the generator can still refuse
        return Scope(True, "classifier reply was not JSON", tokens, reply.cached)
    return Scope(out.get("in_scope") is not False, str(out.get("reason") or ""), tokens,
                 reply.cached)
