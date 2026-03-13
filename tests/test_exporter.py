"""Tests for the reporting / export module."""

import json
import csv
from pathlib import Path

from mm2hunter.scraper.validator import ValidationResult
from mm2hunter.reporting.exporter import export_csv, export_json, summary_stats


def _sample_results():
    return [
        ValidationResult(
            url="https://shop1.example.com",
            has_stripe=True,
            has_wallet=True,
            harvester_found=True,
            harvester_in_stock=True,
            harvester_price=4.50,
            passed=True,
        ),
        ValidationResult(
            url="https://shop2.example.com",
            has_stripe=False,
            has_wallet=True,
            harvester_found=True,
            harvester_in_stock=False,
            harvester_price=8.00,
            passed=False,
        ),
    ]


def test_export_json(tmp_path: Path):
    results = _sample_results()
    path = tmp_path / "out.json"
    export_json(results, path)
    data = json.loads(path.read_text())
    assert len(data) == 2
    assert data[0]["url"] == "https://shop1.example.com"
    assert data[0]["passed"] is True


def test_export_csv(tmp_path: Path):
    results = _sample_results()
    path = tmp_path / "out.csv"
    export_csv(results, path)
    with open(path) as fh:
        reader = list(csv.DictReader(fh))
    assert len(reader) == 2
    assert reader[1]["has_stripe"] == "False"


def test_summary_stats():
    results = _sample_results()
    stats = summary_stats(results)
    assert stats["total_scanned"] == 2
    assert stats["total_passed"] == 1
    assert stats["stripe_detected"] == 1
