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


#: v10: the scope check and a rewrite of the question in one gpt-oss-20b call. Measured on the lay
#: set (Phase 15): SCOPE_PROMPT refused 8 of 78 answerable lay questions, reading first-person
#: questions as "personal tax advice" and tax collected at source as GST; and lay wording misses
#: the Act's vocabulary ("notional rent" for annual value), which no id lookup can fix.
UNDERSTAND_PROMPT = """You screen and rephrase questions for a search tool over India's \
Income-tax Act, 2025 (as amended by the Finance Act, 2026). Most users are ordinary taxpayers \
describing their own situation in everyday words. You have NOT seen the Act's text, so never \
decide whether the Act defines, contains or specifies something: a later step checks that.

1. Category. Pick exactly one:
- "forms": which return form to file, Income-tax Rules, CBDT circulars or notifications;
- "courts": a court or tribunal decision;
- "other_law": GST, how much stamp duty or registration fee to pay, company or tenancy law, \
treaties, foreign tax. NOT tax deducted or collected at source (TDS/TCS): that is income tax, \
even when a seller of coal, scrap, cars or tour packages, a bank or a buyer collects it ("do I \
have to collect tax from my customers?" is "act"). NOT what an income-tax term means ("stamp duty \
value", "fair market value"): that is "act";
- "own_case": using the e-filing portal, or the user's own notice, refund status or dispute;
- "current_facts": the interest a bank or scheme pays today (PPF, FD, EPF), people, \
statistics, or a future budget;
- "advice": working out one person's tax bill, or choosing for them (which regime or investment \
is better, whether a plan is a good idea);
- "act": anything else, including what the Act says about the user's own situation ("I pay rent \
of 60,000 a month, do I have to cut tax?", "I'm 70, do I pay advance tax?", "what late fee will I \
pay?"). If unsure, pick "act".

2. Queries. For "act", write 1 or 2 short search queries that restate the question in the Act's \
own legal vocabulary. Name the specific payment, income, asset or person the user means, in the \
Act's words, not just the general topic (e.g. "annual value of house property occupied by the \
owner for his own residence", "consideration for transfer of a virtual digital asset", "fees \
for professional services paid to a resident", "deduction for interest on deposits in a \
savings account", "income not included in total income: agricultural income"). Never write a \
section, Schedule, clause or serial number.

3. Kind: "amendment" if it asks what changed in 2026 or in the budget, even as a second \
question ("... Did the 2026 budget raise it?"); "table" if it asks for a \
rate, threshold, slab, or an amount deducted or collected at source; "definition" only if it \
asks what a particular word or phrase means; otherwise "general".

Return only JSON: {"category": "act", "reason": "<one short sentence>", "queries": ["..."], \
"kind": "general"}"""

#: v10's out-of-scope categories; `in_scope` is derived in code, because the first version asked
#: for a bare `in_scope` and gpt-oss-20b answered true while its own reason said "asks which return
#: form to file" (4 of 17 lay refusals let through on lay_dev)
CATEGORIES = ("forms", "courts", "other_law", "own_case", "current_facts", "advice", "act")
_AT_SOURCE = re.compile(r"\b(?:TDS|TCS|(?:deducted|collected) at source|tax (?:deduction|"
                        r"collection) at source)\b", re.I)
#: the same in plain words ("collect tax from the buyers", "tax cut from the interest"); gpt-oss-20b
#: still called "I sell coal ... do I have to collect extra tax from the buyers?" GST (lay_dev)
_AT_SOURCE_LAY = re.compile(r"\b(?:collect|deduct|cut|withh[oe]ld)\w*\b[^.?]{0,40}\btax\b|"
                            r"\btax\b[^.?]{0,40}\b(?:collect|deduct|cut|withh[oe]ld)\w*\b", re.I)
_GST = re.compile(r"\b(?:GST|goods and services tax)\b", re.I)
#: a budget question in plain words; the 20b model called "... Did the 2026 budget raise it?"
#: "general", so the answer lost its *What changed* block
_BUDGET = re.compile(r"\b(?:budget|finance act)\b", re.I)
#: a later year's budget: the corpus is the Act as amended by the Finance Act, 2026, yet gpt-oss-20b
#: called "What does the Finance Bill, 2027 propose?" act (dev). A "2027-28" tax year is not one.
_FUTURE_BUDGET = re.compile(
    r"\b(?:finance\s+(?:bill|act)|budget)\W{1,3}20(?:2[7-9]|[3-9]\d)\b(?!-)|"
    r"\b20(?:2[7-9]|[3-9]\d)\b(?!-)\W{1,3}(?:union\s+)?(?:budget|finance\s+(?:bill|act))\b", re.I)
#: a penalty under another named Act is in that Act. The Act cites the Black Money, Benami and
#: Wealth-tax Acts, so naming one is not enough; gpt-oss-20b called "What is the penalty under the
#: Black Money Act for undisclosed foreign assets?" act (dev)
_OTHER_ACT_PENALTY = re.compile(
    r"\b(?i:penalt(?:y|ies)|punishment|prosecution)\b[^.?]{0,30}\b(?i:under\s+the)\s+"
    r"(?!(?i:income[\s‑-]tax)\b)(?:[A-Z][\w()‑-]*\s+){1,8}Act\b")
KINDS = ("amendment", "table", "definition", "general")
#: a rewrite in the Act's words that asks for a table's numbers (the 20b model often calls these
#: "general", and `_TABLE` only knows the abbreviations)
TABLE_WORDS = re.compile(r"\b(?:deducted at source|collected at source|rates?|threshold|slab)\b",
                         re.I)
#: room for gpt-oss-20b's reasoning plus the longer JSON (the classify role's 400 is too tight)
UNDERSTAND_MAX_TOKENS = 700
#: a provision number anywhere in a rewrite: the 20b model knows the Income-tax Act, 1961's
#: numbering ("section 54", "section 80C"), which would send the id lookup to the wrong provision
_NUMBERED = re.compile(
    r"\b(?:u/s|sections?|schedules?|sub-sections?|clauses?|paragraphs?|rules?)\s*"
    r"[\dIVXL]+[A-Z]{0,3}(?:\s*\([0-9a-zA-Z]{1,4}\))*|\b\d{2,3}[A-Z]{1,3}\b", re.I)


@dataclass
class Understanding:
    in_scope: bool
    reason: str
    queries: list[str]
    kind: str
    tokens: int
    cached: bool


def clean_queries(raw: object) -> list[str]:
    """At most two distinct search queries, with any provision number removed."""
    out: list[str] = []
    for q in raw if isinstance(raw, list) else []:
        if not isinstance(q, str):
            continue
        q = re.sub(r"\s+", " ", _NUMBERED.sub(" ", q)).strip(" ,;:-")[:200]
        if len(q) > 3 and q.lower() not in (x.lower() for x in out):
            out.append(q)
    return out[:2]


def understand(llm: ChatClient, question: str) -> Understanding:
    """v10's classifier: scope, Act-vocabulary search queries and the question's kind, in one
    call. Fails open like `scope`; `QuotaExhausted` propagates."""
    try:
        reply = llm.chat([{"role": "system", "content": UNDERSTAND_PROMPT},
                          {"role": "user", "content": question}], json_mode=True,
                         max_tokens=UNDERSTAND_MAX_TOKENS)
    except LLMError as exc:
        return Understanding(True, f"classifier failed: {str(exc)[:80]}", [], "general", 0, False)
    tokens = reply.usage.get("total_tokens") or 0
    try:
        out = reply.json()
    except (LLMError, ValueError):
        return Understanding(True, "classifier reply was not JSON", [], "general", tokens,
                             reply.cached)
    kind = out.get("kind") if out.get("kind") in KINDS else "general"
    category = out.get("category")
    reason = str(out.get("reason") or "")
    # the prompt says TDS/TCS is income tax, yet gpt-oss-20b still filed "tax deducted at source
    # on freelance fees" under other_law (lay_dev); a TDS/TCS question is never other law
    if category == "other_law" and (_AT_SOURCE.search(f"{question} {reason}") or (
            _AT_SOURCE_LAY.search(question) and not _GST.search(question))):
        category = "act"
    if category == "act" and _FUTURE_BUDGET.search(question):
        category = "current_facts"
    elif category == "act" and _OTHER_ACT_PENALTY.search(question):
        category = "other_law"
    if kind in ("general", "table") and _BUDGET.search(question):
        kind = "amendment"
    # an unknown or missing category fails open
    in_scope = category not in CATEGORIES or category == "act"
    if not in_scope:
        reason = f"{category}: {reason}" if reason else str(category)
    return Understanding(in_scope, reason, clean_queries(out.get("queries")) if in_scope else [],
                         kind, tokens, reply.cached)


@dataclass
class Scope:
    in_scope: bool
    reason: str
    tokens: int
    cached: bool


def scope(llm: ChatClient, question: str) -> Scope:
    """Ask the classifier whether the Act can answer `question`.

    A classifier failure fails open, like an unparseable verdict: on some lay questions
    gpt-oss-20b produces no JSON at all (Groq 400 `json_validate_failed`), and refusing to answer
    because the screen broke would be worse than letting the generator decide. Running out of
    quota (`QuotaExhausted`, not an `LLMError`) still propagates.
    """
    try:
        reply = llm.chat([{"role": "system", "content": SCOPE_PROMPT},
                          {"role": "user", "content": question}], json_mode=True)
    except LLMError as exc:
        return Scope(True, f"classifier failed: {str(exc)[:80]}", 0, False)
    tokens = reply.usage.get("total_tokens") or 0
    try:
        out = reply.json()
    except (LLMError, ValueError):
        # unparseable verdicts fail open: the generator can still refuse
        return Scope(True, "classifier reply was not JSON", tokens, reply.cached)
    return Scope(out.get("in_scope") is not False, str(out.get("reason") or ""), tokens,
                 reply.cached)
