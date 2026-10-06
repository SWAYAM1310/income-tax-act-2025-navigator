"""Read-only lookups over the Act in Postgres, shared by the API and the MCP server.

Every function takes an open connection and returns plain dicts, so the HTTP endpoints and the
MCP tools serve the same data the agent retrieves from (`provisions`, `table_rows`,
`amendments`, `amendment_links`).
"""

from __future__ import annotations

import re

import psycopg

from statnav.retrieve.amend import _label_key

_PROV_COLS = ("id, kind, number, label, heading, text, parent_id, chapter, part, schedule, "
              "page_start, page_end, is_amended, text_marked")
_PROV_KEYS = [c.strip() for c in _PROV_COLS.split(",")]


def citation(number: str, schedule: str | None) -> str:
    """Human citation: "section 2(5)", "Schedule XIV, paragraph 4(3)", "section 393 (Table)"."""
    return number if schedule else f"section {number}"


def provision(conn: psycopg.Connection, pid: str) -> dict | None:
    """One provision: its own text, children, full subtree (`subtree`), the amendments made
    anywhere in it, its enclosing section, and, for a table, its rows."""
    row = conn.execute(f"SELECT {_PROV_COLS} FROM provisions WHERE id = %s", (pid,)).fetchone()
    if row is None:
        return None
    out = dict(zip(_PROV_KEYS, row, strict=True))
    out["citation"] = citation(out["number"], out["schedule"])
    out["children"] = [
        {"id": c, "number": n, "label": lab, "text": t}
        for c, n, lab, t in conn.execute(
            "SELECT id, number, label, text FROM provisions WHERE parent_id = %s ORDER BY ord",
            (pid,)).fetchall()]
    # every endnote in the subtree (each names the provision it applies to)
    out["amendments"] = amendments(conn, pid)
    marked = out.pop("text_marked")
    own = [a for a in out["amendments"] if a["provision_id"] == pid]
    out["amended_text"] = before_after(marked, own) if marked else None
    out["subtree"] = subtree(conn, pid)
    # the enclosing section (or schedule paragraph) and its heading: printed Acts show it as the
    # marginal note beside the text, and sub-provisions have no heading of their own
    head_id = re.split(r"[(#]", pid, maxsplit=1)[0].split(":tbl")[0]
    head = conn.execute("SELECT heading, number, schedule FROM provisions WHERE id = %s",
                        (head_id,)).fetchone()
    out["section"] = ({"id": head_id, "heading": head[0], "citation": citation(head[1], head[2])}
                      if head else None)
    if out["kind"] == "table":
        out["rows"] = table_rows(conn, pid)
    return out


def subtree(conn: psycopg.Connection, pid: str, limit: int = 300) -> list[dict]:
    """The provision and everything under it, in document order, each with its depth below
    `pid` and, if amended, its before/after segments -- what a reader sees on the page."""
    rows = conn.execute(
        "SELECT id, label, heading, text, text_marked, kind FROM provisions "
        "WHERE id = %s OR id LIKE %s OR id LIKE %s ORDER BY ord LIMIT %s",
        (pid, pid + "(%", pid + ":%", limit)).fetchall()
    notes: dict[str, list[dict]] = {}
    for a in amendments(conn, pid):
        notes.setdefault(a["provision_id"], []).append(a)
    base = pid.count("(") + pid.count(":")
    return [{"id": i, "label": lab, "heading": head, "text": t, "kind": kind,
             "depth": i.count("(") + i.count(":") - base,
             "amended_text": before_after(m, notes.get(i, [])) if m else None}
            for i, lab, head, t, m, kind in rows]


_MARK = re.compile(r"\{\{fn:([^}]+)\}\}\[([^\]]*)\]?")
_SUB_FOR = re.compile(r"[Ss]ubs?\.\s+for\s+[\"“](.+?)[\"”]")


def before_after(marked: str, notes: list[dict]) -> dict:
    """Split amended text into plain and amended segments, and rebuild the wording before the
    Finance Act, 2026 where the endnotes allow it.

    `marked` tags each bracket of amended words with its endnote: `{{fn:11}}[...]`. Per
    bracket: *inserted* words were absent before; *substituted* words replaced the quoted text
    in `Sub. for "..."`; a substitution or omission that printed the whole earlier provision
    ("Prior to its substitution, clause (32) read as under:") gives it as `prior_text`. Where
    the endnote gives none of these, `before` is None rather than a guess.
    """
    by_label = {n["label"]: n for n in notes}
    segments: list[dict] = []
    before_parts: list[str] = []
    known, whole = True, None
    pos = 0
    for m in _MARK.finditer(marked):
        if m.start() > pos:
            plain = marked[pos:m.start()]
            segments.append({"text": plain})
            before_parts.append(plain)
        label, words = m.group(1), m.group(2)
        note = by_label.get(label) or {}
        kind, prior = note.get("type"), note.get("prior_text")
        sub_for = _SUB_FOR.search(note.get("endnote") or "")
        was: str | None
        if kind == "inserted":
            was = ""
        elif kind == "substituted" and sub_for:
            was = sub_for.group(1)
        elif kind in ("substituted", "omitted") and prior:
            was, whole = None, prior
        else:
            was = None
        segments.append({"text": words, "label": label, "type": kind, "was": was,
                         "endnote": note.get("endnote")})
        if was is None and whole is None:
            known = False
        before_parts.append(was or "")
        pos = m.end()
    if pos < len(marked):
        segments.append({"text": marked[pos:]})
        before_parts.append(marked[pos:])
    inserted = sum(len(s["text"]) for s in segments if s.get("type") == "inserted")
    if whole is not None:
        before = whole
    elif inserted >= 0.8 * sum(len(s["text"]) for s in segments):
        # the provision itself was inserted ("" = it did not exist before); the remainder is
        # usually parser residue such as the next Part's heading
        before = ""
    elif known:
        before = re.sub(r"\s+([;,.:])", r"\1", re.sub(r"\s{2,}", " ", "".join(before_parts)))
        before = before.strip()
    else:
        before = None
    return {"segments": segments, "before": before}


def subtree_text(conn: psycopg.Connection, pid: str, limit: int = 400) -> str:
    """The provision's text followed by its descendants', in document order."""
    rows = conn.execute(
        "SELECT label, text FROM provisions WHERE id = %s OR id LIKE %s OR id LIKE %s "
        "ORDER BY ord LIMIT %s", (pid, pid + "(%", pid + ":%", limit)).fetchall()
    return "\n".join(" ".join(x for x in (lab, t) if x) for lab, t in rows)


def table_rows(conn: psycopg.Connection, table_id: str, sl_no: str | None = None) -> list[dict]:
    """Rows of one table (e.g. `s393:tbl1`), optionally only serial number `sl_no`."""
    q = ("SELECT row_id, sl_no, subrow, row_heading, cells, rate, threshold, page_start, "
         "page_end FROM table_rows WHERE table_id = %s")
    args: list = [table_id]
    if sl_no:
        q += " AND sl_no = %s"
        args.append(sl_no)
    keys = ["row_id", "sl_no", "subrow", "row_heading", "cells", "rate", "threshold",
            "page_start", "page_end"]
    rows = [dict(zip(keys, r, strict=True)) for r in conn.execute(q, args).fetchall()]
    # serial numbers are text ("1", "2", "10"); sort them as numbers where they are
    return sorted(rows, key=lambda r: (_label_key(r["sl_no"]), r["subrow"] or "", r["row_id"]))


def amendments(conn: psycopg.Connection, pid: str, descendants: bool = True) -> list[dict]:
    """Finance Act, 2026 endnotes linked to `pid` (and, by default, to anything under it)."""
    where = "l.provision_id = %s"
    args: list = [pid]
    if descendants:
        where = "(l.provision_id = %s OR l.provision_id LIKE %s OR l.provision_id LIKE %s)"
        args += [pid + "(%", pid + ":%"]
    rows = conn.execute(
        "SELECT a.label, a.type, a.amending_act, a.effective_date, a.header, a.prior_text, "
        "l.provision_id, p.number, p.schedule FROM amendments a "
        "JOIN amendment_links l ON l.key = a.key LEFT JOIN provisions p ON p.id = l.provision_id "
        f"WHERE {where}", args).fetchall()
    out = [{"label": lab, "type": kind, "amending_act": act, "effective_date": date,
            "endnote": header, "prior_text": prior, "provision_id": target,
            "applies_to": citation(num, sch) if num else target}
           for lab, kind, act, date, header, prior, target, num, sch in rows]
    return sorted(out, key=lambda a: (_label_key(a["label"]), a["provision_id"]))
