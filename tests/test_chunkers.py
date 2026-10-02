import collections

import pytest

from statnav.index.build import load_artefacts
from statnav.index.chunkers import build_chunks


@pytest.fixture(scope="module")
def chunks(parsed):
    art = load_artefacts()
    return {v: build_chunks(v, art) for v in ("v0", "v1", "v2")}


def test_chunk_ids_unique(chunks):
    for v, cs in chunks.items():
        dup = [k for k, n in collections.Counter(c.id for c in cs).items() if n > 1]
        assert not dup, f"{v}: {dup[:5]}"


def test_windows_are_bounded_and_track_coverage(chunks):
    for v in ("v0", "v1"):
        assert max(c.tokens for c in chunks[v]) <= 512
        covered = {p for c in chunks[v] for p in c.meta["provisions"]}
        assert "s2(1)" in covered and "s393:tbl1#1(i)" in covered
    # the naive v0 text still carries the running header; v1 does not
    assert any("Income Tax Department" in c.text for c in chunks["v0"])
    assert not any("Income Tax Department" in c.text for c in chunks["v1"])


def test_v2_keeps_a_definition_together(chunks):
    c = next(c for c in chunks["v2"] if c.provision_id == "s2(5)")
    for frag in ['"agricultural income" means', "(a) any rent or revenue", "(b) any income",
                 "(i) agriculture"]:
        assert frag in c.text
    assert {"s2(5)", "s2(5)(a)", "s2(5)(b)(i)"} <= set(c.meta["provisions"])
    assert c.embed_text.startswith("Section 2 — Definitions.")


def test_v2_table_row_chunk_is_self_describing(chunks):
    c = next(c for c in chunks["v2"] if c.id == "v2:s393:tbl1#1(i)")
    assert "Section 393, Table 1 (FOR PAYMENTS TO RESIDENT), Sl. No. 1(i)" in c.text
    assert "Rs. 20,000" in c.text and "Payer: Any person." in c.text
    assert c.meta["provisions"][0] == "s393:tbl1#1(i)"
    assert c.page_start == 456


def test_v2_fits_llm_budget(chunks):
    assert max(c.tokens for c in chunks["v2"]) <= 1600
