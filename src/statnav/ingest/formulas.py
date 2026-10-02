"""Inject the hand-transcribed formula images (formulas.yaml) into the parsed text."""

from __future__ import annotations

from pathlib import Path

import yaml

from statnav.ingest.pdf_layout import Line
from statnav.ingest.structure import ParseResult

FORMULAS = Path(__file__).with_name("formulas.yaml")


def load() -> list[dict]:
    with FORMULAS.open(encoding="utf-8") as f:
        return yaml.safe_load(f)


def _preceding_line(lines: list[Line], page: int, bbox: list[float]) -> int | None:
    """The last line above the image on its page, preferring lines in the same column."""
    x0, y0, x1, _ = bbox
    best = None
    for k, ln in enumerate(lines):
        if ln.page != page or ln.bbox[3] > y0 + 2:
            continue
        overlap = min(ln.bbox[2], x1 + 150) - max(ln.bbox[0], x0 - 150) > 0
        score = (overlap, ln.bbox[3])
        if best is None or score > best[0]:
            best = (score, k)
    return best[1] if best else None


def inject(result: ParseResult, lines: list[Line]) -> list[str]:
    """Append "[Formula: ...]" after the preceding line's text. Returns where each went."""
    owner: dict[int, tuple[str, int]] = {}
    for node in result.nodes.values():
        for pos, k in enumerate(node.line_indices):
            if k >= 0:
                owner.setdefault(k, (node.id, pos))
    cell_of: dict[int, object] = {}
    for t in result.tables:
        for row in t.rows:
            for sub in row.subrows:
                for cell in sub.cells:
                    for ln in cell.lines:
                        cell_of[id(ln)] = cell

    placed = []
    for f in load():
        k = _preceding_line(lines, f["page"], f["bbox"])
        token = f"[Formula: {f['text']}]"
        if k is None:
            placed.append(f"p{f['page']}: unplaced")
            continue
        cell = cell_of.get(id(lines[k]))
        if cell is not None:
            cell.lines.append(Line(f["page"], tuple(f["bbox"]), [], token))
            placed.append(f"p{f['page']}: table cell")
        elif k in owner:
            nid, pos = owner[k]
            node = result.nodes[nid]
            at = pos + 1
            while at < len(node.texts) and node.texts[at].startswith("[Formula:"):
                at += 1  # keep several formulas after one line in page order (s229(2): D, E)
            node.texts.insert(at, token)
            node.line_indices.insert(at, -1)
            # later formulas owned by this node shift by one
            owner.update({kk: (n_, p_ + 1) for kk, (n_, p_) in owner.items()
                          if n_ == nid and p_ >= at})
            placed.append(f"p{f['page']}: {nid}")
        else:
            placed.append(f"p{f['page']}: no owner for line {k}")
    return placed
