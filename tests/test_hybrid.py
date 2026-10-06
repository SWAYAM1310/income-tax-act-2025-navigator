"""Query-term selection and reciprocal rank fusion (v3 hybrid retrieval)."""

import pytest

from statnav.retrieve.dense import Hit
from statnav.retrieve.hybrid import DEFAULT_RETRIEVERS, rrf, search, terms


def h(cid: str, tokens: int = 10) -> Hit:
    return Hit(cid, cid, 0.5, f"text {cid}", tokens, 1, 1, {"provisions": [cid]})


def test_terms_drops_question_words_and_keeps_numbers():
    got = terms("How was section 483(1) amended by the Finance Act, 2026?")
    # "how/was/by/the/act/section" are stop words; the numbers survive
    assert got == ["483", "1", "amended", "finance", "2026"]


def test_terms_are_safe_tsquery_input():
    # operators and quotes cannot survive, so the terms can be interpolated into to_tsquery
    assert terms("drop & table | 'x':* !foo") == ["drop", "table", "foo"]


def test_terms_dedupe_and_keep_first_position():
    assert terms("income from income and capital") == ["income", "capital"]


def test_terms_of_a_question_with_nothing_informative():
    assert terms("what is it under the act?") == []


def test_rrf_rewards_agreement_between_lists():
    a = [h("x"), h("y")]
    b = [h("y"), h("z")]
    # y is ranked by both lists, so it wins despite never being first
    assert [r.chunk_id for r in rrf([(a, 1.0), (b, 1.0)])] == ["y", "x", "z"]


def test_rrf_weights_shift_the_order():
    a = [h("x")]
    b = [h("y")]
    assert [r.chunk_id for r in rrf([(a, 1.0), (b, 5.0)])] == ["y", "x"]


def test_rrf_truncates_to_k_and_carries_the_fused_score():
    out = rrf([([h("a"), h("b"), h("c")], 1.0)], k=2)
    assert [r.chunk_id for r in out] == ["a", "b"]
    assert out[0].score == pytest.approx(1 / 61, abs=1e-6)  # rrf rounds to 6 decimals
    assert out[0].score > out[1].score


def test_rrf_of_nothing_is_nothing():
    assert rrf([]) == []
    assert rrf([([], 1.0)]) == []


def test_rrf_preserves_the_hit_payload():
    out = rrf([([h("a", tokens=42)], 1.0)])
    assert out[0].tokens == 42
    assert out[0].meta == {"provisions": ["a"]}


def test_v3_defaults_to_dense_plus_both_id_lookups_without_fts():
    # fts is implemented but excluded: it cost lookup recall on dev (0.800 vs 0.914)
    assert DEFAULT_RETRIEVERS == ("dense", "ids", "under")


def test_search_rejects_an_unknown_retriever():
    with pytest.raises(ValueError, match="unknown retrievers"):
        search(None, None, "q", "v2", retrievers=["dense", "bm25"])


@pytest.fixture(scope="module")
def conn():
    from statnav.index.db import connect
    try:
        c = connect()
    except Exception as exc:  # noqa: BLE001 - any connection failure means "skip"
        pytest.skip(f"database not reachable: {exc}")
    yield c
    c.close()


@pytest.mark.db
def test_containers_separates_table_sections_from_leaf_provisions(conn):
    """Section 393 keeps its rates in child chunks; section 483 holds 483(1) itself.

    This is what lets the exact-id boost serve amendment questions without wrecking table
    ranking, and it needs no knowledge of the question's type.
    """
    from statnav.retrieve.hybrid import containers
    got = containers(conn, ["s393", "s483"], "v2")
    assert "s393" in got
    assert "s483" not in got


@pytest.mark.db
def test_by_ids_drops_a_container_so_its_rows_can_win(conn):
    from statnav.retrieve.hybrid import by_ids
    kept = [h.chunk_id for h in by_ids(conn, ["s393"], "v2", 10)]
    assert "v2:s393" not in kept, "the section-393 heading must not take the exact-id boost"
    # it is still reachable, just without the boost
    loose = [h.chunk_id for h in by_ids(conn, ["s393"], "v2", 10, drop_containers=False,
                                        stub_tokens=0)]
    assert "v2:s393" in loose


@pytest.mark.db
def test_by_ids_keeps_the_provision_an_amendment_question_names(conn):
    from statnav.retrieve.hybrid import by_ids
    kept = [h.chunk_id for h in by_ids(conn, ["s483(1)", "s483"], "v2", 10)]
    assert "v2:s483" in kept


def test_slot_merge_leaves_the_top_untouched_and_fills_the_next_slots():
    from statnav.retrieve.hybrid import slot_merge
    base = [h(c) for c in "abcdef"]
    extra = [h("x"), h("y"), h("z")]
    got = [r.chunk_id for r in slot_merge(base, extra, keep=2, slots=2, k=10)]
    assert got == ["a", "b", "x", "y", "c", "d", "e", "f"]


def test_slot_merge_does_not_duplicate_a_chunk_already_kept():
    from statnav.retrieve.hybrid import slot_merge
    base = [h("a"), h("b"), h("c")]
    got = [r.chunk_id for r in slot_merge(base, [h("a"), h("x")], keep=2, slots=1, k=10)]
    assert got == ["a", "b", "x", "c"]


def test_slot_merge_with_nothing_to_add_is_the_base_ranking():
    from statnav.retrieve.hybrid import slot_merge
    base = [h(c) for c in "abc"]
    assert slot_merge(base, [], keep=2, slots=2, k=2) == base[:2]


@pytest.mark.db
def test_xref_hits_follow_a_reference_both_ways_and_skip_the_seeds(conn):
    """s2(1) cites s515(3)(b), so a seed covering s2(1) must reach the chunk holding it."""
    import numpy as np

    from statnav.retrieve.hybrid import xref_hits
    row = conn.execute("SELECT id FROM chunks WHERE version='v2' AND "
                       "meta->'provisions' ? 's2(1)' LIMIT 1").fetchone()
    seed = by_id_hit(conn, row[0])
    # the seed's own embedding stands in for a query vector
    emb = conn.execute("SELECT embedding FROM chunks WHERE id=%s", (row[0],)).fetchone()[0]
    qvec = emb.to_numpy() if hasattr(emb, "to_numpy") else np.asarray(emb, dtype="float32")
    got = xref_hits(conn, [seed], "v2", qvec, 50)
    assert got and row[0] not in {x.chunk_id for x in got}
    assert any("s515(3)(b)" in (x.meta.get("provisions") or []) for x in got)


def by_id_hit(conn, chunk_id):
    r = conn.execute("SELECT id, provision_id, 0.0, embed_text, tokens, page_start, page_end, "
                     "meta FROM chunks WHERE id=%s", (chunk_id,)).fetchone()
    return Hit(*r)


@pytest.mark.db
def test_under_ids_is_exact_whatever_the_hnsw_search_width():
    """A filtered `ORDER BY embedding <=> q` used to be planned as an HNSW scan that only
    visits ~ef_search neighbours, so s2(52) ("India") came back empty at 40 and 100."""
    import numpy as np

    from statnav.index.db import connect
    from statnav.retrieve.hybrid import under_ids, xref_hits

    try:
        conn = connect()
    except Exception as exc:  # noqa: BLE001 - any connection failure means "skip"
        pytest.skip(f"database not reachable: {exc}")
    qvec = np.ones(1024, dtype=np.float32) / 32.0
    conn.execute("SET hnsw.ef_search = 10")
    assert [h.chunk_id for h in under_ids(conn, ["s2(52)"], "v2", qvec, 2)] == ["v2:s2(52)"]
    seed = under_ids(conn, ["s171"], "v2", qvec, 1)
    assert xref_hits(conn, seed, "v2", qvec, 5)  # s171 has cross-references
    conn.close()
