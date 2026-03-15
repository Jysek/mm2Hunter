"""Tests for the reporting / export module."""

import json
import csv
from pathlib import Path

from mm2hunter.scraper.validator import ValidationResult
from mm2hunter.reporting.exporter import (
    export_csv,
    export_json,
    summary_stats,
    RealtimeExporter,
)


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
            scan_mode="fast",
        ),
        ValidationResult(
            url="https://shop2.example.com",
            has_stripe=False,
            has_wallet=True,
            harvester_found=True,
            harvester_in_stock=False,
            harvester_price=8.00,
            passed=False,
            scan_mode="fast",
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
    assert data[0]["scan_mode"] == "fast"


def test_export_csv(tmp_path: Path):
    results = _sample_results()
    path = tmp_path / "out.csv"
    export_csv(results, path)
    with open(path) as fh:
        reader = list(csv.DictReader(fh))
    assert len(reader) == 2
    assert reader[1]["has_stripe"] == "False"
    assert reader[0]["scan_mode"] == "fast"


def test_summary_stats():
    results = _sample_results()
    stats = summary_stats(results)
    assert stats["total_scanned"] == 2
    assert stats["total_passed"] == 1
    assert stats["stripe_detected"] == 1
    assert stats["fast_scanned"] == 2
    assert stats["deep_scanned"] == 0


def test_summary_stats_with_deep():
    results = _sample_results()
    results[0].scan_mode = "deep"
    stats = summary_stats(results)
    assert stats["fast_scanned"] == 1
    assert stats["deep_scanned"] == 1


# ---------------------------------------------------------------------------
# RealtimeExporter tests
# ---------------------------------------------------------------------------

def test_realtime_init_creates_empty_files(tmp_path: Path):
    """RealtimeExporter should create empty placeholder files on init."""
    rt = RealtimeExporter(tmp_path / "rt_data")

    assert (tmp_path / "rt_data" / "discovered_urls.txt").exists()
    assert (tmp_path / "rt_data" / "results.json").exists()
    assert (tmp_path / "rt_data" / "results.csv").exists()
    assert (tmp_path / "rt_data" / "stats.json").exists()

    data = json.loads((tmp_path / "rt_data" / "results.json").read_text())
    assert data == []


def test_realtime_add_discovered_url(tmp_path: Path):
    """add_discovered_url should append to the TXT file immediately."""
    rt = RealtimeExporter(tmp_path)

    rt.add_discovered_url("https://a.example.com")
    rt.add_discovered_url("https://b.example.com")

    lines = (tmp_path / "discovered_urls.txt").read_text().strip().splitlines()
    assert lines == ["https://a.example.com", "https://b.example.com"]
    assert rt.discovered_count == 2


def test_realtime_add_discovered_urls_batch(tmp_path: Path):
    """add_discovered_urls should append a batch at once."""
    rt = RealtimeExporter(tmp_path)

    rt.add_discovered_urls(["https://x.com", "https://y.com", "https://z.com"])

    lines = (tmp_path / "discovered_urls.txt").read_text().strip().splitlines()
    assert len(lines) == 3
    assert rt.discovered_count == 3


def test_realtime_add_result_updates_files(tmp_path: Path):
    """add_result should flush after reaching the flush interval."""
    rt = RealtimeExporter(tmp_path)

    r1 = ValidationResult(
        url="https://shop1.example.com",
        has_stripe=True,
        has_wallet=True,
        harvester_found=True,
        harvester_in_stock=True,
        harvester_price=4.50,
        passed=True,
    )
    rt.add_result(r1)
    rt.flush()  # Force flush since interval may not be reached

    # JSON
    data = json.loads((tmp_path / "results.json").read_text())
    assert len(data) == 1
    assert data[0]["url"] == "https://shop1.example.com"

    # CSV
    with open(tmp_path / "results.csv") as fh:
        rows = list(csv.DictReader(fh))
    assert len(rows) == 1

    # Stats
    stats = json.loads((tmp_path / "stats.json").read_text())
    assert stats["total_scanned"] == 1
    assert stats["total_passed"] == 1


def test_realtime_add_results_batch(tmp_path: Path):
    """add_results should flush immediately."""
    rt = RealtimeExporter(tmp_path)

    results = [
        ValidationResult(url="https://a.com", passed=True),
        ValidationResult(url="https://b.com", passed=False),
    ]
    rt.add_results(results)

    data = json.loads((tmp_path / "results.json").read_text())
    assert len(data) == 2


def test_realtime_results_property(tmp_path: Path):
    """The results property should return a copy of accumulated results."""
    rt = RealtimeExporter(tmp_path)

    r1 = ValidationResult(url="https://a.com", passed=True)
    r2 = ValidationResult(url="https://b.com", passed=False)
    rt.add_result(r1)
    rt.add_result(r2)

    results = rt.results
    assert len(results) == 2
    assert results[0].url == "https://a.com"
    assert results[1].url == "https://b.com"


def test_realtime_flush(tmp_path: Path):
    """flush() should force write even below the interval."""
    rt = RealtimeExporter(tmp_path)

    rt.add_result(ValidationResult(url="https://x.com", passed=True))
    rt.flush()

    data = json.loads((tmp_path / "results.json").read_text())
    assert len(data) == 1
