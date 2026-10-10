import pytest

from evals.common import contains, norm
from evals.metrics import aggregate, fact_match, stated_numbers, token_f1


@pytest.mark.parametrize("answer,fact", [
    ("TDS applies when the consideration is ₹50 lakh or more", "Fifty lakh rupees"),
    ("the threshold is Rs 20000", "Rs. 20,000"),
    ("threshold of ₹5,00,000", "Rs. 5,00,000."),
    ("rate is 2 per cent... 2%", "2%"),
    ("a person appointed to be a Deputy Commissioner", "a person appointed to be a Deputy"),
    ("Rates in force apply", "rates in force"),
    ("the rate is 2 % for education", "2%"),
    ("TDS at 1 % of the consideration", "1%"),
    ("The rate of tax deducted at source is 2 percent.", "2%"),
    ("at the rate of thirty per cent; or 30 per cent", "30%"),
])
def test_fact_matching_tolerates_formatting(answer, fact):
    assert contains(answer, fact)


def test_money_does_not_conflate_amounts():
    assert not contains("threshold of ₹5 lakh", "Fifty lakh rupees")
    assert norm("Rs. 50,00,000") == norm("fifty lakh rupees")


@pytest.mark.parametrize("answer,fact", [
    ("Tax must be collected at the time of debiting the amount payable by the buyer",
     "at the time of debiting of the amount payable"),
    ("A fixed place of business through which the business is wholly or partly carried on",
     "wholly or partly carried on"),
])
def test_soft_fact_match_accepts_paraphrase(answer, fact):
    assert fact_match(answer, fact)


@pytest.mark.parametrize("answer,fact", [
    ("the period may be extended by a further forty days", "a further period of thirty days"),
    ("the rate is 20%", "rate of 2%"),
    ("the rate is 20 %", "rate of 2%"),
    ("the rate is 20 per cent", "rate of 2%"),
    ("the deduction is allowed in the year of purchase", "in the tax year the asset was sold"),
])
def test_soft_fact_match_rejects_wrong_content(answer, fact):
    assert not fact_match(answer, fact)


def test_token_f1():
    assert token_f1("the cat sat", "the cat sat") == 1.0
    assert token_f1("", "x") == 0.0


def test_aggregate_refusal_precision_recall():
    recs = [
        {"type": "refusal", "metrics": {"refused": 1.0, "should_refuse": 1.0}},
        {"type": "refusal", "metrics": {"refused": 0.0, "should_refuse": 1.0}},
        {"type": "lookup", "metrics": {"refused": 1.0, "should_refuse": 0.0, "fact_recall": 0.0}},
        {"type": "lookup", "metrics": {"refused": 0.0, "should_refuse": 0.0, "fact_recall": 1.0}},
    ]
    m = aggregate(recs)
    assert m["refusal_precision"] == 0.5 and m["refusal_recall"] == 0.5
    assert m["fact_recall"] == 0.5 and m["by_type"]["lookup"]["n"] == 2


@pytest.mark.parametrize("answer,expected", [
    ('the rate was changed from "60%" to "30%"', 1.0),
    ('the rate of "60%" was replaced by "30%"', 1.0),
    ('it substituted "30%" for "60%"', 1.0),
    ('the rate was changed from "30%" to "60%"', 0.0),   # backwards: v6 on 195(1)(i)
    ('replaced "30%" with "60%"', 0.0),
    ('the rate is now 30%', None),                         # only one wording quoted
    ('"60%" appears, and much later, after a long digression about other things, "30%"', None),
])
def test_amendment_direction(answer, expected):
    from evals.metrics import amendment_direction
    assert amendment_direction(answer, "60%", "30%") == expected


def test_amendment_direction_when_old_is_inside_new():
    from evals.metrics import amendment_direction
    old, new = "sub-section (1)(a)(i) or (b)", "sub-section (1)(a)(ii) or (b)"
    assert amendment_direction(f"changed from {old} to {new}", old, new) == 1.0
    assert amendment_direction(f"changed from {new} to {old}", old, new) == 0.0


def test_a_change_type_fact_accepts_its_synonyms():
    assert fact_match('to replace the rate of "60%" with "30%"', "substituted")
    assert fact_match("the clause was newly added", "inserted")
    assert not fact_match("the clause was newly added", "omitted")


def test_stated_numbers_skip_the_worked_example_and_citation_labels():
    answer = "\n".join(["### In short", "Up to Rs. 25,000 [C12].",
                        "### Example", "Suppose you pay Rs. 30,000.", "- 30,000 - 25,000 = 5,000",
                        "### Watch out", "Senior citizens: Rs. 50,000 [C3]."])
    assert stated_numbers(answer) == {"25,000", "50,000"}
    # an answer without sections (v0-v8) is read whole, as before
    assert stated_numbers("Rates 10% and Rs. 20,000 [C1].") == {"10%", "20,000"}
