from statnav.ingest.qa import THRESHOLDS, scorecard


def test_ingestion_scorecard_meets_thresholds(parsed):
    card = scorecard()
    failed = {k: card[k] for k, ok in card["passed"].items() if not ok}
    assert not failed, f"below threshold {THRESHOLDS}: {failed}"
    assert card["header_footer_residue"] == 0
    assert card["duplicate_ids"] == 0
