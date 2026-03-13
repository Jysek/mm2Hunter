"""
Playwright-based scraper that validates discovered MM2 shop sites.

Checks performed per site:
  1. Stripe payment gateway detection
  2. "Add Funds" / wallet system detection
  3. Harvester item – stock status & price <= $6.00
"""

from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Dict, List, Optional
from urllib.parse import urljoin, urlparse

from playwright.async_api import Browser, Page, async_playwright

from mm2hunter.config import ScraperConfig, ValidationConfig
from mm2hunter.utils.logging import get_logger

logger = get_logger("validator")

# ---------------------------------------------------------------------------
# Result model
# ---------------------------------------------------------------------------

@dataclass
class ValidationResult:
    url: str
    has_stripe: bool = False
    has_wallet: bool = False
    harvester_found: bool = False
    harvester_in_stock: bool = False
    harvester_price: Optional[float] = None
    passed: bool = False
    error: Optional[str] = None
    discovered_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )

    def to_dict(self) -> Dict:
        return {
            "url": self.url,
            "has_stripe": self.has_stripe,
            "has_wallet": self.has_wallet,
            "harvester_found": self.harvester_found,
            "harvester_in_stock": self.harvester_in_stock,
            "harvester_price": self.harvester_price,
            "passed": self.passed,
            "error": self.error,
            "discovered_at": self.discovered_at,
        }


# ---------------------------------------------------------------------------
# Regex / keyword helpers
# ---------------------------------------------------------------------------

STRIPE_INDICATORS = [
    "js.stripe.com",
    "powered by stripe",
    "stripe.com",
    "stripe-js",
    "stripe elements",
    "pk_live_",
    "pk_test_",
    'class="StripeElement"',
]

WALLET_KEYWORDS = [
    "add funds",
    "wallet",
    "balance",
    "top up",
    "top-up",
    "deposit",
    "add balance",
]

PRICE_RE = re.compile(r"\$\s?(\d{1,4}(?:\.\d{1,2})?)")


# ---------------------------------------------------------------------------
# Validator class
# ---------------------------------------------------------------------------

class SiteValidator:
    """Concurrent site validator powered by Playwright."""

    def __init__(
        self,
        scraper_cfg: ScraperConfig,
        validation_cfg: ValidationConfig,
    ) -> None:
        self._scfg = scraper_cfg
        self._vcfg = validation_cfg

    # ------------------------------------------------------------------
    async def validate_many(self, urls: List[str]) -> List[ValidationResult]:
        """Validate a list of URLs concurrently (bounded concurrency)."""
        sem = asyncio.Semaphore(self._scfg.max_concurrency)

        async with async_playwright() as pw:
            launch_args: dict = {
                "headless": self._scfg.headless,
                "args": [
                    "--disable-blink-features=AutomationControlled",
                    "--no-sandbox",
                ],
            }
            if self._scfg.proxy_url:
                launch_args["proxy"] = {"server": self._scfg.proxy_url}

            browser = await pw.chromium.launch(**launch_args)

            async def _bounded(url: str) -> ValidationResult:
                async with sem:
                    return await self._validate_one(browser, url)

            results = await asyncio.gather(
                *[_bounded(u) for u in urls], return_exceptions=False
            )
            await browser.close()

        return list(results)

    # ------------------------------------------------------------------
    async def _validate_one(self, browser: Browser, url: str) -> ValidationResult:
        """Run all checks on a single URL."""
        result = ValidationResult(url=url)
        context = None
        try:
            context = await browser.new_context(
                user_agent=self._scfg.user_agent,
                viewport={"width": 1280, "height": 720},
                java_script_enabled=True,
            )
            page = await context.new_page()

            # Block heavy resources to speed up loading
            await page.route(
                "**/*.{png,jpg,jpeg,gif,svg,webp,mp4,webm,woff,woff2}",
                lambda route: route.abort(),
            )

            await page.goto(url, wait_until="domcontentloaded",
                            timeout=self._scfg.timeout_ms)
            # Give JS time to render
            await page.wait_for_timeout(3000)

            html = await page.content()
            html_lower = html.lower()

            # 1. Stripe detection
            result.has_stripe = self._detect_stripe(html_lower)

            # 2. Wallet / Add-Funds detection
            result.has_wallet = self._detect_wallet(html_lower)

            # 3. Harvester item check
            await self._check_harvester(page, html_lower, result)

            # Determine pass/fail
            result.passed = (
                (result.has_stripe or not self._vcfg.require_stripe)
                and (result.has_wallet or not self._vcfg.require_wallet)
                and result.harvester_found
                and result.harvester_in_stock
                and result.harvester_price is not None
                and result.harvester_price <= self._vcfg.max_price_usd
            )

        except Exception as exc:
            result.error = f"{type(exc).__name__}: {exc}"
            logger.debug("Validation error for %s: %s", url, result.error)
        finally:
            if context:
                await context.close()

        status = "PASS" if result.passed else "FAIL"
        logger.info("[%s] %s  stripe=%s wallet=%s price=%s stock=%s",
                     status, url[:80], result.has_stripe, result.has_wallet,
                     result.harvester_price, result.harvester_in_stock)
        return result

    # ------------------------------------------------------------------
    # Detection helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _detect_stripe(html_lower: str) -> bool:
        return any(ind.lower() in html_lower for ind in STRIPE_INDICATORS)

    @staticmethod
    def _detect_wallet(html_lower: str) -> bool:
        return any(kw in html_lower for kw in WALLET_KEYWORDS)

    async def _check_harvester(
        self, page: Page, html_lower: str, result: ValidationResult
    ) -> None:
        """Locate the Harvester item, check stock, and extract price."""
        # --- Try to find a link/button leading to a Harvester product page ---
        harvester_links = await page.query_selector_all(
            'a:has-text("Harvester"), [data-product*="harvester" i]'
        )
        if harvester_links:
            try:
                await harvester_links[0].click(timeout=5000)
                await page.wait_for_timeout(2500)
                html_lower = (await page.content()).lower()
            except Exception:
                pass  # stay on the current page

        # Check if "harvester" is even mentioned
        if "harvester" not in html_lower:
            result.harvester_found = False
            return

        result.harvester_found = True

        # --- Stock check ---
        out_of_stock_signals = ["out of stock", "sold out", "unavailable", "disabled"]
        has_oos = any(s in html_lower for s in out_of_stock_signals)

        # Positive signal – enabled "add to cart"
        atc_btns = await page.query_selector_all(
            'button:has-text("Add to Cart"), button:has-text("Buy Now"), '
            'button:has-text("Purchase"), input[value*="Add to Cart" i]'
        )
        atc_enabled = False
        for btn in atc_btns:
            if await btn.is_enabled():
                atc_enabled = True
                break

        result.harvester_in_stock = atc_enabled or (not has_oos and "in stock" in html_lower)

        # --- Price extraction ---
        # Strategy: look near the word "harvester" for a dollar amount
        price_candidates: List[float] = []

        # Search page text segments around "harvester"
        body_text = await page.inner_text("body")
        body_lower = body_text.lower()
        idx = body_lower.find("harvester")
        if idx != -1:
            window = body_text[max(0, idx - 300): idx + 500]
            for match in PRICE_RE.finditer(window):
                try:
                    price_candidates.append(float(match.group(1)))
                except ValueError:
                    pass

        # Fallback: scan all visible prices on the page
        if not price_candidates:
            for match in PRICE_RE.finditer(body_text):
                try:
                    price_candidates.append(float(match.group(1)))
                except ValueError:
                    pass

        if price_candidates:
            # Pick the lowest price in the neighbourhood of "Harvester"
            result.harvester_price = min(price_candidates)
