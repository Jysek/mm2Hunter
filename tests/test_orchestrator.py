"""Tests for the orchestrator helper functions."""

from pathlib import Path

from mm2hunter.orchestrator import _save_discovered_urls


def test_save_discovered_urls(tmp_path: Path):
    urls = [
        "https://site1.example.com",
        "https://site2.example.com",
        "https://site3.example.com",
    ]
    out = _save_discovered_urls(urls, tmp_path)
    assert out.exists()
    assert out.name == "discovered_urls.txt"

    lines = out.read_text().strip().splitlines()
    assert lines == urls


def test_save_discovered_urls_empty(tmp_path: Path):
    out = _save_discovered_urls([], tmp_path)
    assert out.exists()
    assert out.read_text() == ""


def test_save_discovered_urls_creates_dir(tmp_path: Path):
    nested = tmp_path / "sub" / "dir"
    out = _save_discovered_urls(["https://a.com"], nested)
    assert out.exists()
    assert nested.exists()
