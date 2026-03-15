"""
Reporting module -- exports validated results to CSV, JSON, and serves a
lightweight web dashboard.

Includes a RealtimeExporter for incremental file updates during search
and validation phases.
"""

from __future__ import annotations

import csv
import json
import threading
from datetime import datetime, timezone
from pathlib import Path

from mm2hunter.scraper.validator import ValidationResult
from mm2hunter.utils.logging import get_logger

logger = get_logger("reporter")


# ---------------------------------------------------------------------------
# File exporters (batch -- kept for backward compatibility)
# ---------------------------------------------------------------------------

def export_json(results: list[ValidationResult], path: Path) -> Path:
    """Write results to a JSON file."""
    data = [r.to_dict() for r in results]
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2, default=str)
    logger.info("JSON report saved -> %s (%d entries)", path, len(data))
    return path


def export_csv(results: list[ValidationResult], path: Path) -> Path:
    """Write results to a CSV file."""
    if not results:
        logger.warning("No results to export.")
        return path

    fieldnames = list(results[0].to_dict().keys())
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        for r in results:
            writer.writerow(r.to_dict())
    logger.info("CSV report saved  -> %s (%d entries)", path, len(results))
    return path


# ---------------------------------------------------------------------------
# Summary helpers
# ---------------------------------------------------------------------------

def summary_stats(results: list[ValidationResult]) -> dict:
    """Return a quick stats dict about the validation run."""
    passed = [r for r in results if r.passed]
    fast = sum(1 for r in results if r.scan_mode == "fast")
    deep = sum(1 for r in results if r.scan_mode == "deep")
    return {
        "total_scanned": len(results),
        "total_passed": len(passed),
        "total_failed": len(results) - len(passed),
        "stripe_detected": sum(1 for r in results if r.has_stripe),
        "wallet_detected": sum(1 for r in results if r.has_wallet),
        "harvester_found": sum(1 for r in results if r.harvester_found),
        "fast_scanned": fast,
        "deep_scanned": deep,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }


# ---------------------------------------------------------------------------
# Realtime exporter -- writes files incrementally
# ---------------------------------------------------------------------------

_CSV_FIELDNAMES = [
    "url", "has_stripe", "has_wallet", "harvester_found",
    "harvester_in_stock", "harvester_price", "passed", "error",
    "scan_mode", "discovered_at",
]


class RealtimeExporter:
    """Thread-safe incremental file writer.

    Keeps ``discovered_urls.txt``, ``results.json``, ``results.csv``,
    and ``stats.json`` up-to-date as URLs are discovered and validated.
    """

    def __init__(self, data_dir: Path) -> None:
        self._data_dir = data_dir
        self._data_dir.mkdir(parents=True, exist_ok=True)

        self._lock = threading.Lock()

        # In-memory accumulators
        self._discovered_urls: list[str] = []
        self._results: list[ValidationResult] = []

        # File paths
        self._disc_path = self._data_dir / "discovered_urls.txt"
        self._json_path = self._data_dir / "results.json"
        self._csv_path = self._data_dir / "results.csv"
        self._stats_path = self._data_dir / "stats.json"

        # Initialize empty files
        self._disc_path.write_text("", encoding="utf-8")
        self._json_path.write_text("[]", encoding="utf-8")
        self._stats_path.write_text(json.dumps(summary_stats([])), encoding="utf-8")

        # CSV: write header
        with open(self._csv_path, "w", newline="", encoding="utf-8") as fh:
            writer = csv.DictWriter(fh, fieldnames=_CSV_FIELDNAMES)
            writer.writeheader()

        # Throttle: avoid flushing JSON/CSV/Stats on every single result
        self._flush_counter = 0
        self._flush_interval = 10  # flush every N results

    # ----- discovered URLs ------------------------------------------------

    def add_discovered_url(self, url: str) -> None:
        """Append a single discovered URL (search phase)."""
        with self._lock:
            self._discovered_urls.append(url)
            with open(self._disc_path, "a", encoding="utf-8") as fh:
                fh.write(url + "\n")

    def add_discovered_urls(self, urls: list[str]) -> None:
        """Append a batch of discovered URLs (search phase)."""
        with self._lock:
            self._discovered_urls.extend(urls)
            with open(self._disc_path, "a", encoding="utf-8") as fh:
                for url in urls:
                    fh.write(url + "\n")

    # ----- validation results ---------------------------------------------

    def add_result(self, result: ValidationResult) -> None:
        """Append a single validation result; flush periodically."""
        with self._lock:
            self._results.append(result)
            self._flush_counter += 1
            if self._flush_counter >= self._flush_interval:
                self._flush_result_files()
                self._flush_counter = 0

    def add_results(self, results: list[ValidationResult]) -> None:
        """Append a batch of validation results and flush."""
        with self._lock:
            self._results.extend(results)
            self._flush_result_files()
            self._flush_counter = 0

    def flush(self) -> None:
        """Force-flush all pending results to disk."""
        with self._lock:
            self._flush_result_files()
            self._flush_counter = 0

    # ----- internal flush -------------------------------------------------

    def _flush_result_files(self) -> None:
        """Rewrite results.json, CSV, and stats.json."""
        # JSON
        data = [r.to_dict() for r in self._results]
        with open(self._json_path, "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=2, default=str)

        # CSV
        with open(self._csv_path, "w", newline="", encoding="utf-8") as fh:
            writer = csv.DictWriter(fh, fieldnames=_CSV_FIELDNAMES)
            writer.writeheader()
            for r in self._results:
                writer.writerow(r.to_dict())

        # Stats
        stats = summary_stats(self._results)
        with open(self._stats_path, "w", encoding="utf-8") as fh:
            json.dump(stats, fh, indent=2)

    # ----- accessors ------------------------------------------------------

    @property
    def discovered_urls(self) -> list[str]:
        with self._lock:
            return list(self._discovered_urls)

    @property
    def results(self) -> list[ValidationResult]:
        with self._lock:
            return list(self._results)

    @property
    def discovered_count(self) -> int:
        with self._lock:
            return len(self._discovered_urls)

    @property
    def results_count(self) -> int:
        with self._lock:
            return len(self._results)
