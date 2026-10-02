"""Stable dev / test / dev_mini splits of the verified golden set.

    python -m evals.splits            # (re)assign; an existing frozen test split never changes
    python -m evals.splits --freeze   # freeze the current test split (writes test.sha256)

Assignment is by a hash of the question id, so adding questions never reshuffles old ones.
dev_mini = 6 dev questions per type: the end-to-end set that fits one day of Groq quota.
"""

from __future__ import annotations

import argparse
import hashlib

from evals.common import GOLDEN, SPLITS_DIR, TYPES, read_jsonl

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


def is_frozen() -> bool:
    return (SPLITS_DIR / "test.sha256").exists()


def make(freeze: bool = False) -> dict[str, int]:
    golden = read_jsonl(GOLDEN)
    ids = [q["id"] for q in golden]
    if is_frozen():
        test = _read("test")
        expected = (SPLITS_DIR / "test.sha256").read_text().strip()
        if test_digest(test) != expected:
            raise SystemExit("test.ids no longer matches its frozen digest; refusing to continue")
    else:
        test = [i for i in ids if _bucket(i) < TEST_SHARE]
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


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--freeze", action="store_true")
    print(make(ap.parse_args().freeze))
