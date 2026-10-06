"""v7: check an answer against its evidence, re-derive its citations, flag unsupported claims.

What the checks target was measured on v6's dev_mini answers before building, not assumed:

- Simple deterministic rules (every number in the cited text, every named provision cited) flag
  mostly false positives: years like "2026" come from endnotes, and provisions such as s237(1)
  are named *inside* the passage the answer cites.
- The real remaining error is **under-citation**. Multi-hop answers rely on two passages and
  cite one: v6 cites `s173` but not `s66(16)` for "fixed place of business", and `s394` but not
  `s402(33)` for the overseas tour package, although both passages are in its evidence.

So the verifier (gpt-oss-20b) splits the answer into claims and names, for each, the passages
that state it -- across *all* the evidence, not just what the answer cited. A claim no passage
supports sends the answer back for one regeneration with the claim named (`graph.py`); a second
failure is returned as is, with the unsupported claims recorded.

Measured on dev_mini, the hypothesis behind re-deriving citations was wrong: the checker judged
every v6 answer fully supported by the passage it already cited (s173 alone does state "fixed
place of business ... wholly or partly carried on"; the gold's second hop s66(16) is needed to
*find* the answer, not to support it), and using its support as the citations lowered citation
precision and recall. So v7 keeps the generator's citations and uses the verdict as a gate
(`agent: {verify_citations: true}` restores re-derivation).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from statnav.llm.client import ChatClient, LLMError

VERIFY_PROMPT = """You check an answer about India's Income-tax Act, 2025 against numbered \
context passages.
Split the answer into its distinct factual claims (rules, conditions, rates, amounts, periods, \
definitions, amendment details). Ignore framing such as "Under the Act" or "The passages say".
For each claim list EVERY passage that states it or directly supports it, e.g. ["C2", "C5"]. \
Use [] only if no passage supports it. A claim is supported if a passage says the same thing \
in other words; it is not supported if it adds a number, condition or provision that no \
passage contains.
Return only JSON: {"claims": [{"claim": "...", "support": ["C1"]}]}"""

_LABEL = re.compile(r"C(\d+)")


@dataclass
class Verdict:
    ok: bool  # every claim has support (and there was at least one claim)
    citations: list[str]  # "C<n>" labels supporting the answer, in passage order
    unsupported: list[str] = field(default_factory=list)
    claims: list[dict] = field(default_factory=list)
    tokens: int = 0
    error: str | None = None  # the check itself failed; the answer is left unchanged


def _labels(raw: object, n: int) -> list[int]:
    out = []
    for x in raw if isinstance(raw, list) else [raw]:
        for m in _LABEL.finditer(str(x)):
            k = int(m.group(1))
            if 1 <= k <= n:
                out.append(k)
    return out


def verify(llm: ChatClient, answer: str, evidence_block: str, n_passages: int) -> Verdict:
    """Ask the checker which passages support each claim in `answer`.

    `evidence_block` is the same "[C1] ..." text the generator saw, so labels line up.
    Provider errors other than quota propagate as a failed check (fail open: keep the answer).
    """
    from statnav.llm.client import QuotaExhausted

    try:
        reply = llm.chat([{"role": "system", "content": VERIFY_PROMPT},
                          {"role": "user", "content": f"{evidence_block}\n\nAnswer to check:\n"
                                                      f"{answer}"}], json_mode=True)
    except QuotaExhausted:
        raise
    except LLMError as exc:
        return Verdict(True, [], error=str(exc))
    tokens = reply.usage.get("total_tokens") or 0
    try:
        claims = reply.json().get("claims") or []
    except (LLMError, ValueError, AttributeError):
        return Verdict(True, [], tokens=tokens, error="checker reply was not JSON")
    claims = [c for c in claims if isinstance(c, dict) and str(c.get("claim") or "").strip()]
    if not claims:
        return Verdict(True, [], tokens=tokens, error="checker found no claims")
    support: set[int] = set()
    unsupported = []
    for c in claims:
        got = _labels(c.get("support"), n_passages)
        support.update(got)
        if not got:
            unsupported.append(str(c["claim"]).strip())
    return Verdict(not unsupported, [f"C{k}" for k in sorted(support)], unsupported, claims,
                   tokens)
