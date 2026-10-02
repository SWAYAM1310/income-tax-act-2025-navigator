"""Cross-reference extraction and resolution.

Reference forms found in the Act (counts from the source inspection):
  section 515(3)(b)            ~2,276 "section N" mentions, ~1,200 with a clause path
  sections 427 and 428         plural lists joined by ",", "and", "or", "to"
  sub-section (3)(b)           relative to the referring section
  clause (22)(iii)(A)          relative: resolved upwards from the referring provision
  Chapter XIX-C                means Part C of Chapter XIX
  Schedule III (Table: Sl. No. 23), section 393(1) [Table: Sl. No. 1(i)]   table rows
  section 2(h) of the Securities Contracts (Regulation) Act, 1956          external
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from statnav.ingest.structure import Node

P1 = r"\((?:\d+[A-Z]*|[a-z]{1,4}|[A-Z]{1,5})\)"  # one label: (3) (2A) (b) (za) (iii) (A)
PATH = rf"(?:\s?{P1})*"
ITEM = rf"\d+(?![\d-]){PATH}"  # 515(3)(b); "80-IA" (1961 Act numbering) never matches
CONT = rf"(?:{ITEM}|{P1}{PATH})"  # "263(1) or (4)": a bare path continues the same section
SEP = r"\s*(?:,\s*(?:and|or)?|\band\b|\bor\b|\bto\b)\s*"
SECTION_LIST_RE = re.compile(rf"\b(sections?)\s+({ITEM}(?:{SEP}{CONT})*)")
REL_RE = re.compile(
    rf"\b(sub-sections?|clauses?|sub-clauses?|items?|sub-items?)\s+({P1}{PATH}(?:{SEP}{P1}{PATH})*)")
CHAPTER_RE = re.compile(r"\bChapter\s+([IVXL]+)(?:-([A-H]))?\b")
PART_OF_CHAPTER_RE = re.compile(r"\bPart\s+([A-H])\s+of\s+(?:this\s+Chapter|Chapter\s+([IVXL]+))")
SCHEDULE_RE = re.compile(r"\bSchedule\s+([IVXL]+)\b")
TABLE_ROW_RE = re.compile(r"[\[(]Table:\s*Sl\.\s*Nos?\.\s*([^\])]+)[\])]")
SERIAL_RE = re.compile(r"\bserial numbers?\s+(\d+[A-Z]?(?:\([ivx]+\))?)")
EXTERNAL_AFTER_RE = re.compile(
    r"^[\s,]*(?:\[[^\]]*\]\s*)?(?:of|under)\s+(?:the\s+)?(?:said\s+Act|that\s+Act|"
    r"[A-Z][\w().,'\- ]{2,120}?\bAct\b|[A-Z][\w().,'\- ]{2,80}?\b(?:Code|Rules|Regulations)\b|"
    r"Constitution)")
ONE_REF_RE = re.compile(rf"(\d+)?({PATH})")
PATH_PART_RE = re.compile(r"\(([^)]+)\)")
SL_ITEM_RE = re.compile(r"(\d+[A-Z]?)(\([ivx]+\))?")


@dataclass
class CrossRef:
    from_id: str
    raw: str
    ref_type: str  # section | provision | chapter | part | schedule | table_row | external
    to_id: str | None
    resolution: str  # exact | partial | unresolved | external


def _labels(path: str) -> list[str]:
    return [f"({m})" for m in PATH_PART_RE.findall(path)]


def _style(label: str) -> str:
    t = label.strip("()")
    if t[0].isdigit():
        return "num"
    if t.islower():
        return "roman" if re.fullmatch(r"[ivxl]+", t) and t not in ("i", "v", "x", "l") else "alpha"
    return "upper"


def inherit(prev: list[str], cur: list[str]) -> list[str]:
    """In a list, a continuation like "(b)" in "(2)(a) and (b)" keeps the earlier levels."""
    if not prev or not cur or _style(prev[0]) == _style(cur[0]):
        return cur
    for k in range(1, len(prev)):
        if _style(prev[k]) == _style(cur[0]):
            return prev[:k] + cur
    return cur


def _section_of(node: Node, nodes: dict[str, Node]) -> Node | None:
    n: Node | None = node
    while n is not None and n.kind not in ("section", "paragraph"):
        n = nodes.get(n.parent) if n.parent else None
    return n


class Resolver:
    def __init__(self, nodes: dict[str, Node], table_rows: dict[str, list[str]]):
        """table_rows: table node id -> row ids ("s393:tbl1#1(i)")."""
        self.nodes = nodes
        self.table_rows = table_rows
        self.tables_under: dict[str, list[str]] = {}
        for tid in table_rows:
            p = nodes[tid].parent
            while p:
                self.tables_under.setdefault(p, []).append(tid)
                p = nodes[p].parent

    # -- resolution helpers --------------------------------------------------------------------
    def _deepest(self, base: str, labels: list[str]) -> tuple[str | None, str]:
        if base not in self.nodes:
            return None, "unresolved"
        cur = base
        for k, lab in enumerate(labels):
            nxt = cur + lab
            if nxt not in self.nodes:
                # the Act sometimes skips a level: "section 70(zd)" means 70(1)(zd)
                tail = "".join(labels[k:])
                hits = [i for i in self._subtree(cur) if i.endswith(tail) and i != cur]
                if len(hits) == 1:
                    return hits[0], "inferred"
                return cur, "partial"
            cur = nxt
        return cur, "exact"

    def _subtree(self, nid: str) -> list[str]:
        out, todo = [], [nid]
        while todo:
            n = todo.pop()
            out.append(n)
            todo.extend(self.nodes[n].children)
        return out

    def _relative(self, node: Node, labels: list[str]) -> tuple[str | None, str]:
        """Resolve "(3)(b)" upwards from the referring node: first ancestor that has it."""
        n: Node | None = node
        while n is not None:
            target = n.id + "".join(labels)
            if target in self.nodes and target != node.id:
                return target, "exact"
            if n.kind in ("section", "paragraph"):
                break
            n = self.nodes.get(n.parent) if n.parent else None
        sec = _section_of(node, self.nodes)
        if sec is not None and labels:
            got, how = self._deepest(sec.id, labels)
            if got and got != sec.id:
                return got, "partial"
        return None, "unresolved"

    def _table_row(self, scope: str, sl_text: str) -> list[tuple[str | None, str, str]]:
        tables = [t for t in self.tables_under.get(scope, [])] or (
            [scope] if scope in self.table_rows else [])
        out = []
        for item in re.split(r"\s*(?:,|and|or|to)\s*", sl_text):
            m = SL_ITEM_RE.match(item.strip())
            if not m:
                continue
            want = m.group(1) + (m.group(2) or "")
            hit = None
            for tid in tables:
                rows = self.table_rows[tid]
                cand = f"{tid}#{want}"
                if cand in rows:
                    hit = (cand, "exact")
                    break
                cand = f"{tid}#{m.group(1)}"
                if cand in rows:
                    hit = (cand, "partial")
                    break
            out.append((hit[0] if hit else None, hit[1] if hit else "unresolved", item.strip()))
        return out

    # -- extraction ------------------------------------------------------------------------
    def extract(self, node: Node, text: str) -> list[CrossRef]:
        refs: list[CrossRef] = []
        taken: list[tuple[int, int]] = []

        def overlaps(a: int, b: int) -> bool:
            return any(a < y and x < b for x, y in taken)

        for m in SECTION_LIST_RE.finditer(text):
            tail = text[m.end():m.end() + 160]
            # "section 393(1) [Table: Sl. No. 1(i)]" / "(Table: Sl. No. 2)"
            tm = TABLE_ROW_RE.match(tail.lstrip())
            external = EXTERNAL_AFTER_RE.match(tail[len(tail) - len(tail.lstrip()):]
                                               if not tm else tail.lstrip()[tm.end():])
            taken.append((m.start(), m.end()))
            items = re.split(r"\s*(?:,|\band\b|\bor\b|\bto\b)\s*", m.group(2))
            last_sec = None
            last_labels: list[str] = []
            for it in items:
                im = ONE_REF_RE.fullmatch(it.strip())
                if not im or not (im.group(1) or im.group(2)):
                    continue
                sec = im.group(1) or last_sec
                if sec is None:
                    continue
                labels = _labels(im.group(2) or "")
                if not im.group(1):  # "263(1) or (4)", "70(1)(a) and (b)"
                    labels = inherit(last_labels, labels)
                last_sec, last_labels = sec, labels
                raw = f"section {sec}{''.join(labels)}"
                if external:
                    refs.append(CrossRef(node.id, raw, "external", None, "external"))
                    continue
                to, how = self._deepest(f"s{sec}", labels)
                refs.append(CrossRef(node.id, raw, "provision" if labels else "section", to, how))
            if tm and not external and last_sec:
                scope = refs[-1].to_id or f"s{last_sec}"
                for to, how, item in self._table_row(scope, tm.group(1)):
                    refs.append(CrossRef(node.id, f"{scope} Table Sl. No. {item}", "table_row",
                                         to, how))

        for m in REL_RE.finditer(text):
            if overlaps(m.start(), m.end()):
                continue
            tail = text[m.end():m.end() + 160]
            if EXTERNAL_AFTER_RE.match(tail):
                refs.append(CrossRef(node.id, m.group(0), "external", None, "external"))
                continue
            # "clause (a) of sub-section (1)": resolve the outer reference first
            of = re.match(r"\s*of\s+(sub-section|clause|sub-clause)\s+((?:\([^)]+\))+)", tail)
            prev: list[str] = []
            for part in re.split(SEP, m.group(2)):
                labels = inherit(prev, _labels(part))
                if not labels:
                    continue
                prev = labels
                if of:
                    labels = _labels(of.group(2)) + labels
                to, how = self._relative(node, labels)
                refs.append(CrossRef(node.id, f"{m.group(1)} {''.join(labels)}", "provision",
                                     to, how))
            taken.append((m.start(), m.end()))

        for m in PART_OF_CHAPTER_RE.finditer(text):
            chap = m.group(2) or (self.nodes[node.chapter].label if node.chapter else None)
            to = f"ch:{chap}:{m.group(1)}" if chap else None
            refs.append(CrossRef(node.id, m.group(0), "part", to if to in self.nodes else None,
                                 "exact" if to in self.nodes else "unresolved"))
        for m in CHAPTER_RE.finditer(text):
            to = f"ch:{m.group(1)}" + (f":{m.group(2)}" if m.group(2) else "")
            kind = "part" if m.group(2) else "chapter"
            if EXTERNAL_AFTER_RE.match(text[m.end():m.end() + 120]):
                refs.append(CrossRef(node.id, m.group(0), "external", None, "external"))
                continue
            refs.append(CrossRef(node.id, m.group(0), kind, to if to in self.nodes else None,
                                 "exact" if to in self.nodes else "unresolved"))
        for m in SCHEDULE_RE.finditer(text):
            tail = text[m.end():m.end() + 120]
            if re.match(r"\s*(?:to|of)\s+the\s+[A-Z]", tail):
                refs.append(CrossRef(node.id, m.group(0), "external", None, "external"))
                continue
            sid = f"sch:{m.group(1)}"
            tm = TABLE_ROW_RE.match(tail.lstrip())
            known = sid in self.nodes
            refs.append(CrossRef(node.id, m.group(0), "schedule", sid if known else None,
                                 "exact" if known else "unresolved"))
            if tm and sid in self.nodes:
                for to, how, item in self._table_row(sid, tm.group(1)):
                    refs.append(CrossRef(node.id, f"Schedule {m.group(1)} Table Sl. No. {item}",
                                         "table_row", to, how))
        return refs
