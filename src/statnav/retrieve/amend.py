"""Attach the amendment endnotes linked to a retrieved provision.

v3 made amendment *retrieval* perfect (recall@5 0.061 -> 1.000) without improving amendment
*answers*. Asked "How was section 99(2) amended?", v3 ranks `v2:s99(2)` first and still refuses:
the chunk text carries only the `[...]` brackets marking amended words, while what changed is in
the Act's endnotes, which the chunkers keep out of the chunk. The endnote for s99(2) reads

    Sub. for "sub-section (1)(a)(i) or (b)" by Act No. 4 of 2026, w.e.f. 1-4-2026.

which is the answer. The oracle is handed these endnotes, which is why it reaches amendment type
0.667 against v2's 0.167 -- so this closes an evidence gap, not a retrieval one.

The endnote is appended to its own provision's chunk rather than added as a separate passage, so
a citation still maps to one chunk and the amendment stays attached to what it amends. Only 163
links cover 8,108 provisions, so most chunks are untouched.
"""

from __future__ import annotations

import dataclasses
from collections import defaultdict

import psycopg

from statnav.embed import tokens
from statnav.retrieve.dense import Hit


def _label_key(label: str) -> tuple[int, str]:
    """Endnote labels are mostly numeric; sort them as numbers when they are."""
    return (int(label), "") if label.isdigit() else (1 << 30, label)


def endnotes_for(conn: psycopg.Connection, provisions: list[str]) -> dict[str, list[str]]:
    """Endnote lines for each of `provisions`, in the same shape the oracle context uses."""
    if not provisions:
        return {}
    rows = conn.execute(
        "SELECT l.provision_id, a.label, a.header, a.prior_text "
        "FROM amendments a JOIN amendment_links l ON l.key = a.key "
        "WHERE l.provision_id = ANY(%s)",
        (list(provisions),),
    ).fetchall()
    out: dict[str, list[tuple[tuple[int, str], str]]] = defaultdict(list)
    for provision_id, label, header, prior in rows:
        note = " ".join(x for x in (header, prior) if x)
        out[provision_id].append((_label_key(label), f"Endnote {label}: {note}"))
    return {p: [line for _, line in sorted(v)] for p, v in out.items()}


def attach(conn: psycopg.Connection, hits: list[Hit]) -> list[Hit]:
    """Append each hit's linked endnotes to its text, re-counting tokens.

    A hit covering several amended provisions gets each endnote once, ordered by label.
    """
    if not hits:
        return hits
    provisions = {p for h in hits for p in (h.meta.get("provisions") or [])}
    by_provision = endnotes_for(conn, sorted(provisions))
    if not by_provision:
        return hits
    out = []
    for h in hits:
        seen: dict[str, None] = {}
        for p in h.meta.get("provisions") or []:
            for line in by_provision.get(p, ()):
                seen.setdefault(line, None)
        if not seen:
            out.append(h)
            continue
        text = h.text + "\n" + "\n".join(seen)
        out.append(dataclasses.replace(h, text=text, tokens=tokens.count(text)))
    return out
