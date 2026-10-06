"""Structured lookups the agent runs after retrieval, where retrieval alone measurably fails.

**Definitions.** The Act defines 557 terms in clauses shaped `"transfer" ... means/includes ...`
(108 of them in section 2). Dense retrieval misses short, generic ones: for "What is the meaning
of "transfer"?" v5's top 10 is all sections that *use* transfer (s96, s174...) and never
s2(109), which defines it. Matching the term against an index of defined terms is exact, so the
defining clause goes to rank 1.

Amendments need no tool here: v3's id lookup already ranks the named provision first, and
`retrieve.amend` attaches its endnotes (`endnotes: structured` states the change type in words).
Tables need none either: table recall@5 is 0.958 on dev and table fact recall 1.00 end-to-end.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

import numpy as np
import psycopg

from statnav.retrieve.dense import Hit
from statnav.retrieve.hybrid import under_ids
from statnav.retrieve.ids import provision_refs

#: `"term" means`, `"term", in relation to X, includes`, `"term" shall have the meaning ...`
_DEFINES = re.compile(
    r'^\s*[“"]([^”"]{2,80})[”"]\s*(?:,[^,]{0,80},\s*)?'
    r"(?:means|includes|shall mean|shall include|has the meaning|shall have the meaning"
    r"|in relation to)", re.I)
_QUOTED = re.compile(r'[“"‘\']([^”"’\']{2,80})[”"’\']')
#: the Act's own name would otherwise match defined terms such as "income-tax"
_ACT_NAME = re.compile(r"\b(?:the\s+)?income[-‑‐ ]tax\s+act(?:,?\s*2025)?", re.I)
MAX_TERMS = 2
#: per term, only the best defining provision: a second one ("University" in both s66(40) and
#: s402(44)) took two evidence slots and pushed a multi-hop question's other gold provision out
#: of the top 5 on dev
MAX_PROVISIONS = 1


def _norm(term: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[‑‐–—]", "-", term)).strip().lower()


def _section(pid: str) -> str:
    return re.split(r"[(:]", pid, maxsplit=1)[0]


@dataclass
class Definitions:
    """Defined term (lower case) -> provision ids that define it, section 2 first."""

    terms: dict[str, list[str]] = field(default_factory=dict)

    @classmethod
    def from_rows(cls, rows: list[tuple[str, str]]) -> Definitions:
        out: dict[str, list[str]] = {}
        for pid, text in rows:
            m = _DEFINES.match(text or "")
            if m:
                out.setdefault(_norm(m.group(1)), []).append(pid)
        for pids in out.values():
            pids.sort(key=lambda p: (_section(p) != "s2", p))
        return cls(out)

    @classmethod
    def from_db(cls, conn: psycopg.Connection) -> Definitions:
        return cls.from_rows(conn.execute("SELECT id, text FROM provisions").fetchall())

    def find(self, question: str) -> list[tuple[str, list[str]]]:
        """Defined terms the question asks about, with their defining provisions.

        Quoted terms win (up to `MAX_TERMS`); otherwise only the longest defined term that occurs
        as whole words, since an unquoted question rarely asks about two ("Principal Commissioner
        of Income-tax" must not also pull in "income-tax"). If the question names a section,
        definitions inside it come first.
        """
        q = _norm(_ACT_NAME.sub(" ", question))
        found = [t for t in (_norm(x) for x in _QUOTED.findall(q)) if t in self.terms]
        if not found:
            hits = [t for t in self.terms if re.search(rf"(?<![\w-]){re.escape(t)}(?![\w-])", q)]
            # the longest wins: "agricultural income" over "income"
            found = sorted(hits, key=len, reverse=True)[:1]
        named = {_section(p) for p in provision_refs(question)}
        out = []
        for t in found[:MAX_TERMS]:
            pids = sorted(self.terms[t], key=lambda p: _section(p) not in named)
            out.append((t, pids[:MAX_PROVISIONS]))
        return out


def definition_hits(conn: psycopg.Connection, pids: list[str], version: str,
                    qvec: np.ndarray, per_provision: int = 2) -> list[Hit]:
    """Chunks holding each defining provision (and its sub-clauses), best match first."""
    out: list[Hit] = []
    seen: set[str] = set()
    for pid in pids:
        for h in under_ids(conn, [pid], version, qvec, per_provision):
            if h.chunk_id not in seen:
                seen.add(h.chunk_id)
                out.append(h)
    return out
