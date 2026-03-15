"""Tests for configuration loading."""

from mm2hunter.config import AppConfig, SerperConfig, ScraperConfig


def test_default_config():
    cfg = AppConfig()
    assert cfg.validation.max_price_usd == 6.00
    assert cfg.validation.target_item == "Harvester"
    assert cfg.scraper.headless is True
    assert cfg.dashboard.port == 8080


def test_serper_keys_from_env(monkeypatch):
    monkeypatch.setenv("SERPER_API_KEYS", "key_a, key_b, key_c")
    sc = SerperConfig()
    assert sc.api_keys == ["key_a", "key_b", "key_c"]


def test_serper_empty_env(monkeypatch):
    monkeypatch.delenv("SERPER_API_KEYS", raising=False)
    sc = SerperConfig()
    assert sc.api_keys == []


def test_scraper_defaults():
    cfg = ScraperConfig()
    assert cfg.max_concurrency == 200
    assert cfg.deep_scan_concurrency == 5
    assert cfg.enable_deep_scan is True


def test_scraper_concurrency_from_env(monkeypatch):
    monkeypatch.setenv("SCRAPER_MAX_CONCURRENCY", "500")
    cfg = ScraperConfig()
    assert cfg.max_concurrency == 500


def test_deep_scan_env(monkeypatch):
    monkeypatch.setenv("ENABLE_DEEP_SCAN", "false")
    cfg = ScraperConfig()
    assert cfg.enable_deep_scan is False
