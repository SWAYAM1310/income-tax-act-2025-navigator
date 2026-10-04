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
