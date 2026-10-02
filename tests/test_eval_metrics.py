import pytest

from evals.common import contains, norm
from evals.metrics import aggregate, token_f1


@pytest.mark.parametrize("answer,fact", [
    ("TDS applies when the consideration is ₹50 lakh or more", "Fifty lakh rupees"),
    ("the threshold is Rs 20000", "Rs. 20,000"),
    ("threshold of ₹5,00,000", "Rs. 5,00,000."),
    ("rate is 2 per cent... 2%", "2%"),
    ("a person appointed to be a Deputy Commissioner", "a person appointed to be a Deputy"),
    ("Rates in force apply", "rates in force"),
])
def test_fact_matching_tolerates_formatting(answer, fact):
    assert contains(answer, fact)


def test_money_does_not_conflate_amounts():
    assert not contains("threshold of ₹5 lakh", "Fifty lakh rupees")
    assert norm("Rs. 50,00,000") == norm("fifty lakh rupees")


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
