"""Table extraction by x-coordinate column binning.

The PDF's tables have no ruling lines (PyMuPDF find_tables() fails), but:
- every table starts with a centred "TABLE" line, optional centred title lines, the column
  headings, then a row of single column letters ("A", "B", "C", ...);
- body text is emitted cell-major: Sl. No. (col A), then the col B lines, then col C, ...;
- a row starts with a serial number ("1.", "13.") in column A, sometimes merged with the col B
  text on one line ("13. Payment received ...");
- sub-rows (e.g. section 393 "1. Commission or brokerage" -> (i), (ii)) show up as the stream
  jumping back to an earlier column within the same serial number.

We locate each table region in the global line stream, derive column left edges from the letter
row plus the body lines, then assemble rows/sub-rows and attach "Note N.-" blocks.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from statnav.ingest.footnotes import looks_like_footnote_start
from statnav.ingest.pdf_layout import FN_TOKEN_RE, Line

SL_NO_RE = re.compile(r"^(\d+[A-Z]*)\.(?:\s+|$)")
PAREN_SL_NO_RE = re.compile(r"^\((\d+)\)(?:\s+|$)")
NOTE_RE = re.compile(r"^Note(?:\s+\d+[A-Z]*)?\s*\.?\s*[—\-:]")
LETTER_RE = re.compile(r"^\(?[A-H]\)?$")
SUBROW_LABEL_RE = re.compile(r"^\(([ivx]+)\)\s")
SUBSECTION_RE = re.compile(r"^\(\d+[A-Z]*\)(?:\s|\([a-z]+\)\s)")  # "(2) ..." or "(2)(a) ..."
BODY_LEFT_MAX = 45.0


def clean(text: str) -> str:
    return re.sub(r"\s+", " ", FN_TOKEN_RE.sub("", text)).strip()


@dataclass
class Cell:
    lines: list[Line] = field(default_factory=list)

    @property
    def text(self) -> str:
        return clean(" ".join(line.text for line in self.lines))

    @property
    def raw(self) -> str:
        return " ".join(line.text for line in self.lines)


@dataclass
class SubRow:
    label: str | None  # "(i)", "(ii)"; None for a plain row
    cells: list[Cell]


@dataclass
class Row:
    sl_no: str
    heading: Cell  # col-B text that precedes sub-rows (empty when no sub-rows)
    subrows: list[SubRow]
    pages: set[int] = field(default_factory=set)


@dataclass
class Table:
    index: int  # 0-based order of appearance in the Act
    start_line: int  # index of the "TABLE" line in the global stream
    end_line: int  # exclusive
    page_start: int
    page_end: int
    title: str
    headers: list[str]  # column headings (best effort), aligned with columns
    letters: list[str]
    col_left: list[float]
    rows: list[Row]
    notes: list[str]
    issues: list[str] = field(default_factory=list)


def _is_letter_row(lines: list[Line], i: int) -> int:
    """Return how many consecutive single-letter lines start at i (the column-letter row)."""
    n = 0
    while i + n < len(lines) and LETTER_RE.match(lines[i + n].text.strip()):
        n += 1
    return n


def is_section_number_span(line: Line) -> bool:
    first = line.first_span
    return (first.bold and line.x0 < BODY_LEFT_MAX
            and re.fullmatch(r"\d+\s*\.?", first.text.strip()) is not None
            and re.match(r"^\d+\s*\.", line.text.strip()) is not None)


def is_table_heading(line: Line) -> bool:
    """A centred 'TABLE' (sections) or 'Table' (Schedule II) line."""
    return clean(line.text) in ("TABLE", "Table") and line.x0 > 200


def is_endnote_line(line: Line) -> bool:
    """An amendment endnote header ('37. Sl. Nos. 38A to 38D inserted by ...'), never a row."""
    return (line.x0 < 36 and not line.first_span.bold
            and looks_like_footnote_start(clean(line.text)))


def _is_section_boundary(line: Line, nxt: Line | None) -> bool:
    t = clean(line.text)
    if not t:
        return False
    first = line.first_span
    # section start: the section number is its own bold span ("19." then plain text, or "169."
    # alone). All-bold row headings inside tables ("1. Commission or brokerage") don't qualify.
    if is_section_number_span(line):
        return True
    # section heading: an all-bold line at the left margin followed by a section start
    if line.all_bold and line.x0 < BODY_LEFT_MAX and t.endswith(".") and nxt is not None \
            and is_section_number_span(nxt):
        return True
    return "BoldItal" in first.font and re.match(r"^(CHAPTER|SCHEDULE|PART)\b", t) is not None


def _find_end(lines: list[Line], body_start: int, paren_rows: bool = False) -> int:
    in_notes = False
    for j in range(body_start, len(lines)):
        line = lines[j]
        t = clean(line.text).lstrip("[")  # "[(7) ..." opens an amended sub-section
        nxt = lines[j + 1] if j + 1 < len(lines) else None
        if is_table_heading(line) or _is_section_boundary(line, nxt):
            return j
        if is_endnote_line(line):
            return j
        if line.x0 < BODY_LEFT_MAX and NOTE_RE.match(t):
            in_notes = True
            continue
        if in_notes and SL_NO_RE.match(t) and line.x0 < BODY_LEFT_MAX:
            in_notes = False
            continue
        if line.x0 < BODY_LEFT_MAX and not SL_NO_RE.match(t):
            if SUBSECTION_RE.match(t) and not paren_rows:
                return j
            if (paren_rows and not PAREN_SL_NO_RE.match(t) and not in_notes
                    and re.match(r"^\([a-z]+\)\s+[A-Z]", t)):
                return j  # "(e) For the purposes of ...": the enclosing provision resumes
    return len(lines)


def _column_edges(lines: list[Line], letters: list[Line], body: range) -> list[float]:
    """Left edge of each column = leftmost start among the body lines that belong to it.

    A line belongs to the column whose header letter is nearest to the line's own centre when
    the line starts right of that column's previous edge; this handles both wide left-aligned
    columns (section 19, col B starts at x=47 under a letter at x=175) and narrow centred
    columns (section 52, where centred cell lines start right of the letter's centre).
    """
    centres = [(ln.bbox[0] + ln.bbox[2]) / 2 for ln in letters]
    cands: list[tuple[float, float]] = []  # (x0, centre) of cell lines
    in_notes = False
    for j in body:
        ln = lines[j]
        t = clean(ln.text)
        if not t:
            continue
        if ln.x0 < BODY_LEFT_MAX and NOTE_RE.match(t):
            in_notes = True
        elif SL_NO_RE.match(t) or PAREN_SL_NO_RE.match(t):
            in_notes = False
            continue
        if not in_notes:
            cands.append((ln.x0, (ln.x0 + ln.bbox[2]) / 2))
    edges = []
    for k, c in enumerate(centres):
        lo = centres[k - 1] + 5 if k else -1
        xs = [x for x, mid in cands if lo < x <= c + 5
              # a centred line of the previous column (section 52) starts right of that
              # column's centre; it must not pull this column's edge leftwards
              and not (k and abs(mid - centres[k - 1]) < abs(mid - c))]
        edges.append(min(xs) if xs else c - 10)
    edges[0] = 0.0  # col A holds only serial numbers; its edge is the page margin
    return edges


def _starts_a_column(line: Line, edges: list[float]) -> bool:
    """True when a later span begins at another column's edge: two cells PyMuPDF joined."""
    for s in line.spans[1:]:
        if s.text.strip() and any(abs(s.bbox[0] - e) < 3 for e in edges[1:]):
            return True
    return False


def _first_boundary_crossing(lines: list[Line], body: range, edges: list[float]) -> int | None:
    """Index of the first non-note line that spans across a column edge by more than 8pt."""
    in_notes = False
    for j in body:
        line = lines[j]
        t = clean(line.text)
        if not t:
            continue
        if line.x0 < BODY_LEFT_MAX and NOTE_RE.match(t):
            in_notes = True
            continue
        if SL_NO_RE.match(t) or PAREN_SL_NO_RE.match(t):
            in_notes = False
            continue  # "13. Payment received ..." legitimately runs from col A into col B
        if in_notes:
            continue
        col = _col_of(line.x0, edges)
        # a full-width line starting in an inner column: body text, not a cell (cells joined
        # on one baseline by PyMuPDF also cross an edge, but stop short of the right margin)
        if (col + 1 < len(edges) and line.bbox[2] > edges[col + 1] + 8 and line.bbox[2] > 540
                and not _starts_a_column(line, edges)):
            return j
    return None


def _col_of(x0: float, edges: list[float]) -> int:
    col = 0
    for k, e in enumerate(edges):
        if x0 >= e - 2:
            col = k
    return col


def _assemble(lines: list[Line], body: range, edges: list[float],
              paren_rows: bool = False) -> tuple[list[Row], list[str]]:
    ncols = len(edges)
    rows: list[Row] = []
    notes: list[str] = []
    issues: list[str] = []
    cur: list[Cell] | None = None
    cur_row: Row | None = None
    last_col = -1
    in_notes = False

    for j in body:
        line = lines[j]
        t = clean(line.text)
        if not t:
            continue
        if line.x0 < BODY_LEFT_MAX and NOTE_RE.match(t):
            in_notes = True
            after = rows[-1].sl_no if rows else ""
            notes.append(f"[after Sl. No. {after}] {t}" if after else t)
            continue
        col = _col_of(line.x0, edges)
        m = (PAREN_SL_NO_RE if paren_rows else SL_NO_RE).match(t) if col == 0 else None
        if m and in_notes and not _row_start_after_notes(line, edges):
            m = None
        if in_notes and not m:
            notes[-1] += " " + t
            continue
        in_notes = False
        if m:
            cur = [Cell() for _ in range(ncols)]
            cur_row = Row(m.group(1), Cell(), [SubRow(None, cur)], {line.page})
            rows.append(cur_row)
            rest = t[m.end():].strip()
            if rest and paren_rows:  # "(1) Amounts credited ...": the row's own col-A text
                cur[0].lines.append(Line(line.page, line.bbox, line.spans, rest))
                last_col = 0
            elif rest:  # serial number merged with the col-B text on one line
                cur[1].lines.append(Line(line.page, line.bbox, line.spans, rest))
                last_col = 1
            else:
                last_col = 0
            continue
        if cur_row is None:
            issues.append(f"text before first row: {t[:60]!r}")
            continue
        cur_row.pages.add(line.page)
        if col < last_col and col >= 1:
            # stream jumped back to an earlier column: a new sub-row of the same serial number
            sm = SUBROW_LABEL_RE.match(t + " ")
            cur = [Cell() for _ in range(ncols)]
            cur_row.subrows.append(SubRow(f"({sm.group(1)})" if sm else None, cur))
        assert cur is not None
        cur[col].lines.append(line)
        last_col = col

    for row in rows:
        _split_first_subrow(row)
    return rows, notes + [f"!{i}" for i in issues]


def _row_start_after_notes(line: Line, edges: list[float]) -> bool:
    """A serial number after a Note block: bold, or confined to the narrow col A/B area."""
    return line.first_span.bold or len(edges) < 3 or line.bbox[2] < edges[2]


def _split_first_subrow(row: Row) -> None:
    """If sub-rows (ii), (iii)... exist, the (i) sub-row starts inside the first sub-row's col B."""
    if len(row.subrows) < 2 or row.subrows[1].label != "(ii)":
        return
    first = row.subrows[0]
    b_lines = first.cells[1].lines
    for k, ln in enumerate(b_lines):
        if SUBROW_LABEL_RE.match(clean(ln.text) + " ") and clean(ln.text).startswith("(i)"):
            row.heading = Cell(b_lines[:k])
            first.cells[1] = Cell(b_lines[k:])
            first.label = "(i)"
            return


def find_tables(lines: list[Line]) -> list[Table]:
    tables: list[Table] = []
    i = 0
    while i < len(lines):
        if not is_table_heading(lines[i]):
            i += 1
            continue
        start = i
        j = i + 1
        title_parts = []
        # centred, all-caps title lines
        while j < len(lines) and lines[j].x0 > 120 and clean(lines[j].text).isupper() \
                and not LETTER_RE.match(clean(lines[j].text)):
            title_parts.append(clean(lines[j].text))
            j += 1
        header_start = j
        k = j
        letters_at = None
        while k < min(len(lines), j + 40):
            n = _is_letter_row(lines, k)
            if n >= 2:
                letters_at = (k, n)
                break
            k += 1
        issues = []
        if letters_at is None:
            issues.append("no column-letter row")
            tables.append(Table(len(tables), start, j, lines[start].page, lines[start].page,
                                " ".join(title_parts), [], [], [], [], [], issues))
            i = j
            continue
        k, n = letters_at
        letter_lines = lines[k:k + n]
        body_start = k + n
        paren_rows = clean(letter_lines[0].text).startswith("(")
        end = _find_end(lines, body_start, paren_rows)
        body = range(body_start, end)
        edges = _column_edges(lines, letter_lines, body)
        # cells never run full width; body text that resumes after a table nested inside an
        # indented provision (e.g. a definition) does, so it marks the true end
        crossed = _first_boundary_crossing(lines, body, edges)
        if crossed is not None:
            end = crossed
            body = range(body_start, end)
            edges = _column_edges(lines, letter_lines, body)
        rows, notes_and_issues = _assemble(lines, body, edges, paren_rows)
        notes = [x for x in notes_and_issues if not x.startswith("!")]
        issues += [x[1:] for x in notes_and_issues if x.startswith("!")]
        tables.append(Table(
            index=len(tables), start_line=start, end_line=end,
            page_start=lines[start].page, page_end=lines[end - 1].page,
            title=" ".join(title_parts), headers=_headers(lines[header_start:k], letter_lines),
            letters=[clean(ln.text).strip("()") for ln in letter_lines], col_left=edges,
            rows=rows, notes=notes, issues=issues,
        ))
        i = end
    return tables


def _headers(header_lines: list[Line], letters: list[Line]) -> list[str]:
    """Assign column-heading fragments to the nearest column letter by horizontal centre."""
    centres = [(ln.bbox[0] + ln.bbox[2]) / 2 for ln in letters]
    out = [""] * len(centres)
    for ln in header_lines:
        c = (ln.bbox[0] + ln.bbox[2]) / 2
        k = min(range(len(centres)), key=lambda q: abs(centres[q] - c))
        out[k] = (out[k] + " " + clean(ln.text)).strip()
    return out
