"""Database tests. `db`: needs the Postgres container. `jina`: needs JINA_API_KEY and an index
built with `python -m statnav.index.build --version v2`."""

import pytest

from statnav.index.db import connect
from statnav.index.load import load


@pytest.fixture(scope="module")
def conn(parsed):
    try:
        c = connect()
    except Exception as exc:  # noqa: BLE001 - any connection failure means "skip"
        pytest.skip(f"database not reachable: {exc}")
    yield c
    c.close()


@pytest.mark.db
def test_load_matches_artefacts(parsed, conn):
    counts = load()
    assert counts["provisions"] == len(parsed["provisions"])
    assert counts["table_rows"] == len(parsed["rows"])
    assert counts["amendments"] == len(parsed["amendments"])
    row = conn.execute("SELECT rate, threshold, cells->>'Payer' FROM table_rows "
                       "WHERE row_id = 's393:tbl1#1(i)'").fetchone()
    assert row == ("Rates in force.", "Rs. 20,000.", "Any person.")
    linked = conn.execute("SELECT provision_id FROM amendment_links l JOIN amendments a "
                          "USING (key) WHERE a.label = '1' AND a.page = 10").fetchall()
    assert linked == [("s2(32)",)]
    ref = conn.execute("SELECT to_id FROM cross_refs WHERE from_id = 's2(1)'").fetchone()
    assert ref == ("s515(3)(b)",)


@pytest.mark.db
@pytest.mark.jina
@pytest.mark.parametrize("query,expected,k", [
    ("How does the Act define agricultural income?", "s2(5)", 1),
    ("What is the TDS rate and threshold on insurance commission paid to a resident?",
     "s393:tbl1#1(i)", 5),
    ("Who is an accountant for the purposes of the Act?", "s2(1)", 5),
])
def test_dense_retrieval_fixtures(conn, query, expected, k):
    from statnav.embed.jina import JinaClient
    from statnav.retrieve.dense import search

    n = conn.execute("SELECT count(*) FROM chunks WHERE version = 'v2'").fetchone()[0]
    if n == 0:
        pytest.skip("v2 index not built")
    hits = search(conn, JinaClient.from_config(), query, "v2", k)
    covered = [p for h in hits for p in h.meta["provisions"]]
    assert expected in covered, [h.chunk_id for h in hits]
