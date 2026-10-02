from statnav.config import _expand, base_config, pdf_path


def test_env_expansion_keeps_types(monkeypatch):
    monkeypatch.delenv("STATNAV_TEST_PORT", raising=False)
    assert _expand("${STATNAV_TEST_PORT:5433}") == 5433
    monkeypatch.setenv("STATNAV_TEST_PORT", "6000")
    assert _expand("${STATNAV_TEST_PORT:5433}") == 6000
    assert _expand("host-${STATNAV_TEST_PORT:1}") == "host-6000"


def test_base_config_points_at_pdf():
    cfg = base_config()
    assert cfg["source"]["pages"] == 666
    assert pdf_path().name == "Income-tax-Act-2025.pdf"
