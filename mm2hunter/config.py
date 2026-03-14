"""
Central configuration for MM2 Shop Discovery Tool.

All settings can be overridden via environment variables or a .env file.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
DATA_DIR.mkdir(exist_ok=True)


@dataclass
class SerperConfig:
    """Serper.dev search API settings."""

    api_keys: list[str] = field(default_factory=list)
    base_url: str = "https://google.serper.dev/search"
    results_per_query: int = 20  # num param sent to Serper
    max_retries_per_key: int = 2
    pages_per_query: int = 1  # how many pages of results to fetch per query
    queries_file: str | None = None  # path to a TXT file with custom queries

    def __post_init__(self) -> None:
        raw = os.getenv("SERPER_API_KEYS", "")
        if raw:
            self.api_keys = [k.strip() for k in raw.split(",") if k.strip()]
        pages = os.getenv("SERPER_PAGES_PER_QUERY")
        if pages:
            self.pages_per_query = max(1, int(pages))
        self.queries_file = os.getenv("QUERIES_FILE") or None


@dataclass
class ScraperConfig:
    """Playwright scraper settings."""

    headless: bool = True
    timeout_ms: int = 30_000
    max_concurrency: int = 5
    max_threads: int = 5  # worker tasks for validation
    user_agent: str = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    )
    proxy_url: str | None = field(default=None)

    def __post_init__(self) -> None:
        self.headless = os.getenv("SCRAPER_HEADLESS", "true").lower() == "true"
        timeout = os.getenv("SCRAPER_TIMEOUT_MS")
        if timeout:
            self.timeout_ms = int(timeout)
        concurrency = os.getenv("SCRAPER_MAX_CONCURRENCY")
        if concurrency:
            self.max_concurrency = int(concurrency)
        threads = os.getenv("SCRAPER_MAX_THREADS")
        if threads:
            self.max_threads = int(threads)
        self.proxy_url = os.getenv("PROXY_URL") or None


@dataclass
class ValidationConfig:
    """Criteria for validating discovered shops."""

    target_item: str = "Harvester"
    max_price_usd: float = 6.00
    require_stripe: bool = True
    require_wallet: bool = True  # "Add Funds" / wallet system


@dataclass
class DashboardConfig:
    """Web dashboard settings."""

    host: str = "0.0.0.0"
    port: int = 8080

    def __post_init__(self) -> None:
        self.host = os.getenv("DASHBOARD_HOST", self.host)
        port = os.getenv("DASHBOARD_PORT")
        if port:
            self.port = int(port)


@dataclass
class AppConfig:
    """Top-level application config aggregating all sub-configs."""

    serper: SerperConfig = field(default_factory=SerperConfig)
    scraper: ScraperConfig = field(default_factory=ScraperConfig)
    validation: ValidationConfig = field(default_factory=ValidationConfig)
    dashboard: DashboardConfig = field(default_factory=DashboardConfig)
    data_dir: Path = DATA_DIR


# Singleton convenience -------------------------------------------------
_config: AppConfig | None = None


def get_config() -> AppConfig:
    """Return (and lazily create) the global AppConfig singleton."""
    global _config
    if _config is None:
        _config = AppConfig()
    return _config
