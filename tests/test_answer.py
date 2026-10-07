"""The evidence packing, prompt and citation parsing shared by evals and the chat."""

import json

from statnav.answer import Answer, AnswerTextStream, pack, parse_citations, user_prompt


def hit(cid: str, tokens: int, **kw) -> dict:
    return {"chunk_id": cid, "text": f"text of {cid}", "tokens": tokens,
            "provisions": kw.get("provisions", [cid.split(":", 1)[-1]]),
            "page_start": kw.get("page_start", 7), "page_end": kw.get("page_end", 8)}


def test_pack_keeps_rank_order_and_skips_only_what_overflows():
    hits = [hit("a", 100), hit("b", 5000), hit("c", 200)]
    kept = pack(hits, 500)
    # b overflows and is skipped, but c still fits: packing is greedy, not "stop at first miss"
    assert [h["chunk_id"] for h in kept] == ["a", "c"]


def test_pack_respects_the_budget():
    hits = [hit(str(n), 300) for n in range(10)]
    kept = pack(hits, 1000)
    assert sum(h["tokens"] for h in kept) <= 1000
    assert len(kept) == 3


def test_user_prompt_numbers_passages_from_one_and_carries_pages():
    p = user_prompt("what is x?", [hit("a", 10), hit("b", 10, page_start=0, page_end=0)])
    assert "Question: what is x?" in p
    assert "[C1] (pp. 7-8)" in p
    assert "[C2]\n" in p  # no page range when the chunk has none
    assert p.index("[C1]") < p.index("[C2]")


def test_parse_citations_accepts_the_shapes_the_model_emits():
    ev = [hit("a", 10), hit("b", 10), hit("c", 10)]
    out = {"citations": ["C1", "[C3]", " C2 ", 2]}
    assert [h["chunk_id"] for h in parse_citations(out, ev)] == ["a", "c", "b", "b"]


def test_parse_citations_is_case_sensitive_today():
    """Pins current behaviour: a lowercase "c1" is dropped, not resolved.

    The ladder's committed citation scores were measured with this parser, so widening it
    would move those numbers. Revisit when a version changes the prompt.
    """
    assert parse_citations({"citations": ["c1"]}, [hit("a", 10)]) == []


def test_parse_citations_drops_out_of_range_and_junk():
    ev = [hit("a", 10)]
    assert parse_citations({"citations": ["C9", "C0", "nonsense", ""]}, ev) == []
    assert parse_citations({}, ev) == []
    assert parse_citations({"citations": None}, ev) == []


def test_answer_provisions_dedupes_in_citation_order():
    res = Answer(question="q", answer="a", refused=False, cited=[
        hit("x", 1, provisions=["s2(5)", "s2(5)(a)"]),
        hit("y", 1, provisions=["s2(5)", "s9"]),
    ])
    assert res.provisions == ["s2(5)", "s2(5)(a)", "s9"]


def _stream(chunks: list[str]) -> tuple[list[str], AnswerTextStream]:
    parser = AnswerTextStream()
    return [parser.feed(c) for c in chunks], parser


def test_answer_text_stream_decodes_escapes_split_across_pieces():
    reply = json.dumps({"answer": 'Rate "2%" ₹ 20,000\nand more', "citations": ["C1"]},
                       ensure_ascii=True)
    pieces, parser = _stream([reply[i:i + 3] for i in range(0, len(reply), 3)])
    assert "".join(pieces) == parser.text == 'Rate "2%" ₹ 20,000\nand more'
    assert parser.done and parser.feed('", "x": "y"}') == ""


def test_answer_text_stream_skips_other_keys_and_fences():
    _, parser = _stream(['```json\n{"citations": ["C1"], "refused": false, "ans',
                         'wer" :  "Section 2(5)', ' says so."}\n```'])
    assert parser.text == "Section 2(5) says so."


def test_answer_text_stream_waits_for_an_answer_key():
    pieces, parser = _stream(["no json here", " at all"])
    assert pieces == ["", ""] and parser.text == "" and not parser.done
