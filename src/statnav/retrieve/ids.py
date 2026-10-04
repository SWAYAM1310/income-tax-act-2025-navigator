"""Find the provision ids a question names, so retrieval can look them up exactly.

Dense embeddings carry no signal for "section 483(1)": the number is the whole content of the
reference, and Postgres' `simple` tokeniser splits it into the tokens `483` and `1`. Amendment
questions always name their provision ("How was section 483(1) amended..."), which is why
amendment recall@5 sits at 0.06 through v2. Parsing the reference and looking it up by id turns
that into an exact match.

    provision_refs("How was section 483(1) amended?")        -> ["s483(1)"]
    provision_refs("Schedule XI, Part A, paragraph 4(f)")     -> ["sch:XI:A:4(f)"]
"""

from __future__ import annotations

import re

# a chain of bracketed sub-provision labels: (3)(b)(ii)(A)
_SUBS = r"(?:\s*\([0-9a-zA-Z]{1,4}\))*"
# "section 206(3)(a)", "section 427", "section 194A(1)"
_SECTION = re.compile(rf"\bsections?\s+(\d{{1,3}}[A-Z]{{0,2}})({_SUBS})", re.IGNORECASE)
# "Schedule XI, Part A, paragraph 4(f)" / "Schedule XIV, paragraph 4(3)"
_SCHEDULE = re.compile(
    rf"\bschedule\s+([IVXL]{{1,6}})"
    rf"(?:\s*,?\s*part\s+([A-Z]))?"
    rf"(?:\s*,?\s*(?:paragraph|para|rule)\s+(\d{{1,3}})({_SUBS}))?",
    re.IGNORECASE,
)


def _subs(raw: str) -> str:
    """Normalise a bracket chain, dropping the whitespace authors put between brackets."""
    return "".join(f"({m})" for m in re.findall(r"\(([0-9a-zA-Z]{1,4})\)", raw or ""))


def provision_refs(text: str) -> list[str]:
    """Canonical provision ids named in `text`, most specific first, de-duplicated.

    Section numbers keep their case (`194A`); schedule numerals are upper-cased (`sch:XIV`).
    """
    out: dict[str, None] = {}
    for m in _SECTION.finditer(text):
        out.setdefault(f"s{m.group(1).upper()}{_subs(m.group(2))}", None)
    for m in _SCHEDULE.finditer(text):
        parts = [f"sch:{m.group(1).upper()}"]
        if m.group(2):
            parts.append(m.group(2).upper())
        if m.group(3):
            parts.append(f"{m.group(3)}{_subs(m.group(4))}")
        out.setdefault(":".join(parts), None)
    return list(out)


def ancestors(pid: str) -> list[str]:
    """`pid` then its enclosing provisions, most specific first.

    `s228(3)(b)` -> ["s228(3)(b)", "s228(3)", "s228"]. The chunkers index a provision subtree
    under the node that owns it, so a deep reference may only be reachable via its parent.
    """
    out = [pid]
    head, *_ = pid.split("(", 1)
    brackets = re.findall(r"\([0-9a-zA-Z]{1,4}\)", pid)
    for n in range(len(brackets) - 1, -1, -1):
        cand = head + "".join(brackets[:n])
        if cand != pid and cand:
            out.append(cand)
    if pid.startswith("sch:"):
        # sch:XI:A:4(f) -> sch:XI:A:4 -> sch:XI:A -> sch:XI
        seg = out[-1].split(":")
        for n in range(len(seg) - 1, 1, -1):
            out.append(":".join(seg[:n]))
    return list(dict.fromkeys(out))


def expand(text: str) -> list[str]:
    """Every id worth trying for `text`: each reference, then its ancestors."""
    out: dict[str, None] = {}
    for pid in provision_refs(text):
        for cand in ancestors(pid):
            out.setdefault(cand, None)
    return list(out)
