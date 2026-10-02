"""Structure parser: clean line stream -> provision tree, tables and amendment endnotes.

Hierarchy of the Income-tax Act, 2025 (verified against the PDF):
  CHAPTER (I-XXIII) -> optional Part ("A.-Heads of income") -> section (1-536)
    -> labelled levels, nested by label style:
       (1) sub-section -> (a) clause -> (i) sub-clause -> (A) item -> (I) sub-item
  SCHEDULE (I-XVI) -> optional PART A/B/C -> paragraph (1., 2., ...) -> labelled levels
This Act has no provisos or Explanations. Tables are cut out of the stream and become `table`
nodes whose rows live in tables.py output. Endnote blocks are routed to footnotes.py.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from statnav.ingest.footnotes import (
    FOOTNOTE_START_RE,
    Footnote,
    looks_like_footnote_start,
    parse_block,
)
from statnav.ingest.pdf_layout import FN_TOKEN_RE, Line
from statnav.ingest.tables import (
    BODY_LEFT_MAX,
    Table,
    clean,
    find_tables,
    is_section_number_span,
    is_table_heading,
)

ROMAN_UPPER = {"I": 1, "V": 5, "X": 10, "L": 50, "C": 100, "D": 500, "M": 1000}
RANK = {"num": 0, "alpha": 1, "roman": 2, "ALPHA": 3, "ROMAN": 4}
ALIGN = 7.0  # x tolerance for labels at the same level
TAIL_RE = re.compile(r"^\s*but\s+(?:does|shall)\s+not\s+include")
DEEPER = 10.0  # x offset that marks a label as one level deeper than the open node
NOT_A_LABEL_AFTER_RE = re.compile(r"^\s*(?:[;,.:)\]\u2014\u2013-]|and\b|or\b|$)")
FIRST_LABEL = {"num": {"1"}, "alpha": {"a"}, "roman": {"i"}, "ALPHA": {"A"}, "ROMAN": {"I"}}
KIND = {"num": "sub-section", "alpha": "clause", "roman": "sub-clause", "ALPHA": "item",
        "ROMAN": "sub-item"}

# a leading label, optionally preceded by footnote tokens and an opening amendment bracket
LEAD_RE = re.compile(r"^((?:\{\{fn:[0-9a-z]+\}\}|\[|\s)*)\(([0-9]+[A-Z]*|[a-z]{1,6}|[A-Z]{1,6})\)")
CHAPTER_RE = re.compile(r"^CHAPTER\s+([IVXL]+)$")
SCHEDULE_RE = re.compile(r"^SCHEDULE\s+([IVXL]+)$")
SCHED_PART_RE = re.compile(r"^PART\s+([A-Z])$")
PART_RE = re.compile(r"^([A-H])\.\s*[—\-]\s*(.+)$")
SEE_SECTION_RE = re.compile(r"^\[See sections?\s+(.+)\]$")


def roman_value(s: str) -> int | None:
    s = s.upper()
    if not s or any(c not in ROMAN_UPPER for c in s):
        return None
    total = 0
    for i, c in enumerate(s):
        v = ROMAN_UPPER[c]
        total += -v if i + 1 < len(s) and ROMAN_UPPER[s[i + 1]] > v else v
    return total if to_roman(total) == s else None


def to_roman(n: int) -> str:
    out = ""
    for v, sym in ((1000, "M"), (900, "CM"), (500, "D"), (400, "CD"), (100, "C"), (90, "XC"),
                   (50, "L"), (40, "XL"), (10, "X"), (9, "IX"), (5, "V"), (4, "IV"), (1, "I")):
        while n >= v:
            out += sym
            n -= v
    return out


def alpha_succ(s: str) -> str:
    if s[-1] != "z":
        return s[:-1] + chr(ord(s[-1]) + 1)
    return s + "a"


def is_alpha_label(s: str) -> bool:
    # (a), (za), (zza); inserted clauses like (fa) between (f) and (g)
    return len(s) == 1 or (s[0] == "z" and len(s) <= 4) or (len(s) == 2 and not roman_value(s))


def is_next_label(prev: str, lab: str, cls: str) -> bool:
    """Does `lab` continue the sequence after `prev` (allowing one skipped or an inserted label)?"""
    if cls == "num":
        pm, lm = re.match(r"(\d+)([A-Z]*)", prev), re.match(r"(\d+)([A-Z]*)", lab)
        pn, ln_ = int(pm.group(1)), int(lm.group(1))
        return pn < ln_ <= pn + 2 or (ln_ == pn and lm.group(2) > pm.group(2))
    if cls in ("alpha", "ALPHA"):
        p_, l_ = prev.lower(), lab.lower()
        nxt = alpha_succ(p_)
        if l_ in (nxt, alpha_succ(nxt)) or (l_.startswith(p_) and len(l_) == len(p_) + 1):
            return True
        # after an inserted clause "(fa)" the sequence resumes at "(g)"
        return len(p_) == 2 and p_[0] != "z" and l_ == alpha_succ(p_[0])
    pv, lv = roman_value(prev), roman_value(lab)
    return pv is not None and lv is not None and pv < lv <= pv + 2


def label_x(line: Line) -> float:
    """x of the label's "(", ignoring a leading amendment bracket ("[(7) ...")."""
    for span in line.spans:
        t = span.text.lstrip()
        if not t:
            continue
        if t.startswith("("):
            return span.bbox[0]
        if t.startswith("["):
            n = len(t) - len(t.lstrip("["))
            return span.bbox[0] + 2.8 * n if t.lstrip("[") else span.bbox[2]
        break
    return line.x0


def label_classes(lab: str) -> list[str]:
    if lab[0].isdigit():
        return ["num"]
    out = []
    if lab.islower():
        if is_alpha_label(lab):
            out.append("alpha")
        if roman_value(lab):
            out.append("roman")
    elif lab.isupper():
        if len(lab) == 1:
            out.append("ALPHA")
        if roman_value(lab):
            out.append("ROMAN")
    return out


@dataclass
class Node:
    id: str
    kind: str
    number: str  # citation path, e.g. "2(5)(b)" or "Schedule XI, Part A, paragraph 2(a)"
    label: str | None
    heading: str | None
    parent: str | None
    chapter: str | None
    part: str | None
    schedule: str | None
    page_start: int
    page_end: int
    cls: str | None = None  # label class for labelled nodes
    x0: float = 0.0  # x of the label (indentation)
    chained: bool = False  # second label on its line, e.g. the (i) in "(5)(i)"
    texts: list[str] = field(default_factory=list)
    children: list[str] = field(default_factory=list)
    fn_labels: list[str] = field(default_factory=list)
    line_indices: list[int] = field(default_factory=list)

    @property
    def text(self) -> str:
        return re.sub(r"\s+", " ", " ".join(self.texts)).strip()

    @property
    def clean_text(self) -> str:
        return re.sub(r"\s+", " ", FN_TOKEN_RE.sub("", self.text)).strip()


@dataclass
class ParseResult:
    nodes: dict[str, Node]
    tables: list[Table]
    table_owner: dict[int, str]  # table index -> node id
    footnotes: list[Footnote]
    warnings: list[str]


class _Parser:
    def __init__(self, lines: list[Line]):
        self.lines = lines
        self.nodes: dict[str, Node] = {}
        self.warnings: list[str] = []
        self.tables = find_tables(lines)
        self.table_at = {t.start_line: t for t in self.tables}
        self.table_owner: dict[int, str] = {}
        self.footnotes: list[Footnote] = []
        self.chapter: Node | None = None
        self.part: Node | None = None
        self.schedule: Node | None = None
        self.sched_part: Node | None = None
        self.unit: Node | None = None  # current section or schedule paragraph
        self.stack: list[Node] = []  # labelled nodes under self.unit
        self.last_section = 0
        self.last_para = 0
        self.pending_heading: list[tuple[int, Line]] = []
        self.pending_fn: set[str] = set()
        self.marker_occ: list[tuple[str, int, str]] = []  # (label, line index, node id)
        self.root = self._add(Node("preamble", "preamble", "Preamble", None, None, None, None,
                                   None, None, 1, 1))

    # -- helpers ---------------------------------------------------------------------------
    def _add(self, node: Node) -> Node:
        base, k = node.id, 2
        while node.id in self.nodes:
            node.id = f"{base}~{k}"
            k += 1
        if node.id != base:
            self.warnings.append(f"duplicate id {base} on p{node.page_start}")
        self.nodes[node.id] = node
        if node.parent:
            self.nodes[node.parent].children.append(node.id)
        return node

    def _ctx(self) -> dict:
        return {
            "chapter": self.chapter.id if self.chapter else None,
            "part": (self.sched_part or self.part).id if (self.sched_part or self.part) else None,
            "schedule": self.schedule.id if self.schedule else None,
        }

    def _container(self) -> Node:
        if self.unit is not None:
            return self.unit
        for n in (self.sched_part, self.schedule, self.part, self.chapter):
            if n is not None:
                return n
        return self.root

    def _append_text(self, node: Node, text: str, idx: int, page: int) -> None:
        node.texts.append(text)
        node.line_indices.append(idx)
        node.page_end = max(node.page_end, page)
        for lab in FN_TOKEN_RE.findall(text):
            self._marker(lab, idx, node)
        # propagate page span to ancestors
        p = node.parent
        while p:
            anc = self.nodes[p]
            anc.page_end = max(anc.page_end, page)
            p = anc.parent

    def _marker(self, lab: str, idx: int, node: Node) -> None:
        node.fn_labels.append(lab)
        self.pending_fn.add(lab)
        self.marker_occ.append((lab, idx, node.id))

    def _close_unit(self) -> None:
        self.unit = None
        self.stack = []

    # -- line classification ---------------------------------------------------------------
    def _is_endnote_start(self, line: Line) -> bool:
        t = clean(line.text)
        if line.x0 > 36 or line.first_span.bold:
            return False
        m = FOOTNOTE_START_RE.match(t)
        if not m or m.group(1) not in self.pending_fn:
            return False
        return looks_like_footnote_start(t)

    def _is_boundary(self, i: int) -> bool:
        line = self.lines[i]
        t = clean(line.text)
        nxt = self.lines[i + 1] if i + 1 < len(self.lines) else None
        if is_table_heading(line) or is_section_number_span(line):
            return True
        if line.all_bold and line.x0 < BODY_LEFT_MAX and nxt is not None \
                and is_section_number_span(nxt):
            return True
        if "BoldItal" in line.first_span.font:
            return True
        return bool(PART_RE.match(t) and line.first_span.italic and line.x0 > 150)

    # -- main loop -------------------------------------------------------------------------
    def run(self) -> ParseResult:
        i = 0
        n = len(self.lines)
        while i < n:
            line = self.lines[i]
            t = clean(line.text)
            if i in self.table_at:
                i = self._table(i)
                continue
            if self._is_endnote_start(line):
                i = self._endnotes(i)
                continue
            line, nxt_i = self._merged(i)
            t = clean(line.text)
            first = line.first_span
            if "BoldItal" in first.font and CHAPTER_RE.match(t):
                i = self._chapter(i)
                continue
            if "BoldItal" in first.font and SCHEDULE_RE.match(t):
                i = self._schedule(i)
                continue
            if "BoldItal" in first.font and SCHED_PART_RE.match(t) and self.schedule:
                i = self._sched_part(i)
                continue
            if PART_RE.match(t) and first.italic and line.x0 > 150 and self.chapter:
                self._part(i)
                i += 1
                continue
            if is_section_number_span(line):
                num = int(re.match(r"^(\d+)", t).group(1))
                if self._accept_unit_number(num, line):
                    self._unit_start(i, num, line)
                    i = nxt_i
                    continue
            if line.all_bold and line.x0 < BODY_LEFT_MAX and not LEAD_RE.match(line.text.strip()) \
                    and not t.isupper():
                self.pending_heading.append((i, line))
                i = nxt_i
                continue
            self._flush_heading_as_text()
            self._body_line(i, line)
            i = nxt_i
        self._link_footnotes()
        return ParseResult(self.nodes, self.tables, self.table_owner, self.footnotes,
                           self.warnings)

    def _accept_unit_number(self, num: int, line: Line) -> bool:
        if self.schedule is None:
            if num == self.last_section + 1:
                return True
            if self.last_section < num <= self.last_section + 3:
                self.warnings.append(f"section gap {self.last_section}->{num} p{line.page}")
                return True
            return False
        return num == self.last_para + 1 or (num == 1 and self.last_para == 0)

    def _flush_heading_as_text(self) -> None:
        for k, ln in self.pending_heading:
            self._append_text(self._container(), ln.text, k, ln.page)
        self.pending_heading = []

    # -- structural events ------------------------------------------------------------------
    def _chapter(self, i: int) -> int:
        self._flush_heading_as_text()
        self._close_unit()
        roman = CHAPTER_RE.match(clean(self.lines[i].text)).group(1)
        j, title = self._title_lines(i + 1)
        self.part = None
        self.chapter = self._add(Node(
            f"ch:{roman}", "chapter", f"Chapter {roman}", roman, title, None, None, None, None,
            self.lines[i].page, self.lines[i].page))
        self.chapter.chapter = self.chapter.id
        return j

    def _part(self, i: int) -> None:
        self._flush_heading_as_text()
        self._close_unit()
        m = PART_RE.match(clean(self.lines[i].text))
        letter, title = m.group(1), m.group(2).strip()
        self.part = self._add(Node(
            f"{self.chapter.id}:{letter}", "part", f"Chapter {self.chapter.label}-{letter}",
            letter, title, self.chapter.id, self.chapter.id, None, None,
            self.lines[i].page, self.lines[i].page))
        self.part.part = self.part.id

    def _schedule(self, i: int) -> int:
        self._flush_heading_as_text()
        self._close_unit()
        roman = SCHEDULE_RE.match(clean(self.lines[i].text)).group(1)
        j = i + 1
        see = None
        if j < len(self.lines) and SEE_SECTION_RE.match(clean(self.lines[j].text)):
            see = SEE_SECTION_RE.match(clean(self.lines[j].text)).group(1)
            j += 1
        j, title = self._title_lines(j)
        self.chapter = self.part = self.sched_part = None
        self.last_para = 0
        self.schedule = self._add(Node(
            f"sch:{roman}", "schedule", f"Schedule {roman}", roman, title, None, None, None,
            None, self.lines[i].page, self.lines[i].page))
        self.schedule.schedule = self.schedule.id
        if see:
            self.schedule.texts.append(f"[See section {see}]")
        return j

    def _sched_part(self, i: int) -> int:
        self._flush_heading_as_text()
        self._close_unit()
        letter = SCHED_PART_RE.match(clean(self.lines[i].text)).group(1)
        j, title = self._title_lines(i + 1)
        self.last_para = 0
        s = self.schedule
        self.sched_part = self._add(Node(
            f"{s.id}:{letter}", "schedule-part", f"Schedule {s.label}, Part {letter}", letter,
            title, s.id, None, None, s.id, self.lines[i].page, self.lines[i].page))
        self.sched_part.part = self.sched_part.id
        return j

    def _title_lines(self, j: int) -> tuple[int, str]:
        parts = []
        while j < len(self.lines):
            ln = self.lines[j]
            t = clean(ln.text)
            if t and t.isupper() and ln.x0 > 30 and not is_table_heading(ln) \
                    and "BoldItal" not in ln.first_span.font and not PART_RE.match(t):
                parts.append(t)
                j += 1
                continue
            break
        return j, " ".join(parts)

    def _unit_start(self, i: int, num: int, line: Line) -> None:
        heading = " ".join(clean(ln.text) for _, ln in self.pending_heading) or None
        heading_fns = [(lab, k) for k, ln in self.pending_heading
                       for lab in FN_TOKEN_RE.findall(ln.text)]
        page0 = self.pending_heading[0][1].page if self.pending_heading else line.page
        self.pending_heading = []
        self._close_unit()
        ctx = self._ctx()
        if self.schedule is None:
            self.last_section = num
            node = Node(f"s{num}", "section", str(num), str(num), heading,
                        (self.part or self.chapter or self.root).id, ctx["chapter"], ctx["part"],
                        None, page0, line.page, x0=line.x0)
        else:
            self.last_para = num
            owner = self.sched_part or self.schedule
            prefix = owner.number
            node = Node(f"{owner.id}:{num}", "paragraph", f"{prefix}, paragraph {num}", str(num),
                        heading, owner.id, None, ctx["part"], self.schedule.id, page0, line.page,
                        x0=line.x0)
        self.unit = self._add(node)
        for lab, k in heading_fns:
            self._marker(lab, k, self.unit)
        rest = re.sub(r"^\s*\d+\s*\.\s*", "", line.text, count=1)
        if rest.strip():
            self._labelled_text(i, line, rest)

    # -- body text ---------------------------------------------------------------------------
    def _merged(self, i: int) -> tuple[Line, int]:
        """Join PyMuPDF fragments of one visual line ("(o) " + "{{fn:31}}[***]")."""
        parts = [self.lines[i]]
        j = i + 1
        while j < len(self.lines) and j not in self.table_at:
            nl, last = self.lines[j], parts[-1]
            if nl.page == last.page and abs(nl.y0 - last.y0) < 2.5 and nl.x0 > last.bbox[2] - 1:
                parts.append(nl)
                j += 1
            else:
                break
        if len(parts) == 1:
            return parts[0], i + 1
        bbox = (parts[0].bbox[0], min(p.bbox[1] for p in parts), parts[-1].bbox[2],
                max(p.bbox[3] for p in parts))
        text = " ".join(p.text.rstrip() for p in parts)
        return Line(parts[0].page, bbox, [s for p in parts for s in p.spans], text), j

    def _body_line(self, i: int, line: Line) -> None:
        if self.unit is None:
            self._append_text(self._container(), line.text, i, line.page)
            return
        self._labelled_text(i, line, line.text)

    def _labelled_text(self, i: int, line: Line, text: str) -> None:
        """Consume leading labels ("(1)(a) ...", "{{fn:3}}[(v) ...") and attach the text."""
        prefix = ""
        rest = text
        target = None
        x = label_x(line)
        while True:
            m = LEAD_RE.match(rest.lstrip())
            if not m:
                break
            lab = m.group(2)
            after = rest.lstrip()[m.end():]
            if NOT_A_LABEL_AFTER_RE.match(after):
                break  # "(1);", "(a) and (b)": a wrapped cross-reference, not a label
            if lab in ("ii", "II"):
                self._fix_misread_i(lab)
            cls = self._decide(lab, x)
            if cls is not None and not self._plausible(lab, cls, x):
                other = [c for c in label_classes(lab) if c != cls]
                cls = other[0] if other and self._plausible(lab, other[0], x) else None
            if cls is None:
                break
            prefix += m.group(1)
            rest = rest.lstrip()[m.end():]
            target = self._push(lab, cls, x, line.page, chained=target is not None,
                                bracketed="[" in m.group(1))
            x = target.x0  # a chained label shares the (bracket-corrected) column
        if target is None:
            target = self._continuation_target(line.x0, rest)
        body = (prefix.strip() + " " + rest.strip()).strip()
        self._append_text(target, body, i, line.page)

    def _decide(self, lab: str, x: float) -> str | None:
        cands = label_classes(lab)
        if not cands:
            return None
        if len(cands) == 1:
            return cands[0]
        lower = cands[0].islower()
        a_cls, r_cls = ("alpha", "roman") if lower else ("ALPHA", "ROMAN")
        open_a = next((n for n in reversed(self.stack) if n.cls == a_cls), None)
        open_r = next((n for n in reversed(self.stack) if n.cls == r_cls), None)
        if (open_r is not None
                and to_roman(roman_value(open_r.label.strip("()")) + 1) == lab.upper()):
            return r_cls
        if open_a is not None and alpha_succ(open_a.label.strip("()").lower()) == lab.lower():
            # "(i)" right after "(h)": sibling clause, or first sub-clause of (h)?
            if lab.lower() == "i" and x > open_a.x0 + 8:
                return r_cls
            return a_cls
        if lab.lower() == "i":
            return r_cls
        # fall back to indentation: closest open node of either class
        da = abs(x - open_a.x0) if open_a else 1e9
        dr = abs(x - open_r.x0) if open_r else 1e9
        return a_cls if da <= dr else r_cls

    def _plausible(self, lab: str, cls: str, x: float) -> bool:
        """Is `lab` the next label of an open sequence, or the first label of a new level?

        Rejects cross-references that happen to start a wrapped line, e.g. "(b)(ii) and (iii)
        is carried on" inside clause (c).
        """
        if lab in FIRST_LABEL[cls]:
            # a first label can't restart a sequence that is open at the same indentation,
            # e.g. a wrapped "...sub-section / (1) apply shall..." inside sub-section (7)
            return self._open_sibling(cls, x, aligned_only=True) is None
        open_same = self._open_sibling(cls, x)
        if open_same is None:
            return False
        return is_next_label(open_same.label.strip("()"), lab, cls)

    def _sequence_sibling(self, lab: str, cls: str, x: float, bracketed: bool) -> Node | None:
        """An open node this label continues ("(4)" -> "(5)"), even if an amendment bracket
        pushed the label right of its normal column."""
        for n in reversed(self.stack):
            if (n.cls == cls and is_next_label(n.label.strip("()"), lab, cls)
                    and (bracketed or abs(n.x0 - x) <= 12)):
                return n
        return None

    def _open_sibling(self, cls: str, x: float, aligned_only: bool = False) -> Node | None:
        """The open node of the same label style at (about) the same indentation."""
        same = [n for n in self.stack if n.cls == cls]
        if not same:
            return None
        # a chained label ("(5)(i)") has no column of its own, so it aligns with any sibling
        aligned = [n for n in same if n.chained or abs(n.x0 - x) <= ALIGN]
        if aligned:
            return aligned[-1]
        return None if aligned_only else same[-1]

    def _fix_misread_i(self, lab: str) -> None:
        """"(i)" right after "(h)" was read as a clause; a following "(ii)" proves it opened a
        sub-clause list under (h). Reclassify it and move it (and its subtree) under (h)."""
        a_cls, r_cls = ("alpha", "roman") if lab.islower() else ("ALPHA", "ROMAN")
        if any(n.cls == r_cls for n in self.stack):
            return
        node = next((n for n in reversed(self.stack)
                     if n.cls == a_cls and n.label.strip("()").lower() == "i"), None)
        if node is None:
            return
        parent = self.nodes[node.parent]
        k = parent.children.index(node.id)
        if k == 0:
            return
        new_parent = self.nodes[parent.children[k - 1]]  # the "(h)" clause
        parent.children.pop(k)
        self._rename(node, new_parent)
        node.cls, node.kind = r_cls, KIND[r_cls]
        new_parent.children.append(node.id)
        idx = self.stack.index(node)
        self.stack.insert(idx, new_parent)

    def _rename(self, node: Node, new_parent: Node) -> None:
        old_id, old_number = node.id, node.number
        del self.nodes[old_id]
        node.id = f"{new_parent.id}{node.label}"
        node.number = f"{new_parent.number}{node.label}"
        node.parent = new_parent.id
        self.nodes[node.id] = node
        for cid in list(node.children):
            child = self.nodes[cid]
            node.children[node.children.index(cid)] = cid.replace(old_id, node.id, 1)
            self._rename(child, node)
        _ = old_number

    def _push(self, lab: str, cls: str, x: float, page: int, chained: bool = False,
              bracketed: bool = False) -> Node:
        rank = RANK[cls]
        sibling = (self._sequence_sibling(lab, cls, x, bracketed)
                   or self._open_sibling(cls, x, aligned_only=True))
        if sibling is not None and bracketed:
            x = sibling.x0  # keep the column of the sequence, not the shifted bracket
        if sibling is not None:
            # same style at the same indentation: close everything down to that sibling
            while self.stack and self.stack[-1] is not sibling:
                self.stack.pop()
            self.stack.pop()
        elif self.stack and x > self.stack[-1].x0 + DEEPER:
            # indentation wins over label style: a clearly deeper label is a child even when
            # its style ranks higher (e.g. a sixth-level "(a)" under item "(I)" in 32(e))
            pass
        else:
            # close nodes indented deeper than this label, and same-column nodes whose style
            # ranks at or below it; label style alone is not reliable ("(5)(i)" then "(a)")
            while self.stack and (
                    self.stack[-1].x0 > x + ALIGN
                    or (abs(self.stack[-1].x0 - x) <= ALIGN and RANK[self.stack[-1].cls] >= rank)
                    or (self.stack[-1].chained and RANK[self.stack[-1].cls] >= rank)):
                self.stack.pop()
        parent = self.stack[-1] if self.stack else self.unit
        lab_text = f"({lab})"
        node = Node(
            f"{parent.id}{lab_text}", KIND[cls], f"{parent.number}{lab_text}", lab_text, None,
            parent.id, parent.chapter, parent.part, parent.schedule, page, page, cls=cls, x0=x,
            chained=chained)
        node = self._add(node)
        self.stack.append(node)
        return node

    def _continuation_target(self, x: float, text: str = "") -> Node:
        """Unlabelled line: continue the deepest node, or a shallower one if dedented."""
        if not self.stack:
            return self.unit
        if TAIL_RE.match(FN_TOKEN_RE.sub("", text)):
            # "but does not include—" after a list qualifies the list's parent, e.g. 2(40):
            # the exclusions that follow are sub-clauses (i)-(v) of clause (40), not of (f)
            self.stack.pop()
            return self.stack[-1] if self.stack else self.unit
        deepest = self.stack[-1]
        if x >= deepest.x0 - 3:
            return deepest
        # dedented ("where,-" back at the definition's level): close the deeper nodes so that
        # a following list nests under the node this text belongs to
        while self.stack and x < self.stack[-1].x0 - 3:
            self.stack.pop()
        return self.stack[-1] if self.stack else self.unit

    # -- tables and endnotes -------------------------------------------------------------------
    def _table(self, i: int) -> int:
        self._flush_heading_as_text()
        table = self.table_at[i]
        owner = self.stack[-1] if self.stack else self._container()
        unit = self.unit or self._container()
        k = sum(1 for t_owner in self.table_owner.values()
                if t_owner.split(":tbl")[0] == unit.id) + 1
        node = self._add(Node(
            f"{unit.id}:tbl{k}", "table", f"{unit.number} (Table{' ' + str(k) if k > 1 else ''})",
            None, table.title or None, owner.id, owner.chapter, owner.part, owner.schedule,
            table.page_start, table.page_end))
        node.texts.append(f"[TABLE {table.title}]".strip())
        for k in range(table.start_line, table.end_line):
            for lab in FN_TOKEN_RE.findall(self.lines[k].text):
                self._marker(lab, k, node)
        node.line_indices.append(table.start_line)
        self.table_owner[table.index] = node.id
        return table.end_line

    def _endnotes(self, i: int) -> int:
        self._flush_heading_as_text()
        items = []
        j = i
        while j < len(self.lines) and (j == i or not self._is_boundary(j)):
            ln = self.lines[j]
            items.append((j, ln.page, ln.text))
            j += 1
        for fn in parse_block(items):
            self.footnotes.append(fn)
            self.pending_fn.discard(fn.label)
        return j

    def _link_footnotes(self) -> None:
        """Each body marker links to the first endnote with the same label after it."""
        by_label: dict[str, list[Footnote]] = {}
        for fn in self.footnotes:
            by_label.setdefault(fn.label, []).append(fn)
        for lab, idx, node_id in self.marker_occ:
            cands = [f for f in by_label.get(lab, []) if f.line_index > idx]
            if not cands:
                self.warnings.append(f"marker {lab} in {node_id} has no endnote")
                continue
            fn = cands[0]
            if node_id not in fn.linked_nodes:
                fn.linked_nodes.append(node_id)
                fn.link_method = "marker"


def parse(lines: list[Line]) -> ParseResult:
    return _Parser(lines).run()
