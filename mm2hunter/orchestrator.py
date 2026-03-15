"""
Orchestrator -- wires search, validation, and reporting together.

Uses RealtimeExporter so that output files (discovered_urls.txt,
results.json, results.csv, stats.json) are updated incrementally
as each URL is discovered or validated.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

from mm2hunter.config import AppConfig, get_config
from mm2hunter.reporting.dashboard import Dashboard
from mm2hunter.reporting.exporter import (
    RealtimeExporter,
    export_csv,
    export_json,
    summary_stats,
)
from mm2hunter.scraper.validator import SiteValidator, ValidationResult
from mm2hunter.search.engine import SearchEngine
from mm2hunter.utils.logging import get_logger

logger = get_logger("orchestrator")


def _save_discovered_urls(urls: list[str], data_dir: Path) -> Path:
    """Save all discovered URLs to a TXT file BEFORE validation.

    This allows users to see which sites were found even if validation
    crashes or is interrupted.
    """
    out_path = data_dir / "discovered_urls.txt"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as fh:
        for url in urls:
            fh.write(url + "\n")
    logger.info("Saved %d discovered URLs -> %s", len(urls), out_path)
    return out_path


def _load_urls_from_file(path: str) -> list[str]:
    """Load URLs from a plain-text file (one URL per line).

    Blank lines and lines starting with '#' are skipped.
    """
    urls: list[str] = []
    p = Path(path)
    if not p.is_file():
        logger.error("URL file not found: %s", path)
        return urls
    with open(p, encoding="utf-8") as fh:
        for line in fh:
            stripped = line.strip()
            if stripped and not stripped.startswith("#"):
                urls.append(stripped)
    logger.info("Loaded %d URLs from %s", len(urls), path)
    return urls


# ---------------------------------------------------------------------------
# Validation + reporting (shared by several entry-points)
# ---------------------------------------------------------------------------

async def _validate_and_report(
    cfg: AppConfig,
    urls: list[str],
    rt_exporter: RealtimeExporter | None = None,
) -> list[ValidationResult]:
    """Run Playwright validation on *urls* and export reports.

    If *rt_exporter* is provided, results are written in real-time
    as each URL finishes validation.  A final batch export is still
    performed at the end for consistency.
    """
    if not urls:
        logger.warning("No URLs to validate.")
        return []

    logger.info("=== Validation Phase ===")
    validator = SiteValidator(cfg.scraper, cfg.validation)

    # Build the real-time callback
    def _on_result(result: ValidationResult) -> None:
        if rt_exporter is not None:
            rt_exporter.add_result(result)
            logger.debug(
                "Realtime update: %d results written so far.",
                rt_exporter.results_count,
            )

    results = await validator.validate_many(urls, on_result=_on_result)

    # Final batch export (ensures files are complete and consistent)
    logger.info("=== Reporting Phase ===")
    data_dir = cfg.data_dir
    export_json(results, data_dir / "results.json")
    export_csv(results, data_dir / "results.csv")

    stats = summary_stats(results)
    with open(data_dir / "stats.json", "w") as fh:
        json.dump(stats, fh, indent=2)

    passed = [r for r in results if r.passed]
    logger.info(
        "Pipeline complete. %d/%d sites passed all checks.",
        len(passed),
        len(results),
    )
    for r in passed:
        logger.info("  -> %s  (price=$%.2f)", r.url, r.harvester_price or 0)

    return results


# ---------------------------------------------------------------------------
# Public entry-points
# ---------------------------------------------------------------------------

async def run_pipeline(config: AppConfig | None = None) -> list[ValidationResult]:
    """Execute the full discovery -> validate -> report pipeline.

    Uses RealtimeExporter so discovered URLs and validation results
    are flushed to disk as they arrive.
    """
    cfg = config or get_config()

    # Create realtime exporter
    rt_exporter = RealtimeExporter(cfg.data_dir)

    # 1. Search phase  – URLs are written to disk in real-time
    logger.info("=== Phase 1: Search & Discovery ===")
    engine = SearchEngine(cfg.serper)

    # Use a callback to stream discovered URLs to disk
    def _on_urls_found(new_urls: list[str]) -> None:
        rt_exporter.add_discovered_urls(new_urls)
        logger.info(
            "Realtime: %d total discovered URLs so far.",
            rt_exporter.discovered_count,
        )

    search_results = await engine.search_all(on_results=_on_urls_found)
    urls = [r["url"] for r in search_results]
    logger.info("Discovered %d unique URLs to validate.", len(urls))

    if not urls:
        logger.warning("No URLs found -- check your API keys / queries.")
        return []

    # 2 + 3. Validate & report (real-time)
    return await _validate_and_report(cfg, urls, rt_exporter=rt_exporter)


async def run_validate_raw(
    config: AppConfig | None = None,
    url_file: str = "",
) -> list[ValidationResult]:
    """Validate URLs loaded from a user-supplied file (no search phase)."""
    cfg = config or get_config()

    urls = _load_urls_from_file(url_file)
    if not urls:
        logger.warning("No URLs loaded -- nothing to validate.")
        return []

    # Create realtime exporter and pre-populate with discovered URLs
    rt_exporter = RealtimeExporter(cfg.data_dir)
    rt_exporter.add_discovered_urls(urls)

    return await _validate_and_report(cfg, urls, rt_exporter=rt_exporter)


async def run_dashboard(config: AppConfig | None = None) -> None:
    """Start only the web dashboard (reads existing data files)."""
    cfg = config or get_config()
    dash = Dashboard(cfg.dashboard, cfg.data_dir)
    await dash.start()
    logger.info(
        "Dashboard is live at http://%s:%s -- Press Ctrl+C to stop.",
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
