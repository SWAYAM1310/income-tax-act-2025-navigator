"""The lay-person question set: the leak lint, its gold labels and its splits."""

import pytest

from evals.common import SPLITS_DIR, read_jsonl
from evals.lay_lint import copied_run, problems
from evals.splits import LAY
from evals.splits import test_digest as digest


def _q(question: str, **gold) -> dict:
    return {"type": "lookup", "question": question, "gold_provisions": [],
            "gold_table_rows": [], **gold}


def test_lint_flags_named_provisions_and_quoted_terms():
    assert problems(_q("Under section 393, what is the TDS rate on rent?"))
    assert problems(_q("What does Schedule III, Table Sl. No. 24 exempt?"))
    assert problems(_q("What is covered by clause (b) of the definition?"))
    assert problems(_q('What is the meaning of "agricultural income"?'))
    assert not problems(_q("I pay my landlord 60,000 a month. Do I cut tax from the rent?"))


def test_lint_flags_a_copied_run_of_gold_text():
    gold = "Any income by way of rent when paid by person other than specified person"
    assert copied_run("what TDS applies to income by way of rent paid by person other than "
                      "specified person?", gold)
    assert copied_run("I pay rent to my landlord; is tax cut?", gold) is None


@pytest.fixture(scope="module")
def lay(parsed):
    rows = read_jsonl(LAY)
    if not rows:
        pytest.skip("evals/data/lay.jsonl not built")
    return rows


def test_every_lay_row_passes_its_checks(lay):
    from evals.build.lay import check

    bad = {r["id"]: check(r) for r in lay if r["status"] != "rejected" and check(r)}
    assert not bad


def test_hand_written_situations_pass_their_checks(parsed):
    from evals.build.lay import situations

    rows = situations()  # raises on any failing situation
    assert len(rows) == len({r["id"] for r in rows})


def test_paraphrases_come_from_dev_only(lay):
    test_ids = set((SPLITS_DIR / "test.ids").read_text(encoding="utf-8").split())
    golden = {q["id"] for q in read_jsonl(SPLITS_DIR.parent / "data" / "golden.jsonl")}
    pairs = [r["pair_of"] for r in lay if r["style"] == "paraphrase"]
    assert pairs and all(p in golden and p not in test_ids for p in pairs)


def test_lay_splits_are_disjoint_and_lay_test_is_frozen(lay):
    read = lambda n: (SPLITS_DIR / f"{n}.ids").read_text(encoding="utf-8").split()  # noqa: E731
    dev, test, mini = read("lay_dev"), read("lay_test"), read("lay_mini")
    assert not set(dev) & set(test)
    assert set(mini) <= set(dev)
    accepted = {r["id"] for r in lay if r["status"] == "accepted"}
    assert set(dev) | set(test) == accepted
    frozen = (SPLITS_DIR / "lay_test.sha256").read_text(encoding="utf-8").strip()
    assert digest(test) == frozen


def test_load_questions_reads_the_lay_splits(lay):
    from evals.run import load_questions

    dev = load_questions("lay_dev", final=False)
    assert dev and all("style" in q for q in dev)
    assert all(q["style"] == "situation" for q in load_questions("lay_dev:situation", False))
    assert all(q["person"] == "first" for q in load_questions("lay_dev:first", False))
    orig = load_questions("lay_orig", final=False)
    assert orig and all("style" not in q for q in orig)  # golden rows, the Act's wording
    with pytest.raises(SystemExit):
        load_questions("lay_test", final=False)
