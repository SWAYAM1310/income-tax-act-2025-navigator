"""Rebuilding a provision's wording before the Finance Act, 2026 from its tagged brackets."""

from statnav.repo import before_after


def note(label, kind, endnote, prior=None):
    return {"label": label, "type": kind, "endnote": endnote, "prior_text": prior}


def test_substitution_restores_the_quoted_words():
    got = before_after('If transferred under {{fn:11}}[sub-section (1)(a)(ii) or (b)] it is.',
                       [note("11", "substituted",
                             'Sub. for "sub-section (1)(a)(i) or (b)" by Act No. 4 of 2026.')])
    assert got["before"] == "If transferred under sub-section (1)(a)(i) or (b) it is."
    seg = got["segments"][1]
    assert (seg["label"], seg["type"], seg["was"]) == ("11", "substituted",
                                                       "sub-section (1)(a)(i) or (b)")


def test_insertion_drops_the_words_and_tidies_punctuation():
    got = before_after("a return of loss {{fn:47}}[except in a case referred to]; or",
                       [note("47", "inserted", "Ins. by Act No. 4 of 2026.")])
    assert got["before"] == "a return of loss; or"


def test_a_wholly_inserted_provision_did_not_exist_before():
    got = before_after("{{fn:52}}[ The amount not deductible shall be allowed later.] C.",
                       [note("52", "inserted", "Ins. by Act No. 4 of 2026.")])
    assert got["before"] == ""


def test_printed_prior_text_wins():
    got = before_after('{{fn:1}}[ "co-operative society" means a new thing.]',
                       [note("1", "substituted", "Sub. by Act No. 4 of 2026. Prior to its "
                             "substitution, clause (32) read as under :", "(32) the old thing")])
    assert got["before"] == "(32) the old thing"


def test_unknown_earlier_wording_is_none_not_a_guess():
    got = before_after("the {{fn:9}}[new words] apply",
                       [note("9", "substituted", "Sub. by Act No. 4 of 2026.")])
    assert got["before"] is None and got["segments"][1]["was"] is None
