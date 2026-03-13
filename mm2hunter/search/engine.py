"""
Serper.dev search client – discovers MM2 shop URLs.
"""

from __future__ import annotations

import asyncio
from typing import Dict, List, Optional, Set

import httpx

from mm2hunter.config import SerperConfig
from mm2hunter.search.key_manager import KeyExhaustedError, KeyManager
from mm2hunter.utils.logging import get_logger

logger = get_logger("search_engine")

# ---------------------------------------------------------------------------
# Pre-built search queries targeting MM2 shops
# ---------------------------------------------------------------------------
SEARCH_QUERIES: List[str] = [
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


class SearchEngine:
    """Sends queries to Serper.dev and collects unique result URLs."""

    def __init__(self, config: SerperConfig) -> None:
        self._cfg = config
        self._km = KeyManager(config.api_keys)
        self._seen_urls: Set[str] = set()

    # ------------------------------------------------------------------
    async def search_all(self) -> List[Dict]:
        """Run every pre-built query and return de-duplicated results."""
        all_results: List[Dict] = []
        for query in SEARCH_QUERIES:
            try:
                results = await self._search(query)
                all_results.extend(results)
            except KeyExhaustedError:
                logger.error("All API keys exhausted – stopping search early.")
                break
            except Exception as exc:
                logger.error("Query failed: %s – %s", query[:60], exc)
        logger.info(
            "Search complete: %d unique URLs discovered.", len(self._seen_urls)
        )
        return all_results

    # ------------------------------------------------------------------
    async def _search(self, query: str) -> List[Dict]:
        """Execute a single search query with automatic key rotation."""
        payload = {"q": query, "num": self._cfg.results_per_query}
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
                logger.warning("HTTP error %s – rotating key.", exc.response.status_code)
                self._km.rotate(reason=str(exc))
            except httpx.RequestError as exc:
                logger.warning("Request error: %s", exc)
                await asyncio.sleep(1)

        logger.warning("Max attempts reached for query: %s", query[:60])
        return []

    # ------------------------------------------------------------------
    def _parse_results(self, data: dict) -> List[Dict]:
        """Extract organic results, de-duplicate by URL."""
        results: List[Dict] = []
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
