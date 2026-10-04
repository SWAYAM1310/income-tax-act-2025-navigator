"""Parsing the provision ids a question names (the v3 exact-ID lookup)."""

from statnav.retrieve.ids import ancestors, expand, provision_refs


def test_plain_section():
    assert provision_refs("How was section 427 amended by the Finance Act, 2026?") == ["s427"]


def test_section_with_a_deep_bracket_chain():
    q = "How was section 228(3)(b)(ii)(A) amended by the Finance Act, 2026?"
    assert provision_refs(q) == ["s228(3)(b)(ii)(A)"]


def test_section_with_a_letter_suffix():
    assert provision_refs("what does section 194A say") == ["s194A"]


def test_brackets_may_be_spaced_out():
    assert provision_refs("section 206 (3) (a)") == ["s206(3)(a)"]


def test_schedule_with_part_and_paragraph():
    q = "What change did the Finance Act, 2026 make to Schedule XI, Part A, paragraph 4(f)?"
    assert provision_refs(q) == ["sch:XI:A:4(f)"]


def test_schedule_without_a_part():
    q = "How was Schedule XIV, paragraph 4(1)(a) amended?"
    assert provision_refs(q) == ["sch:XIV:4(1)(a)"]


def test_several_references_keep_question_order_and_dedupe():
    got = provision_refs("does section 90 override section 91, and section 90 again?")
    assert got == ["s90", "s91"]


def test_no_reference_means_no_ids():
    assert provision_refs("how is agricultural income defined") == []
    assert provision_refs("what is the penalty for a late GST return") == []


def test_ancestors_walk_the_bracket_chain_outwards():
    assert ancestors("s228(3)(b)(ii)") == ["s228(3)(b)(ii)", "s228(3)(b)", "s228(3)", "s228"]


def test_ancestors_of_a_letter_suffixed_section_do_not_drop_the_letter():
    """`s80C` must not fall back to `s80`: the suffix is part of the section number.

    A refusal question asks what the 1961 Act's section 80C allowed. The 2025 Act has no 80C,
    only an unrelated section 80, so falling back would hand the model a wrong provision and
    turn a correct refusal into a confident wrong answer.
    """
    assert ancestors("s80C") == ["s80C"]


def test_ancestors_walk_schedule_segments():
    assert ancestors("sch:XI:A:4(f)") == ["sch:XI:A:4(f)", "sch:XI:A:4", "sch:XI:A", "sch:XI"]


def test_expand_is_refs_plus_ancestors_deduped():
    assert expand("section 206(3)(a)") == ["s206(3)(a)", "s206(3)", "s206"]
