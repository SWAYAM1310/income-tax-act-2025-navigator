"""Search the indexed Act from the command line.

    python -m statnav.retrieve.search "how is agricultural income defined" --version v2 -k 5

Prints the top-k chunks with their provisions and pages, and the total evidence tokens, which
shows whether the retrieved context fits the LLM budget (~4.5K tokens on Groq's free tier).
"""

from __future__ import annotations

import argparse
import textwrap

from statnav.embed.jina import JinaClient
from statnav.index.db import connect
from statnav.retrieve.dense import search

EVIDENCE_BUDGET = 4500


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("query")
    ap.add_argument("--version", default="v2")
    ap.add_argument("-k", type=int, default=5)
    a = ap.parse_args()
    client = JinaClient.from_config()
    with connect() as conn:
        hits = search(conn, client, a.query, a.version, a.k)
    total = 0
    for n, h in enumerate(hits, 1):
        total += h.tokens
        covers = ", ".join(h.meta.get("provisions", [])[:4])
        print(f"{n}. [{h.score:.3f}] {h.chunk_id}  pp.{h.page_start}-{h.page_end}  "
              f"{h.tokens} tok  covers: {covers or '-'}")
        print(textwrap.indent(textwrap.shorten(h.text, 300), "   "))
    fits = "fits" if total <= EVIDENCE_BUDGET else "EXCEEDS"
    print(f"\nevidence: {total} tokens ({fits} the {EVIDENCE_BUDGET}-token budget); "
          f"Jina tokens this query: {client.usage.tokens}")


if __name__ == "__main__":
    main()
