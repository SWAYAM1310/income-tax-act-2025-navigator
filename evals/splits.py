"""Stable dev / test / dev_mini splits of the verified golden set.

    python -m evals.splits            # (re)assign; an existing frozen test split never changes
    python -m evals.splits --freeze   # freeze the current test split (writes test.sha256)
    python -m evals.splits --lay [--freeze]   # the lay set's splits (evals/data/lay.jsonl)

Assignment is by a hash of the question id, so adding questions never reshuffles old ones.
dev_mini = 6 dev questions per type: the end-to-end set that fits one day of Groq quota.

The lay set has its own splits, so it never moves dev, test or dev_mini: lay_test (frozen before
any version is tuned on lay questions), lay_dev, lay_mini (6 lay_dev questions per type), and
lay_orig, the golden originals of the lay_dev paraphrases (the same gold in the Act's words).
"""

from __future__ import annotations

import argparse
import hashlib

from evals.common import DATA_DIR, GOLDEN, SPLITS_DIR, TYPES, read_jsonl

LAY = DATA_DIR / "lay.jsonl"

TEST_SHARE = 40  # percent
MINI_PER_TYPE = 6


def _bucket(qid: str) -> int:
    return int(hashlib.sha1(qid.encode()).hexdigest(), 16) % 100


def _read(name: str) -> list[str]:
    p = SPLITS_DIR / f"{name}.ids"
    return p.read_text(encoding="utf-8").split() if p.exists() else []


def _write(name: str, ids: list[str]) -> None:
    SPLITS_DIR.mkdir(parents=True, exist_ok=True)
    (SPLITS_DIR / f"{name}.ids").write_text("\n".join(ids) + "\n", encoding="utf-8")


def test_digest(ids: list[str]) -> str:
    return hashlib.sha256("\n".join(sorted(ids)).encode()).hexdigest()


def is_frozen(name: str = "test") -> bool:
    return (SPLITS_DIR / f"{name}.sha256").exists()


def _frozen_ids(name: str) -> list[str]:
    ids = _read(name)
    expected = (SPLITS_DIR / f"{name}.sha256").read_text().strip()
    if test_digest(ids) != expected:
        raise SystemExit(f"{name}.ids no longer matches its frozen digest; refusing to continue")
    return ids


def make(freeze: bool = False) -> dict[str, int]:
    golden = read_jsonl(GOLDEN)
    ids = [q["id"] for q in golden]
    test = _frozen_ids("test") if is_frozen() else [i for i in ids if _bucket(i) < TEST_SHARE]
    dev = [i for i in ids if i not in set(test)]
    types = {q["id"]: q["type"] for q in golden}
    mini = []
    for t in TYPES:
        mini += sorted((i for i in dev if types[i] == t), key=_bucket)[:MINI_PER_TYPE]
    _write("dev", dev)
    _write("test", test)
    _write("dev_mini", mini)
    if freeze and not is_frozen():
        (SPLITS_DIR / "test.sha256").write_text(test_digest(test) + "\n", encoding="utf-8")
    return {"dev": len(dev), "test": len(test), "dev_mini": len(mini), "frozen": is_frozen()}


def make_lay(freeze: bool = False) -> dict[str, int]:
    """Splits of the accepted lay questions. A frozen lay_test never changes; later questions
    all go to lay_dev."""
    lay = [q for q in read_jsonl(LAY) if q.get("status") == "accepted"]
    ids = [q["id"] for q in lay]
    test = (_frozen_ids("lay_test") if is_frozen("lay_test")
            else [i for i in ids if _bucket(i) < TEST_SHARE])
    dev = [i for i in ids if i not in set(test)]
    types = {q["id"]: q["type"] for q in lay}
    mini = []
    for t in TYPES:
        mini += sorted((i for i in dev if types[i] == t), key=_bucket)[:MINI_PER_TYPE]
    pair = {q["id"]: q.get("pair_of") for q in lay}
    orig = list(dict.fromkeys(pair[i] for i in dev if pair[i]))
    _write("lay_dev", dev)
    _write("lay_test", test)
    _write("lay_mini", mini)
    _write("lay_orig", orig)
    if freeze and not is_frozen("lay_test"):
        (SPLITS_DIR / "lay_test.sha256").write_text(test_digest(test) + "\n", encoding="utf-8")
    return {"lay_dev": len(dev), "lay_test": len(test), "lay_mini": len(mini),
            "lay_orig": len(orig), "frozen": is_frozen("lay_test")}


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--freeze", action="store_true")
    ap.add_argument("--lay", action="store_true", help="the lay set's splits instead")
    a = ap.parse_args()
    print(make_lay(a.freeze) if a.lay else make(a.freeze))
