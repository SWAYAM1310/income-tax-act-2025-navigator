"""Amendment endnotes: detection, parsing and linking to provisions.

In this PDF each group of sections is followed by its endnotes, e.g. section 2's notes sit on
pp. 10-11 while the amended clause 2(32) is on p. 4. Numbering runs continuously ("1", "2", "3",
"3a", ...) and restarts once (p. 505). A body marker {{fn:N}} is linked to the first endnote with
the same label that appears *after* it in the line stream.

Endnote header variants seen in the Act:
  1. Sub. by the Act No. 4 of 2026, w.e.f. 1-4-2026. Prior to its substitution, clause (32)
     read as under :
  4. Sub. for "(f)" by Act No. 4 of 2026, w.e.f. 1-4-2026.
  3a. Items (II) and (III) sub. for item (II) by the Act No. 4 of 2026, ...
  20. Words "or section 144" omtt. by Act No. 4 of 2026, w.e.f. 1-4-2026.
  84. Shall be renumbered as sub-section (6)(a) thereof ...
  37. Sl. Nos. 38A to 38D inserted ...
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

FOOTNOTE_START_RE = re.compile(r"^(\d+[a-z]?)\.+\s*(.*)$")  # "51.. Sub. for" occurs once
AMENDING_ACT_RE = re.compile(r"(?:the\s+)?Act No\.\s*(\d+)\s+of\s+(\d{4})")
WEF_RE = re.compile(r"w\.e\.f\.\s*([0-9]{1,2}-[0-9]{1,2}-[0-9]{4})")
PRIOR_RE = re.compile(
    r"Prior to (?:its|their) (substitution|omission|insertion)[^:]*?read as under\s*:",
                      re.I)
TARGET_RE = re.compile(
    r"Prior to (?:its|their) \w+,\s*(.*?)\s+read as under", re.I)


@dataclass
class Footnote:
    key: str  # unique: "<label>@<line index>"
    label: str  # "1", "3a"
    page: int
    line_index: int  # position of the header line in the global line stream
    header: str  # first paragraph (up to "read as under :")
    prior_text: str | None
    type: str  # substituted | inserted | omitted | renumbered | other
    amending_act: str | None  # "Act No. 4 of 2026"
    effective_date: str | None  # "1-4-2026"
    target_desc: str | None  # e.g. 'clause (32)', 'Words "or section 144"'
    linked_nodes: list[str] = field(default_factory=list)  # every provision carrying the marker
    link_method: str | None = None

    @property
    def linked_node(self) -> str | None:
        return self.linked_nodes[0] if self.linked_nodes else None
    raw_lines: list[str] = field(default_factory=list)


def classify(header: str) -> str:
    h = header
    if re.search(r"\brenumbered\b", h, re.I):
        return "renumbered"
    if re.search(r"\bSub\.|\bsub\.(?=\s+for|\s+by)|\bsubstituted\b", h):
        return "substituted"
    if re.search(r"\bIns\.|\bins\.(?=\s+by)|\binserted\b", h):
        return "inserted"
    if re.search(r"\bOmtt\.|\bomtt\.|\bomitted\b", h, re.I):
        return "omitted"
    return "other"


def looks_like_footnote_start(text: str) -> bool:
    """A footnote header line: '<label>. <something>' mentioning an amendment."""
    m = FOOTNOTE_START_RE.match(text.strip())
    if not m:
        return False
    rest = m.group(2)
    return bool(re.search(
        r"\b(Sub|Ins|Omtt)\.|\b(sub|ins|omtt)\.\s+(for|by)|Act No\.|renumbered|inserted|omitted"
        r"|substituted", rest))


def parse_block(lines: list[tuple[int, int, str]]) -> list[Footnote]:
    """Parse one endnote block. `lines` are (line_index, page, text) in stream order."""
    notes: list[Footnote] = []
    cur: list[tuple[int, int, str]] = []

    def flush() -> None:
        if cur:
            notes.append(_build(cur))

    for item in lines:
        if looks_like_footnote_start(item[2]) and not item[2].lstrip().startswith("'"):
            flush()
            cur = [item]
        elif cur:
            cur.append(item)
    flush()
    return notes


def _build(items: list[tuple[int, int, str]]) -> Footnote:
    line_index, page, first = items[0]
    label = FOOTNOTE_START_RE.match(first.strip()).group(1)
    body = " ".join(t.strip() for _, _, t in items)
    body = re.sub(r"\s+", " ", body)
    body = re.sub(r"^\d+[a-z]?\.+\s*", "", body)  # drop "N."
    m = PRIOR_RE.search(body)
    if m:
        header, prior = body[:m.end()].strip(), body[m.end():].strip()
        prior = prior.strip().strip("'‘’").strip()
    else:
        header, prior = body, None
    act = AMENDING_ACT_RE.search(header)
    wef = WEF_RE.search(header)
    tgt = TARGET_RE.search(header)
    target = tgt.group(1) if tgt else _target_before_verb(header)
    return Footnote(
        key=f"{label}@{line_index}", label=label, page=page, line_index=line_index,
        header=header, prior_text=prior or None, type=classify(header),
        amending_act=f"Act No. {act.group(1)} of {act.group(2)}" if act else None,
        effective_date=wef.group(1) if wef else None, target_desc=target,
        raw_lines=[t for _, _, t in items],
    )


def _target_before_verb(header: str) -> str | None:
    """'Words "or section 144" omtt. by ...' -> 'Words "or section 144"'."""
    m = re.match(r"^(.*?)\s+(?:sub\.|ins\.|omtt\.|inserted|omitted|substituted)\b", header)
    if m and not re.match(r"^(Sub|Ins|Omtt)\.$", m.group(1)):
        return m.group(1).strip() or None
    m = re.match(r"^Sub\. for (\".*?\")", header)
    return m.group(1) if m else None
