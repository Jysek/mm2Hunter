"""
Orchestrator – wires search, validation, and reporting together.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import List

from mm2hunter.config import AppConfig, get_config
from mm2hunter.reporting.dashboard import Dashboard
from mm2hunter.reporting.exporter import export_csv, export_json, summary_stats
from mm2hunter.scraper.validator import SiteValidator, ValidationResult
from mm2hunter.search.engine import SearchEngine
from mm2hunter.utils.logging import get_logger

logger = get_logger("orchestrator")


def _save_discovered_urls(urls: List[str], data_dir: Path) -> Path:
    """Save all discovered URLs to a TXT file BEFORE validation.

    This allows users to see which sites were found even if validation
    crashes or is interrupted.
    """
    out_path = data_dir / "discovered_urls.txt"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as fh:
        for url in urls:
            fh.write(url + "\n")
    logger.info("Saved %d discovered URLs → %s", len(urls), out_path)
    return out_path


async def run_pipeline(config: AppConfig | None = None) -> List[ValidationResult]:
    """Execute the full discovery → validate → report pipeline."""
    cfg = config or get_config()

    # 1. Search phase -------------------------------------------------------
    logger.info("=== Phase 1: Search & Discovery ===")
    engine = SearchEngine(cfg.serper)
    search_results = await engine.search_all()
    urls = [r["url"] for r in search_results]
    logger.info("Discovered %d unique URLs to validate.", len(urls))

    if not urls:
        logger.warning("No URLs found – check your API keys / queries.")
        return []

    # 1b. Save discovered URLs BEFORE validation ----------------------------
    _save_discovered_urls(urls, cfg.data_dir)

    # 2. Validation phase ---------------------------------------------------
    logger.info("=== Phase 2: Site Validation ===")
    validator = SiteValidator(cfg.scraper, cfg.validation)
    results = await validator.validate_many(urls)

    # 3. Reporting phase ----------------------------------------------------
    logger.info("=== Phase 3: Reporting ===")
    data_dir = cfg.data_dir
    export_json(results, data_dir / "results.json")
    export_csv(results, data_dir / "results.csv")

    stats = summary_stats(results)
    with open(data_dir / "stats.json", "w") as fh:
        json.dump(stats, fh, indent=2)

    passed = [r for r in results if r.passed]
    logger.info(
        "Pipeline complete. %d/%d sites passed all checks.", len(passed), len(results)
    )
    for r in passed:
        logger.info("  ✔ %s  (price=$%.2f)", r.url, r.harvester_price or 0)

    return results


async def run_dashboard(config: AppConfig | None = None) -> None:
    """Start only the web dashboard (reads existing data files)."""
    cfg = config or get_config()
    dash = Dashboard(cfg.dashboard, cfg.data_dir)
    await dash.start()
    logger.info(
        "Dashboard is live at http://%s:%s – Press Ctrl+C to stop.",
        cfg.dashboard.host,
        cfg.dashboard.port,
    )
    # Keep running forever
    await asyncio.Event().wait()


async def run_full(config: AppConfig | None = None) -> None:
    """Run the pipeline then start the dashboard."""
    cfg = config or get_config()
    await run_pipeline(cfg)
    await run_dashboard(cfg)
