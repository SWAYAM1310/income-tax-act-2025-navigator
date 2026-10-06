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
import re
from collections import defaultdict

import psycopg

from statnav.embed import tokens
from statnav.retrieve.dense import Hit


def _label_key(label: str) -> tuple[int, str]:
    """Endnote labels are mostly numeric; sort them as numbers when they are."""
    return (int(label), "") if label.isdigit() else (1 << 30, label)


#: endnote styles, one per ladder step that changed them (`retrieval.endnotes` in a version)
STYLES = ("raw", "structured", "explicit")
_SUB_FOR = re.compile(r"[Ss]ubs?\.\s+for\s+[\"“](.+?)[\"”]")


def style_of(retrieval_cfg: dict) -> str | None:
    """`endnotes: true` (v4/v5) is the raw style; v6 names `structured`, v8 `explicit`."""
    v = retrieval_cfg.get("endnotes")
    if not v:
        return None
    style = "raw" if v is True else str(v)
    if style not in STYLES:
        raise ValueError(f"endnotes must be one of {STYLES}, not {v!r}")
    return style


def changed_words(label: str, header: str, kind: str | None, marked: str | None
                  ) -> tuple[str | None, str | None]:
    """(old words, new words) of one endnote's change, where the Act prints them.

    The old words are quoted in `Sub. for "..."`; the new words are the bracket the endnote
    tags in the provision's text (`{{fn:11}}[...]`). Inserted words have no old side.
    """
    new = None
    if marked:
        m = re.search(r"\{\{fn:" + re.escape(label) + r"\}\}\[([^\]]*)\]", marked)
        new = m.group(1).strip() if m and m.group(1).strip() else None
    old = _SUB_FOR.search(header or "") if kind == "substituted" else None
    return (old.group(1) if old else None), new


def render(label: str, header: str, prior: str | None, kind: str | None = None,
           act: str | None = None, date: str | None = None, target: str | None = None,
           words: tuple[str | None, str | None] | None = None) -> str:
    """One endnote as an evidence line.

    The raw shape (`structured=False`, what v4/v5 and the oracle use) is the Act's own text:
    `Endnote 11: Sub. for "..." by Act No. 4 of 2026, w.e.f. 1-4-2026.` The model often fails to
    read the abbreviation as a change type -- on dev_mini v5 described an `Ins.` endnote as
    "amended" -- so the structured shape states the parsed type, act and date in words first.
    It also names the provision the endnote `target`s: one chunk can carry several endnotes
    (`sch:XIV:4` has a substitution in 4(1)(a) and an insertion in 4(3)), and without the
    target v6 reported 4(3) as "substituted".

    The explicit shape (v8) also spells out the `words` on each side. "Sub. for X" means X is
    the *earlier* wording, and the model read it the other way round: v6 said section 195(1)(i)
    went "from 30% to 60%" when the endnote (`Sub. for "60%"`) says 60% was replaced by 30%.
    """
    note = " ".join(x for x in (header, prior) if x)
    if not kind:
        return f"Endnote {label}: {note}"
    facts = ([f"applies to {target}"] if target else []) + [f"amendment type: {kind}"]
    if act:
        facts.append(f"by {act}")
    if date:
        facts.append(f"with effect from {date}")
    old, new = words or (None, None)
    if old and new:
        facts.append(f'wording before: "{old}"; wording now: "{new}"')
    elif kind == "inserted" and new:
        facts.append(f'inserted (not in the Act before): "{new}"')
    return f"Endnote {label} [{'; '.join(facts)}]: {note}"


def endnotes_for(conn: psycopg.Connection, provisions: list[str],
                 style: str = "raw") -> dict[str, list[str]]:
    """Endnote lines for each of `provisions` in one of `STYLES` (see `render`)."""
    if not provisions:
        return {}
    rows = conn.execute(
        "SELECT l.provision_id, a.label, a.header, a.prior_text, a.type, a.amending_act, "
        "a.effective_date, p.number, p.schedule, p.text_marked "
        "FROM amendments a JOIN amendment_links l ON l.key = a.key "
        "LEFT JOIN provisions p ON p.id = l.provision_id "
        "WHERE l.provision_id = ANY(%s)",
        (list(provisions),),
    ).fetchall()
    out: dict[str, list[tuple[tuple[int, str], str]]] = defaultdict(list)
    for provision_id, label, header, prior, kind, act, date, number, schedule, marked in rows:
        # "Schedule XIV, paragraph 4(3)" is already a citation; sections need the word
        target = (number if schedule else f"section {number}") if number else provision_id
        if style == "raw":
            line = render(label, header, prior)
        else:
            words = changed_words(label, header, kind, marked) if style == "explicit" else None
            line = render(label, header, prior, kind, act, date, target, words)
        out[provision_id].append((_label_key(label), line))
    return {p: [line for _, line in sorted(v)] for p, v in out.items()}


def attach(conn: psycopg.Connection, hits: list[Hit], style: str = "raw") -> list[Hit]:
    """Append each hit's linked endnotes to its text, re-counting tokens.

    A hit covering several amended provisions gets each endnote once, ordered by label.
    """
    if not hits:
        return hits
    provisions = {p for h in hits for p in (h.meta.get("provisions") or [])}
    by_provision = endnotes_for(conn, sorted(provisions), style)
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
