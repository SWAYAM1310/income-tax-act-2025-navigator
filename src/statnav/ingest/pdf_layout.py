"""Layout layer: turn PDF pages into clean, ordered text lines with typography and coordinates.

Facts about this PDF that drive the design (see the plan's source-document findings):
- Running header ("Income Tax Department" NotoSans-Bold 12pt, "Ministry of Finance..." NotoSans 9pt)
  sits at the top of every page but is emitted *last* in stream order.
- The "Downloaded/Printed on ..." footer (NotoSans-Italic 7.5pt) appears on only 51 pages.
- Footnote markers are the only 7.1pt text: a raised label ("1", "3a") in its own text block,
  just left of the bold "[" that opens the amended text. Plain get_text() emits them out of order,
  so we re-insert each marker into the line it belongs to as an inline token  {{fn:<label>}}.
- Body text is 8.5pt LiberationSerif; clause labels are followed by NBSP.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

import pymupdf

MARKER_SIZE = 7.1
HEADER_MAX_Y = 50.0
FOOTER_MIN_Y = 805.0

_NORMALISE = str.maketrans({"\xa0": " ", "\u2002": " ", "\u2003": " ", "\u2009": " ", "\xad": None})


def fn_token(label: str) -> str:
    return "{{fn:" + label + "}}"


FN_TOKEN_RE = re.compile(r"\{\{fn:([0-9]+[a-z]*)\}\}")


@dataclass
class Span:
    text: str
    font: str
    size: float
    bbox: tuple[float, float, float, float]

    @property
    def bold(self) -> bool:
        return "Bold" in self.font

    @property
    def italic(self) -> bool:
        return "Italic" in self.font or "Ital" in self.font


@dataclass
class Line:
    page: int  # 1-based
    bbox: tuple[float, float, float, float]
    spans: list[Span]
    text: str = ""
    # character x-positions (x0 per char of self.text, before marker insertion)
    _char_x: list[float] = field(default_factory=list, repr=False)
    markers: list[str] = field(default_factory=list)

    @property
    def x0(self) -> float:
        return self.bbox[0]

    @property
    def y0(self) -> float:
        return self.bbox[1]

    @property
    def all_bold(self) -> bool:
        return all(s.bold for s in self.spans if s.text.strip())

    @property
    def first_span(self) -> Span:
        return next(s for s in self.spans if s.text.strip())


@dataclass
class Marker:
    page: int
    label: str
    bbox: tuple[float, float, float, float]


@dataclass
class PageLayout:
    number: int
    lines: list[Line]
    markers: list[Marker]
    dropped: list[str]  # header/footer text removed from this page
    unplaced_markers: list[Marker] = field(default_factory=list)


def _is_header_footer(span: dict) -> bool:
    font, size, (_, y0, _, y1) = span["font"], span["size"], span["bbox"]
    if font.startswith("NotoSans") and y1 <= HEADER_MAX_Y and size >= 8.9:
        return True
    return font.startswith("NotoSans-Italic") and y0 >= FOOTER_MIN_Y and round(size, 1) == 7.5


def _span_from_raw(raw: dict) -> tuple[Span, list[float]]:
    chars = raw["chars"]
    text = "".join(c["c"] for c in chars).translate(_NORMALISE)
    xs = [c["bbox"][0] for c in chars]
    return Span(text, raw["font"], round(raw["size"], 2), tuple(raw["bbox"])), xs


def extract_page(page: pymupdf.Page) -> PageLayout:
    number = page.number + 1
    lines: list[Line] = []
    markers: list[Marker] = []
    dropped: list[str] = []

    raw = page.get_text("rawdict", flags=pymupdf.TEXT_PRESERVE_WHITESPACE)
    for block in raw["blocks"]:
        for rl in block.get("lines", []):
            spans: list[Span] = []
            char_x: list[float] = []
            for rs in rl["spans"]:
                span, xs = _span_from_raw(rs)
                if not span.text:
                    continue
                if _is_header_footer(rs):
                    dropped.append(span.text)
                    continue
                if round(rs["size"], 1) == MARKER_SIZE and span.text.strip():
                    markers.append(Marker(number, span.text.strip(), span.bbox))
                    continue
                if round(rs["size"], 1) == 9.9 and not span.text.strip():
                    continue  # stray layout spaces near the top of some pages
                spans.append(span)
                char_x.extend(xs)
            if spans and "".join(s.text for s in spans).strip():
                x0 = min(s.bbox[0] for s in spans)
                y0 = min(s.bbox[1] for s in spans)
                x1 = max(s.bbox[2] for s in spans)
                y1 = max(s.bbox[3] for s in spans)
                text = "".join(s.text for s in spans)
                lines.append(Line(number, (x0, y0, x1, y1), spans, text, char_x))

    layout = PageLayout(number, lines, markers, dropped)
    _place_markers(layout)
    return layout


def _place_markers(layout: PageLayout) -> None:
    """Insert each footnote marker as an inline token in front of the character to its right."""
    placements: dict[int, list[tuple[int, str]]] = {}
    for m in layout.markers:
        mx1 = m.bbox[2]
        mcy = (m.bbox[1] + m.bbox[3]) / 2
        best = None
        for i, line in enumerate(layout.lines):
            ly0, ly1 = line.bbox[1], line.bbox[3]
            # marker is raised ~2pt: its centre sits in the upper part of the line box
            if not (ly0 - 4 <= mcy <= ly1):
                continue
            if line.bbox[2] < mx1 - 1:
                continue
            idx = next((k for k, x in enumerate(line._char_x) if x >= mx1 - 1.5), None)
            if idx is None:
                continue
            gap = line._char_x[idx] - mx1
            if best is None or abs(gap) < best[0]:
                best = (abs(gap), i, idx)
        if best is None or best[0] > 12:
            layout.unplaced_markers.append(m)
            continue
        placements.setdefault(best[1], []).append((best[2], m.label))
    for i, items in placements.items():
        line = layout.lines[i]
        text = line.text
        for idx, label in sorted(items, reverse=True):
            text = text[:idx] + fn_token(label) + text[idx:]
            line.markers.append(label)
        line.text = text


def extract(doc: pymupdf.Document) -> list[PageLayout]:
    return [extract_page(p) for p in doc]
