"""The evidence packing, prompt and citation parsing shared by evals and the chat."""

import json

import pytest

from statnav.answer import (
    ROUTE_BLOCKS,
    SYSTEM_PROMPT,
    Answer,
    AnswerTextStream,
    answer_role,
    follow_ups,
    inline_cites,
    pack,
    parse_citations,
    system_prompt,
    tidy,
    user_prompt,
)


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


# -- v9: explained answers ------------------------------------------------------------------
def test_basic_style_is_the_measured_prompt():
    # v0-v8's cached replies and committed scores depend on this exact text
    assert system_prompt("basic") is SYSTEM_PROMPT
    assert system_prompt("basic", "table") is SYSTEM_PROMPT


@pytest.mark.parametrize("route", ["general", "table", "amendment", "definition"])
def test_explained_prompt_carries_its_route_block_only(route):
    p = system_prompt("explained", route)
    assert ROUTE_BLOCKS[route] in p
    assert all(b not in p for r, b in ROUTE_BLOCKS.items() if r != route)
    for heading in ("### In short", "### What this means for you", "### Example",
                    "### Watch out", "### Key terms"):
        assert heading in p
    assert '"follow_ups"' in p and "{" in p  # the JSON shape survives str.format


def test_explained_prompt_defaults_to_the_general_block():
    assert system_prompt("explained", None) == system_prompt("explained", "general")
    assert system_prompt("explained", "refuse") == system_prompt("explained", "general")


def test_unknown_style_is_an_error():
    with pytest.raises(ValueError):
        system_prompt("chatty")


def test_answer_role_defaults_to_the_measured_one():
    assert answer_role({}) == "answer"
    v9 = {"generation": {"prompt": "explained", "role": "answer_explained"}}
    assert answer_role(v9) == "answer_explained"


def test_inline_cites_only_for_the_explained_style():
    assert inline_cites({"generation": {"prompt": "explained"}})
    assert not inline_cites({"generation": {"prompt": "basic"}})
    assert not inline_cites({})


def test_inline_markers_cite_in_order_without_duplicates():
    ev = [hit("a", 10), hit("b", 10), hit("c", 10)]
    out = {"answer": "Yes [ C3 ]. Limit Rs. 25,000 [C1][C3]. Junk [C9] [c2].",
           "citations": ["C1"]}
    assert [h["chunk_id"] for h in parse_citations(out, ev, inline=True)] == ["a", "c"]
    # the basic style never reads the text, so the committed citation scores cannot move
    assert [h["chunk_id"] for h in parse_citations(out, ev)] == ["a"]


def test_follow_ups_keep_three_non_empty_strings():
    out = {"follow_ups": [" Who is a senior citizen? ", "", 3, "a", "b", "c"]}
    assert follow_ups(out) == ["Who is a senior citizen?", "a", "b"]
    assert follow_ups({"follow_ups": "not a list"}) == []
    assert follow_ups({}) == []


def test_answer_text_stream_keeps_markdown_line_breaks():
    text = "### In short\nYes [C1].\n\n- one\n- **two**"
    reply = json.dumps({"answer": text, "citations": ["C1"]})
    s = AnswerTextStream()
    got = "".join(s.feed(reply[i:i + 5]) for i in range(0, len(reply), 5))
    assert got == text


def test_tidy_keeps_only_key_terms_a_passage_defines():
    ev = [{"text": '(11) "senior citizen" means an individual resident in India of sixty years.'},
          {"text": "Section 126 text."}]
    answer = "\n".join(["### In short", "Yes [C1].",
                        "### Key terms",
                        "- **senior citizen**: an individual of sixty years [C1].",
                        "- **sub-section (1)(a)(i)**: the old clause [C2].",
                        "### Example", "Suppose ..."])
    out = tidy({"answer": answer, "citations": ["C1"], "refused": False}, ev)
    assert "**senior citizen**" in out["answer"] and "(1)(a)(i)" not in out["answer"]
    assert out["answer"].endswith("Suppose ...")


def test_tidy_drops_a_key_terms_section_left_empty_and_hyphens_match():
    ev = [{"text": "“preventive health check‑up” includes a check-up."}]
    answer = "### In short\nYes.\n### Key terms\n- **assessee**: a person.\n"
    assert "Key terms" not in tidy({"answer": answer}, ev)["answer"]
    kept = "### In short\nYes.\n### Key terms\n- **preventive health check-up**: a check.\n"
    assert "Key terms" in tidy({"answer": kept}, ev)["answer"]


def test_tidy_moves_a_follow_ups_section_out_of_the_text():
    answer = "### In short\nYes.\n\n### Follow‑ups\n- What is X?\n- What is Y?"
    out = tidy({"answer": answer, "follow_ups": []}, [])
    assert out["answer"] == "### In short\nYes." and out["follow_ups"] == ["What is X?",
                                                                         "What is Y?"]
    # the listed ones win when the model gave both
    out = tidy({"answer": answer, "follow_ups": ["Z?"]}, [])
    assert out["follow_ups"] == ["Z?"]


def test_tidy_leaves_refusals_and_plain_answers_alone():
    refusal = {"answer": "Not in the Act.", "refused": True}
    assert tidy(refusal, []) is refusal
    assert tidy({"answer": "One paragraph."}, [])["answer"] == "One paragraph."
