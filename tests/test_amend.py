"""Attaching the Act's amendment endnotes to the provisions they amend (v4)."""

import pytest

from statnav.retrieve.amend import _label_key, attach, endnotes_for
from statnav.retrieve.dense import Hit


def hit(cid: str, provisions: list[str], text: str = "body", tokens: int = 5) -> Hit:
    return Hit(cid, cid, 0.5, text, tokens, 1, 1, {"provisions": provisions})


def test_label_key_sorts_numeric_labels_as_numbers():
    assert sorted(["11", "2", "35"], key=_label_key) == ["2", "11", "35"]


def test_label_key_puts_non_numeric_labels_last():
    assert sorted(["7", "a", "3"], key=_label_key) == ["3", "7", "a"]


def test_attach_of_nothing_is_nothing():
    assert attach(None, []) == []


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
def test_endnotes_for_finds_the_s99_2_substitution(conn):
    """s99(2) is the case that made v3 refuse: perfect retrieval, no evidence of the change."""
    got = endnotes_for(conn, ["s99(2)"])
    assert "s99(2)" in got
    line = " ".join(got["s99(2)"])
    assert line.startswith("Endnote ")
    assert "Act No. 4 of 2026" in line


@pytest.mark.db
def test_endnotes_for_is_empty_for_an_unamended_provision(conn):
    assert endnotes_for(conn, ["s2(5)(d)"]) == {} or "s2(5)(d)" not in endnotes_for(
        conn, ["s2(5)(d)"])


@pytest.mark.db
def test_endnotes_for_no_provisions(conn):
    assert endnotes_for(conn, []) == {}


@pytest.mark.db
def test_attach_appends_the_endnote_and_recounts_tokens(conn):
    h = hit("v2:s99(2)", ["s99(2)"], text="(2) If the asset transferred ...", tokens=9)
    out = attach(conn, [h])[0]
    assert "Endnote" in out.text
    assert out.text.startswith("(2) If the asset transferred ...")
    assert out.tokens > h.tokens, "tokens must be re-counted or packing would overflow"
    assert out.chunk_id == h.chunk_id and out.meta == h.meta


@pytest.mark.db
def test_attach_leaves_an_unamended_chunk_untouched(conn):
    h = hit("v2:nothing", ["s-does-not-exist"], text="body", tokens=5)
    out = attach(conn, [h])[0]
    assert out is h


@pytest.mark.db
def test_attach_does_not_repeat_one_endnote_for_a_chunk_covering_several_provisions(conn):
    # a chunk covers a provision and its parent; a shared endnote must appear once
    h = hit("v2:s99", ["s99", "s99(2)", "s99(2)"], text="body", tokens=5)
    out = attach(conn, [h])[0]
    assert out.text.count("Endnote 11:") == 1
