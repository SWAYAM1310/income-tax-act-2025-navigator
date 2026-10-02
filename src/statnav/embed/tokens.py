"""Approximate token counting for chunk sizing and spend estimates.

Jina reports exact usage per request; before a run we only need a close estimate, so we use
tiktoken's cl100k encoding (within ~10% of Jina's counts on English legal text).
"""

from __future__ import annotations

from functools import lru_cache

import tiktoken


@lru_cache(maxsize=1)
def _enc() -> tiktoken.Encoding:
    return tiktoken.get_encoding("cl100k_base")


def count(text: str) -> int:
    return len(_enc().encode(text, disallowed_special=()))


def encode(text: str) -> list[int]:
    return _enc().encode(text, disallowed_special=())


def decode(tokens: list[int]) -> str:
    return _enc().decode(tokens)
