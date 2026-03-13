"""Tests for configuration loading."""

import os
from mm2hunter.config import AppConfig, SerperConfig


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
