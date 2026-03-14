"""
Reporting module – exports validated results to CSV, JSON, and serves a
lightweight web dashboard.
"""

from __future__ import annotations

import csv
import json
from datetime import datetime, timezone
from pathlib import Path

from mm2hunter.scraper.validator import ValidationResult
from mm2hunter.utils.logging import get_logger

logger = get_logger("reporter")


# ---------------------------------------------------------------------------
# File exporters
# ---------------------------------------------------------------------------

def export_json(results: list[ValidationResult], path: Path) -> Path:
    """Write results to a JSON file."""
    data = [r.to_dict() for r in results]
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2, default=str)
    logger.info("JSON report saved → %s (%d entries)", path, len(data))
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
    logger.info("CSV report saved  → %s (%d entries)", path, len(results))
    return path


# ---------------------------------------------------------------------------
# Summary helpers
# ---------------------------------------------------------------------------

def summary_stats(results: list[ValidationResult]) -> dict:
    """Return a quick stats dict about the validation run."""
    passed = [r for r in results if r.passed]
    return {
        "total_scanned": len(results),
        "total_passed": len(passed),
        "total_failed": len(results) - len(passed),
        "stripe_detected": sum(1 for r in results if r.has_stripe),
        "wallet_detected": sum(1 for r in results if r.has_wallet),
        "harvester_found": sum(1 for r in results if r.harvester_found),
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
