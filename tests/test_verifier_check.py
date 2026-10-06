"""The mutation test's corruptions: quantities change, provision numbers and years do not."""

import pytest

from evals.verifier_check import mutate


@pytest.mark.parametrize("answer,expected", [
    ("equal to 30% of cost within 60 days", "equal to 91% of cost within 60 days"),
    ("The TDS rate is 2 % here", "The TDS rate is 7 % here"),
    ("the threshold limit is Rs 1,00,000", "the threshold limit is Rs 300001"),
    ("effective 1-April-2026 under section 393", "effective 4-April-2026 under section 393"),
])
def test_mutate_changes_the_first_quantity(answer, expected):
    assert mutate(answer) == expected


@pytest.mark.parametrize("answer", [
    "the assessment made under section 270(10) or 271;",
    "Section 232(17) was inserted by Act No. 4 of 2026.",
    "as specified for serial number 17 in Table 2",
    "It is defined in clause (c).",
])
def test_mutate_leaves_provision_numbers_and_years_alone(answer):
    assert mutate(answer) is None
