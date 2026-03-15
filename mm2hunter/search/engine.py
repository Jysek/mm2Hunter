"""
Serper.dev search client – discovers MM2 shop URLs.

Supports:
  - Built-in queries or loading custom queries from a TXT file
  - Multiple pages per query for more results
  - Real-time callback to stream discovered URLs as they arrive
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Callable

import httpx

from mm2hunter.config import SerperConfig
from mm2hunter.search.key_manager import KeyExhaustedError, KeyManager
from mm2hunter.utils.logging import get_logger

logger = get_logger("search_engine")

# ---------------------------------------------------------------------------
# Pre-built search queries targeting MM2 shops
# ---------------------------------------------------------------------------
DEFAULT_QUERIES: list[str] = [
    '"Murder Mystery 2" "Harvester" "Add Funds" "Powered by Stripe"',
    '"MM2" shop "Harvester" buy "Add Funds" stripe',
    '"Murder Mystery 2" shop buy "Harvester" wallet "add funds"',
    '"MM2" "Harvester" price "in stock" "add to cart" stripe',
    '"Murder Mystery 2" store "Harvester" cheap buy now stripe',
    '"MM2" godly "Harvester" shop payment stripe wallet',
    '"Roblox MM2" buy "Harvester" "add funds" stripe checkout',
    '"Murder Mystery 2" items shop "Harvester" stock stripe',
    'buy MM2 Harvester cheap stripe "add funds" wallet',
    '"MM2 shop" Harvester price stock stripe "powered by"',
]

ROTATE_STATUS_CODES = {403, 429}

# Type alias for the callback that receives newly discovered URLs
OnResultsCallback = Callable[[list[str]], None] | None


def load_queries_from_file(path: str) -> list[str]:
    """Load search queries from a TXT file (one query per line).

    Blank lines and lines starting with '#' are ignored.
    """
    file_path = Path(path)
    if not file_path.exists():
        logger.error("Queries file not found: %s", path)
        return []

    queries: list[str] = []
    with open(file_path, encoding="utf-8") as fh:
        for line in fh:
            stripped = line.strip()
            if stripped and not stripped.startswith("#"):
                queries.append(stripped)

    logger.info("Loaded %d queries from %s", len(queries), path)
    return queries


class SearchEngine:
    """Sends queries to Serper.dev and collects unique result URLs."""

    def __init__(self, config: SerperConfig) -> None:
        self._cfg = config
        self._km = KeyManager(config.api_keys)
        self._seen_urls: set[str] = set()

    # ------------------------------------------------------------------
    def _get_queries(self) -> list[str]:
        """Return the list of queries to execute.

        If a queries file is configured and valid, those queries are used.
        Otherwise, fall back to the built-in default queries.
        """
        if self._cfg.queries_file:
            custom = load_queries_from_file(self._cfg.queries_file)
            if custom:
                return custom
            logger.warning(
                "Queries file was empty or missing – falling back to defaults."
            )
        return list(DEFAULT_QUERIES)

    # ------------------------------------------------------------------
    async def search_all(
        self,
        on_results: OnResultsCallback = None,
    ) -> list[dict]:
        """Run every query (possibly multiple pages each) and return
        de-duplicated results.

        If *on_results* is provided it is called with the list of **new**
        URL strings each time a query page returns results, enabling
        real-time file writes.
        """
        queries = self._get_queries()
        all_results: list[dict] = []
        pages = max(1, self._cfg.pages_per_query)

        for query in queries:
            for page_num in range(1, pages + 1):
                try:
                    results = await self._search(query, page=page_num)
                    all_results.extend(results)

                    # Fire the callback with newly discovered URLs
                    if results and on_results is not None:
                        new_urls = [r["url"] for r in results]
                        on_results(new_urls)

                except KeyExhaustedError:
                    logger.error("All API keys exhausted – stopping search early.")
                    break
                except Exception as exc:
                    logger.error(
                        "Query failed (page %d): %s – %s", page_num, query[:60], exc
                    )
            else:
                continue  # inner loop finished normally
            break  # KeyExhaustedError – stop outer loop too

        logger.info(
            "Search complete: %d unique URLs discovered.", len(self._seen_urls)
        )
        return all_results

    # ------------------------------------------------------------------
    async def _search(self, query: str, *, page: int = 1) -> list[dict]:
        """Execute a single search query with automatic key rotation.

        Serper.dev uses a 'page' parameter (1-based) or 'start' offset.
        We use the 'page' parameter for pagination.
        """
        payload: dict = {
            "q": query,
            "num": self._cfg.results_per_query,
        }
        if page > 1:
            payload["page"] = page

        attempt = 0
        max_attempts = self._km.alive_count * self._cfg.max_retries_per_key

        while attempt < max_attempts:
            attempt += 1
            headers = {
                "X-API-KEY": self._km.current_key,
                "Content-Type": "application/json",
            }
            try:
                async with httpx.AsyncClient(timeout=15) as client:
                    resp = await client.post(
                        self._cfg.base_url, json=payload, headers=headers
                    )

                if resp.status_code in ROTATE_STATUS_CODES:
                    self._km.rotate(reason=f"HTTP {resp.status_code}")
                    continue

                resp.raise_for_status()
                self._km.mark_success()
                return self._parse_results(resp.json())

            except KeyExhaustedError:
                raise
            except httpx.HTTPStatusError as exc:
                logger.warning(
                    "HTTP error %s – rotating key.", exc.response.status_code
                )
                self._km.rotate(reason=str(exc))
            except httpx.RequestError as exc:
                logger.warning("Request error: %s", exc)
                await asyncio.sleep(1)

        logger.warning("Max attempts reached for query: %s (page %d)", query[:60], page)
        return []

    # ------------------------------------------------------------------
    def _parse_results(self, data: dict) -> list[dict]:
        """Extract organic results, de-duplicate by URL."""
        results: list[dict] = []
        for item in data.get("organic", []):
            url = item.get("link", "")
            if url and url not in self._seen_urls:
                self._seen_urls.add(url)
                results.append(
                    {
                        "url": url,
                        "title": item.get("title", ""),
                        "snippet": item.get("snippet", ""),
                    }
                )
        return results

    # ------------------------------------------------------------------
    @property
    def discovered_count(self) -> int:
        return len(self._seen_urls)

    @property
    def all_discovered_urls(self) -> list[str]:
        """Return a sorted list of all discovered URLs."""
        return sorted(self._seen_urls)
