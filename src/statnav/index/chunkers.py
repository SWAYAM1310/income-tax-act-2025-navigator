"""Chunking strategies for the eval ladder. Each returns a list of Chunk records.

v0  naive: raw PyMuPDF page text (headers, footers, endnotes left in), fixed 512-token windows
v1  cleaned: the same windows over header/footer-free, endnote-free page text
v2  structural: one chunk per provision subtree that fits in MAX_TOKENS, one per table row;
    embed_text carries a breadcrumb (section heading, chapter) so short clauses keep context

Every chunk records which provisions / table rows it covers (meta["provisions"]), so all
versions are scored against the same gold provision ids.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from statnav.embed import tokens

WINDOW = 512
OVERLAP = 64
MAX_TOKENS = 700  # v2: a subtree up to this size stays in one chunk
SPLIT_TOKENS = 1500  # v2: a single provision longer than this is windowed


@dataclass
class Chunk:
    id: str
    version: str
    text: str
    embed_text: str
    page_start: int
    page_end: int
    provision_id: str | None = None
    meta: dict = field(default_factory=dict)

    @property
    def tokens(self) -> int:
        return tokens.count(self.embed_text)


def _norm(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", text.lower()).strip()


# -- v0 / v1: fixed windows over page text -----------------------------------------------------
def window_chunks(version: str, pages: list[dict], provisions: list[dict],
                  rows: list[dict]) -> list[Chunk]:
    """Fixed token windows over the concatenated page texts, with page provenance."""
    toks: list[int] = []
    tok_page: list[int] = []
    for p in pages:
        t = tokens.encode(p["text"] + "\n")
        toks.extend(t)
        tok_page.extend([p["page"]] * len(t))
    chunks: list[Chunk] = []
    step = WINDOW - OVERLAP
    for n, start in enumerate(range(0, max(len(toks) - OVERLAP, 1), step)):
        piece = toks[start:start + WINDOW]
        text = tokens.decode(piece)
        chunks.append(Chunk(f"{version}:{n}", version, text, text,
                            tok_page[start], tok_page[min(start + WINDOW, len(toks)) - 1]))
    _attach_coverage(chunks, provisions, rows)
    return chunks


def _attach_coverage(chunks: list[Chunk], provisions: list[dict], rows: list[dict]) -> None:
    """Mark which provisions / table rows each window contains, by locating a probe string
    (the first ~60 normalised characters of the provision's own text) in the window text."""
    norm = [_norm(c.text) for c in chunks]
    for c in chunks:
        c.meta["provisions"] = []
    probes: list[tuple[str, str, int]] = []  # (id, probe, page)
    for p in provisions:
        t = _norm(p["text"])
        if len(t) >= 25 and p["kind"] not in ("chapter", "part", "schedule", "schedule-part",
                                              "table", "preamble"):
            probes.append((p["id"], t[:60], p["page_start"]))
    for r in rows:
        body = next((v for k, v in r["cells"].items() if v and not k.lower().startswith("sl")),
                    "")
        t = _norm(body)
        if len(t) >= 25:
            probes.append((r["row_id"], t[:60], r["page_start"]))
    for pid, probe, page in probes:
        for c, nt in zip(chunks, norm, strict=True):
            if c.page_start - 1 <= page <= c.page_end + 1 and probe in nt:
                c.meta["provisions"].append(pid)


# -- v2: structure-aware -------------------------------------------------------------------
def _section_of(pid: str, prov: dict[str, dict]) -> dict | None:
    p = prov.get(pid)
    while p is not None and p["kind"] not in ("section", "paragraph"):
        p = prov.get(p["parent"]) if p["parent"] else None
    return p


def _breadcrumb(p: dict, prov: dict[str, dict]) -> str:
    sec = _section_of(p["id"], prov)
    parts = []
    if p.get("schedule"):
        sch = prov.get(p["schedule"])
        if sch:
            parts.append(f"Schedule {sch['label']}" + (f" — {sch['heading']}" if sch["heading"]
                                                        else ""))
        if sec is not None:
            parts.append(f"paragraph {sec['label']}" + (f" ({sec['heading']})"
                                                        if sec["heading"] else ""))
    else:
        if sec is not None:
            parts.append(f"Section {sec['number']}" + (f" — {sec['heading']}"
                                                       if sec["heading"] else ""))
        ch = prov.get(p["chapter"]) if p.get("chapter") else None
        if ch:
            parts.append(f"Chapter {ch['label']} — {ch['heading']}")
    return " · ".join(parts)


def _cite(p: dict) -> str:
    if p["kind"] in ("section", "paragraph"):
        return p["number"]
    if p.get("schedule"):
        return p["number"]
    return f"section {p['number']}"


def _subtree_text(pid: str, prov: dict[str, dict], depth: int = 0) -> str:
    p = prov[pid]
    own = p["text"]
    if p["kind"] in ("section", "paragraph"):
        head = f"{p['label']}. " + (f"[{p['heading']}] " if p["heading"] else "")
        line = head + own
    elif p["kind"] == "table":
        line = own  # rows are their own chunks
    else:
        line = f"{p['label']} {own}".strip()
    parts = [line] if line.strip() else []
    for c in p["children"]:
        if prov[c]["kind"] == "table":
            parts.append(f"[Table {prov[c]['number']} — see table rows]")
        else:
            parts.append(_subtree_text(c, prov, depth + 1))
    return "\n".join(x for x in parts if x)


def _subtree_ids(pid: str, prov: dict[str, dict]) -> list[str]:
    out = [pid]
    for c in prov[pid]["children"]:
        if prov[c]["kind"] != "table":
            out.extend(_subtree_ids(c, prov))
    return out


def _table_name(table_id: str) -> str:
    """"s393:tbl2" -> "Section 393, Table 2"; "sch:III:tbl1" -> "Schedule III, Table"."""
    owner, _, k = table_id.rpartition(":tbl")
    m = re.match(r"^s(\d+)$", owner.split(":")[0])
    base = f"Section {m.group(1)}" if m else "Schedule " + owner.split(":")[1]
    return f"{base}, Table" + (f" {k}" if k != "1" or table_id.startswith("s393") else "")


def _pages(ids: list[str], prov: dict[str, dict]) -> tuple[int, int]:
    return (min(prov[i]["page_start"] for i in ids), max(prov[i]["page_end"] for i in ids))


def structural_chunks(version: str, provisions: list[dict], rows: list[dict],
                      tables: list[dict]) -> list[Chunk]:
    prov = {p["id"]: p for p in provisions}
    chunks: list[Chunk] = []

    def emit(pid: str, text: str, ids: list[str], lead: str = "", cid_base: str = "") -> None:
        p = prov[pid]
        crumb = _breadcrumb(p, prov)
        header = f"{crumb}\n" if crumb else ""
        if lead:  # the parent's opening words, e.g. '(5) "agricultural income" means—'
            header += f"{lead} ...\n"
        header += f"{_cite(p)}:\n"
        ps, pe = _pages(ids, prov)
        body_toks = tokens.encode(text)
        if len(body_toks) <= SPLIT_TOKENS:
            pieces = [text]
        else:
            step = WINDOW - OVERLAP
            pieces = [tokens.decode(body_toks[s:s + WINDOW])
                      for s in range(0, len(body_toks), step)]
        for k, piece in enumerate(pieces):
            cid = (cid_base or f"{version}:{pid}") + (f"@{k + 1}" if len(pieces) > 1 else "")
            chunks.append(Chunk(cid, version, piece, header + piece, ps, pe, pid,
                                {"provisions": ids, "breadcrumb": crumb, "kind": p["kind"]}))

    def walk(pid: str, lead: str = "") -> None:
        p = prov[pid]
        if p["kind"] in ("preamble", "chapter", "part", "schedule", "schedule-part"):
            if p["text"].strip() and p["kind"] in ("schedule", "preamble"):
                emit(pid, p["text"], [pid])
            for c in p["children"]:
                walk(c)
            return
        if p["kind"] == "table":
            return
        text = _subtree_text(pid, prov)
        if tokens.count(text) <= MAX_TOKENS or not [c for c in p["children"]
                                                    if prov[c]["kind"] != "table"]:
            emit(pid, text, _subtree_ids(pid, prov), lead)
            return
        # too big: this node's own text (with its label) as one chunk, then each child, which
        # carries this node's opening words so "(b) any income derived from such land" still
        # says what it defines
        own = _subtree_text(pid, {**prov, pid: {**p, "children": []}})
        if own.strip():
            emit(pid, own, [pid], lead)
        child_lead = (lead + " " if lead else "") + own.split("\n")[0][:160]
        for c in p["children"]:
            walk(c, child_lead.strip())

    roots = [p["id"] for p in provisions if p["parent"] is None]
    for r in roots:
        walk(r)

    # one chunk per table (sub-)row, with the table title and column headings spelled out
    tmeta = {t["table_id"]: t for t in tables}
    for r in rows:
        t = tmeta[r["table_id"]]
        owner = prov[r["table_id"]]
        crumb = _breadcrumb(owner, prov)
        title = _table_name(r["table_id"]) + (f" ({t['title']})" if t["title"] else "")
        cells = "\n".join(f"{k}: {v}" for k, v in r["cells"].items()
                          if v and not k.lower().startswith("sl"))
        head = f"Sl. No. {r['sl_label']}" + (f" — {r['row_heading']}" if r["row_heading"] else "")
        text = f"{title}, {head}\n{cells}"
        chunks.append(Chunk(f"{version}:{r['row_id']}", version, text,
                            f"{crumb}\n{text}" if crumb else text, r["page_start"],
                            r["page_end"], r["table_id"],
                            {"provisions": [r["row_id"], r["table_id"]], "kind": "table_row",
                             "breadcrumb": crumb}))
    # table notes (e.g. section 393 "Note 1.—...") as their own chunks
    for t in tables:
        if t["notes"]:
            owner = prov[t["table_id"]]
            name = _table_name(t["table_id"]) + (f" ({t['title']})" if t["title"] else "")
            for n, note in enumerate(t["notes"], 1):  # one chunk per note: they are cited singly
                emit(t["table_id"], f"Note to {name}: {note}", [t["table_id"]],
                     cid_base=f"{version}:{t['table_id']}:note{n}")
    return chunks


def build_chunks(version: str, artefacts: dict) -> list[Chunk]:
    if version == "v0":
        return window_chunks("v0", artefacts["pages_raw"], artefacts["provisions"],
                             artefacts["rows"])
    if version == "v1":
        return window_chunks("v1", artefacts["pages_clean"], artefacts["provisions"],
                             artefacts["rows"])
    if version == "v2":
        return structural_chunks("v2", artefacts["provisions"], artefacts["rows"],
                                 artefacts["tables"])
    raise ValueError(f"no chunker for {version}")
