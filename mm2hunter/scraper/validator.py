"""
High-performance site validator for MM2 shops.

Architecture (two-tier):
  1. **Fast Scan** – pure async HTTP with httpx (250-500 URLs/sec).
     Downloads HTML, runs regex/string checks for Stripe, wallet, Harvester.
  2. **Deep Scan** (optional) – Playwright headless Chromium for URLs that
     pass the fast scan.  Runs JS, intercepts network, checks DOM.

The fast scan alone is sufficient for most detection.  Deep scan adds
confidence for edge cases (JS-only rendered content).
"""

from __future__ import annotations

import asyncio
import re
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Callable, Awaitable

import httpx

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
    harvester_price: float | None = None
    passed: bool = False
    error: str | None = None
    stripe_evidence: list[str] = field(default_factory=list)
    scan_mode: str = "fast"  # "fast" or "deep"
    discovered_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )

    def to_dict(self) -> dict:
        return {
            "url": self.url,
            "has_stripe": self.has_stripe,
            "has_wallet": self.has_wallet,
            "harvester_found": self.harvester_found,
            "harvester_in_stock": self.harvester_in_stock,
            "harvester_price": self.harvester_price,
            "passed": self.passed,
            "error": self.error,
            "scan_mode": self.scan_mode,
            "discovered_at": self.discovered_at,
        }


# ---------------------------------------------------------------------------
# Regex / keyword helpers
# ---------------------------------------------------------------------------

STRIPE_HTML_INDICATORS = [
    "js.stripe.com",
    "stripe.com/v3",
    "stripe.com/v2",
    "powered by stripe",
    "stripe.js",
    "stripe-js",
    "stripe elements",
    "@stripe/stripe-js",
    "@stripe/react-stripe-js",
    "pk_live_",
    "pk_test_",
    'class="stripeelement"',
    "__stripe_mid",
    "__stripe_sid",
    "stripe-payment",
    "stripe-card",
    "stripe-element",
    "stripe-form",
    "data-stripe",
    "stripecheckout",
    "stripe_publishable",
    "stripe_public_key",
    "checkout.stripe.com",
    "api.stripe.com",
    "m.stripe.com",
    "m.stripe.network",
    "q.stripe.com",
    "r.stripe.com",
    "hooks.stripe.com",
    "invoice.stripe.com",
    "billing.stripe.com",
    "connect.stripe.com",
]

STRIPE_SCRIPT_PATTERNS = [
    re.compile(r"Stripe\s*\(", re.I),
    re.compile(r"loadStripe\s*\(", re.I),
    re.compile(r"stripe\.createPaymentMethod", re.I),
    re.compile(r"stripe\.confirmCardPayment", re.I),
    re.compile(r"stripe\.confirmPayment", re.I),
    re.compile(r"stripe\.createToken", re.I),
    re.compile(r"stripe\.createSource", re.I),
    re.compile(r"stripe\.elements\s*\(", re.I),
    re.compile(r"stripe\.redirectToCheckout", re.I),
    re.compile(r"stripe\.paymentRequest", re.I),
    re.compile(r"stripe\.handleCardAction", re.I),
    re.compile(r"createPaymentIntent", re.I),
    re.compile(r"payment_intent", re.I),
    re.compile(r"client_secret.*pi_", re.I),
    re.compile(r"pk_(live|test)_[A-Za-z0-9]+", re.I),
]

STRIPE_NETWORK_PATTERNS = [
    re.compile(r"js\.stripe\.com", re.I),
    re.compile(r"api\.stripe\.com", re.I),
    re.compile(r"m\.stripe\.com", re.I),
    re.compile(r"m\.stripe\.network", re.I),
    re.compile(r"q\.stripe\.com", re.I),
    re.compile(r"r\.stripe\.com", re.I),
    re.compile(r"checkout\.stripe\.com", re.I),
    re.compile(r"hooks\.stripe\.com", re.I),
    re.compile(r"billing\.stripe\.com", re.I),
    re.compile(r"connect\.stripe\.com", re.I),
    re.compile(r"invoice\.stripe\.com", re.I),
    re.compile(r"merchant-ui-api\.stripe\.com", re.I),
    re.compile(r"pay\.stripe\.com", re.I),
    re.compile(r"payments\.stripe\.com", re.I),
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

# Type alias for result callback
ResultCallback = (
    Callable[[ValidationResult], Awaitable[None]]
    | Callable[[ValidationResult], None]
    | None
)


# ---------------------------------------------------------------------------
# Fast scan helpers (pure string / regex on raw HTML)
# ---------------------------------------------------------------------------


def _detect_stripe_fast(html_lower: str) -> tuple[bool, list[str]]:
    """Detect Stripe indicators from raw HTML (string + regex)."""
    evidence: list[str] = []

    # Layer 1: HTML string indicators
    for indicator in STRIPE_HTML_INDICATORS:
        if indicator.lower() in html_lower:
            evidence.append(f"html:{indicator}")

    # Layer 2: Script patterns (inline JS)
    for pat in STRIPE_SCRIPT_PATTERNS:
        if pat.search(html_lower):
            evidence.append(f"script:{pat.pattern[:40]}")

    # De-duplicate
    evidence = list(dict.fromkeys(evidence))
    return len(evidence) > 0, evidence


def _detect_wallet_fast(html_lower: str) -> bool:
    """Detect wallet / add-funds keywords."""
    return any(kw in html_lower for kw in WALLET_KEYWORDS)


def _check_harvester_fast(html_lower: str) -> tuple[bool, bool, float | None]:
    """Check Harvester presence, stock, and price from raw HTML.

    Returns (found, in_stock, price).
    """
    if "harvester" not in html_lower:
        return False, False, None

    # Stock check
    out_of_stock = ["out of stock", "sold out", "unavailable"]
    has_oos = any(s in html_lower for s in out_of_stock)

    in_stock_signals = ["in stock", "add to cart", "buy now", "purchase"]
    has_in_stock = any(s in html_lower for s in in_stock_signals)
    in_stock = has_in_stock or not has_oos

    # Price extraction – look near "harvester"
    idx = html_lower.find("harvester")
    price: float | None = None
    if idx != -1:
        window = html_lower[max(0, idx - 300): idx + 500]
        prices = [float(m.group(1)) for m in PRICE_RE.finditer(window)]
        if prices:
            price = min(prices)

    # Fallback: scan all prices
    if price is None:
        all_prices = [float(m.group(1)) for m in PRICE_RE.finditer(html_lower)]
        if all_prices:
            price = min(all_prices)

    return True, in_stock, price


# ---------------------------------------------------------------------------
# SiteValidator – two-tier architecture
# ---------------------------------------------------------------------------


class SiteValidator:
    """High-performance concurrent site validator.

    Tier 1 (fast): async HTTP with httpx – 250-500 URLs/sec
    Tier 2 (deep): Playwright headless browser – for URLs that pass fast scan
    """

    def __init__(
        self,
        scraper_cfg: ScraperConfig,
        validation_cfg: ValidationConfig,
    ) -> None:
        self._scfg = scraper_cfg
        self._vcfg = validation_cfg

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def validate_many(
        self,
        urls: list[str],
        on_result: ResultCallback = None,
    ) -> list[ValidationResult]:
        """Validate URLs using the two-tier approach.

        1. Fast HTTP scan (all URLs, high concurrency)
        2. Deep Playwright scan (only URLs that passed fast scan, optional)
        """
        if not urls:
            logger.warning("No URLs to validate.")
            return []

        total = len(urls)
        concurrency = self._scfg.max_concurrency
        timeout_s = self._scfg.timeout_ms / 1000.0

        logger.info(
            "=== Fast Scan: %d URLs | concurrency=%d | timeout=%.1fs ===",
            total, concurrency, timeout_s,
        )

        sem = asyncio.Semaphore(concurrency)
        results: list[ValidationResult] = []
        completed = 0
        start_time = time.monotonic()

        # Build transport with connection pooling for max throughput
        transport = httpx.AsyncHTTPTransport(
            retries=1,
            limits=httpx.Limits(
                max_connections=concurrency,
                max_keepalive_connections=min(concurrency, 100),
            ),
        )

        proxy_transport = None
        if self._scfg.proxy_url:
            proxy_transport = httpx.AsyncHTTPTransport(
                retries=1,
                proxy=self._scfg.proxy_url,
                limits=httpx.Limits(
                    max_connections=concurrency,
                    max_keepalive_connections=min(concurrency, 100),
                ),
            )

        async with httpx.AsyncClient(
            transport=proxy_transport or transport,
            timeout=httpx.Timeout(timeout_s, connect=10.0),
            follow_redirects=True,
            max_redirects=5,
            headers={
                "User-Agent": self._scfg.user_agent,
                "Accept": "text/html,application/xhtml+xml,*/*;q=0.8",
                "Accept-Language": "en-US,en;q=0.9",
                "Accept-Encoding": "gzip, deflate",
            },
        ) as client:

            async def _scan_one(url: str) -> ValidationResult:
                nonlocal completed
                async with sem:
                    result = await self._fast_scan(client, url)
                    completed += 1

                    # Progress log every 50 URLs or at milestones
                    if completed % 50 == 0 or completed == total:
                        elapsed = time.monotonic() - start_time
                        rate = completed / elapsed if elapsed > 0 else 0
                        logger.info(
                            "Progress: %d/%d (%.0f URLs/sec)",
                            completed, total, rate,
                        )

                    # Fire callback
                    if on_result is not None:
                        ret = on_result(result)
                        if asyncio.iscoroutine(ret) or asyncio.isfuture(ret):
                            await ret

                    return result

            # Launch all tasks concurrently (semaphore limits actual concurrency)
            tasks = [asyncio.create_task(_scan_one(u)) for u in urls]
            results = await asyncio.gather(*tasks, return_exceptions=False)

        # Convert any exceptions to failed results
        final_results: list[ValidationResult] = []
        for i, r in enumerate(results):
            if isinstance(r, Exception):
                final_results.append(ValidationResult(
                    url=urls[i],
                    error=f"{type(r).__name__}: {r}",
                ))
            else:
                final_results.append(r)

        elapsed = time.monotonic() - start_time
        rate = len(final_results) / elapsed if elapsed > 0 else 0
        passed_fast = [r for r in final_results if r.passed]

        logger.info(
            "Fast scan complete: %d URLs in %.1fs (%.0f URLs/sec) | %d passed",
            len(final_results), elapsed, rate, len(passed_fast),
        )

        # --- Tier 2: Deep scan (optional, only for passed URLs) ---
        if self._scfg.enable_deep_scan and passed_fast:
            logger.info(
                "=== Deep Scan: %d URLs (Playwright) ===", len(passed_fast),
            )
            deep_results = await self._deep_scan_many(
                [r.url for r in passed_fast], on_result=on_result,
            )
            # Merge deep results back: replace fast results with deep ones
            deep_map = {r.url: r for r in deep_results}
            for i, r in enumerate(final_results):
                if r.url in deep_map:
                    final_results[i] = deep_map[r.url]

        return final_results

    # ------------------------------------------------------------------
    # Tier 1: Fast HTTP scan
    # ------------------------------------------------------------------

    async def _fast_scan(
        self, client: httpx.AsyncClient, url: str,
    ) -> ValidationResult:
        """Download HTML via HTTP and run string/regex checks."""
        result = ValidationResult(url=url, scan_mode="fast")
        try:
            resp = await client.get(url)
            resp.raise_for_status()

            # Only process HTML responses
            content_type = resp.headers.get("content-type", "")
            if "html" not in content_type and "text" not in content_type:
                result.error = f"Non-HTML response: {content_type[:60]}"
                return result

            # Limit body size to avoid memory issues (2 MB)
            html = resp.text[:2_000_000]
            html_lower = html.lower()

            # Stripe detection
            result.has_stripe, result.stripe_evidence = _detect_stripe_fast(html_lower)

            # Wallet detection
            result.has_wallet = _detect_wallet_fast(html_lower)

            # Harvester check
            found, in_stock, price = _check_harvester_fast(html_lower)
            result.harvester_found = found
            result.harvester_in_stock = in_stock
            result.harvester_price = price

            # Pass/fail
            result.passed = (
                (result.has_stripe or not self._vcfg.require_stripe)
                and (result.has_wallet or not self._vcfg.require_wallet)
                and result.harvester_found
                and result.harvester_in_stock
                and result.harvester_price is not None
                and result.harvester_price <= self._vcfg.max_price_usd
            )

        except httpx.TimeoutException:
            result.error = "Timeout"
        except httpx.HTTPStatusError as exc:
            result.error = f"HTTP {exc.response.status_code}"
        except httpx.ConnectError:
            result.error = "Connection refused"
        except httpx.TooManyRedirects:
            result.error = "Too many redirects"
        except Exception as exc:
            result.error = f"{type(exc).__name__}: {str(exc)[:120]}"

        return result

    # ------------------------------------------------------------------
    # Tier 2: Deep Playwright scan
    # ------------------------------------------------------------------

    async def _deep_scan_many(
        self,
        urls: list[str],
        on_result: ResultCallback = None,
    ) -> list[ValidationResult]:
        """Run Playwright deep scan on a (small) set of URLs."""
        try:
            from playwright.async_api import (
                Browser, BrowserContext, Page, Request, async_playwright,
            )
        except ImportError:
            logger.warning(
                "Playwright not installed – skipping deep scan. "
                "Install with: pip install playwright && playwright install chromium"
            )
            return []

        sem = asyncio.Semaphore(self._scfg.deep_scan_concurrency)
        results: list[ValidationResult] = []

        try:
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
                        result = await self._deep_scan_one(browser, url)
                        if on_result is not None:
                            ret = on_result(result)
                            if asyncio.iscoroutine(ret) or asyncio.isfuture(ret):
                                await ret
                        return result

                tasks = [asyncio.create_task(_bounded(u)) for u in urls]
                results = await asyncio.gather(*tasks, return_exceptions=False)
                await browser.close()

        except Exception as exc:
            logger.error("Deep scan failed: %s", exc)

        return [r for r in results if isinstance(r, ValidationResult)]

    async def _deep_scan_one(self, browser, url: str) -> ValidationResult:
        """Run all checks on a single URL using Playwright."""
        from playwright.async_api import Request

        result = ValidationResult(url=url, scan_mode="deep")
        context = None
        try:
            context = await browser.new_context(
                user_agent=self._scfg.user_agent,
                viewport={"width": 1280, "height": 720},
                java_script_enabled=True,
            )
            page = await context.new_page()

            # Network-level Stripe detection
            network_stripe_hits: list[str] = []

            def _on_request(request: Request) -> None:
                req_url = request.url
                for pat in STRIPE_NETWORK_PATTERNS:
                    if pat.search(req_url):
                        network_stripe_hits.append(req_url)
                        break

            page.on("request", _on_request)

            # Block heavy resources
            await page.route(
                "**/*.{png,jpg,jpeg,gif,svg,webp,mp4,webm,woff,woff2}",
                lambda route: route.abort(),
            )

            await page.goto(
                url, wait_until="domcontentloaded", timeout=30_000,
            )
            await page.wait_for_timeout(3000)

            html = await page.content()
            html_lower = html.lower()

            # 1. Stripe detection (deep multi-layer)
            result.has_stripe, result.stripe_evidence = (
                await self._detect_stripe_deep(page, html_lower, network_stripe_hits)
            )

            # 2. Wallet detection
            result.has_wallet = _detect_wallet_fast(html_lower)

            # 3. Harvester check
            await self._check_harvester_deep(page, html_lower, result)

            # Pass/fail
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
            logger.debug("Deep scan error for %s: %s", url, result.error)
        finally:
            if context:
                await context.close()

        status = "PASS" if result.passed else "FAIL"
        logger.info(
            "[DEEP-%s] %s  stripe=%s wallet=%s price=%s stock=%s",
            status, url[:80], result.has_stripe,
            result.has_wallet, result.harvester_price, result.harvester_in_stock,
        )
        return result

    async def _detect_stripe_deep(
        self, page, html_lower: str, network_hits: list[str],
    ) -> tuple[bool, list[str]]:
        """Deep Stripe detection across all layers."""
        evidence: list[str] = []

        # Layer 1: HTML string indicators
        for indicator in STRIPE_HTML_INDICATORS:
            if indicator.lower() in html_lower:
                evidence.append(f"html:{indicator}")

        # Layer 2: Network requests
        for hit in network_hits:
            evidence.append(f"network:{hit[:80]}")

        # Layer 3: Inline scripts
        try:
            scripts = await page.query_selector_all("script:not([src])")
            for el in scripts[:30]:
                try:
                    text = await el.text_content()
                    if text:
                        for pat in STRIPE_SCRIPT_PATTERNS:
                            if pat.search(text):
                                evidence.append(f"inline_script:{pat.pattern[:40]}")
                                break
                except Exception:
                    pass
        except Exception:
            pass

        # Layer 4: External script src
        try:
            ext_scripts = await page.query_selector_all("script[src]")
            for el in ext_scripts:
                src = (await el.get_attribute("src") or "").lower()
                if "stripe" in src:
                    evidence.append(f"script_src:{src[:80]}")
        except Exception:
            pass

        # Layer 5: DOM elements
        try:
            selectors = [
                '[class*="stripe" i]', '[id*="stripe" i]',
                '[data-stripe]', 'iframe[src*="stripe"]',
                '[class*="StripeElement"]',
            ]
            for sel in selectors:
                try:
                    matches = await page.query_selector_all(sel)
                    if matches:
                        evidence.append(f"dom:{sel}({len(matches)})")
                except Exception:
                    pass
        except Exception:
            pass

        # Layer 6: iframes
        try:
            for frame in page.frames:
                try:
                    if "stripe" in frame.url.lower():
                        evidence.append(f"iframe_url:{frame.url[:80]}")
                except Exception:
                    pass
        except Exception:
            pass

        # Layer 7: JS globals
        try:
            js_check = await page.evaluate("""() => {
                const ind = [];
                if (typeof Stripe !== 'undefined') ind.push('Stripe_global');
                if (typeof StripeCheckout !== 'undefined') ind.push('StripeCheckout_global');
                if (window.__stripe_mid) ind.push('__stripe_mid');
                if (window.__stripe_sid) ind.push('__stripe_sid');
                const metas = document.querySelectorAll('meta[content*="stripe"]');
                if (metas.length > 0) ind.push('meta_stripe(' + metas.length + ')');
                try {
                    if (document.cookie.includes('__stripe')) ind.push('stripe_cookie');
                } catch(e) {}
                return ind;
            }""")
            for ind in (js_check or []):
                evidence.append(f"js:{ind}")
        except Exception:
            pass

        # Layer 8: CSP meta tags
        try:
            csp = await page.query_selector_all(
                'meta[http-equiv="Content-Security-Policy"]'
            )
            for meta in csp:
                content = (await meta.get_attribute("content") or "").lower()
                if "stripe" in content:
                    evidence.append("csp_meta:stripe_in_policy")
        except Exception:
            pass

        evidence = list(dict.fromkeys(evidence))
        return len(evidence) > 0, evidence

    async def _check_harvester_deep(
        self, page, html_lower: str, result: ValidationResult,
    ) -> None:
        """Check Harvester with Playwright (can click links)."""
        # Try clicking into a Harvester product page
        try:
            links = await page.query_selector_all(
                'a:has-text("Harvester"), [data-product*="harvester" i]'
            )
            if links:
                await links[0].click(timeout=5000)
                await page.wait_for_timeout(2500)
                html_lower = (await page.content()).lower()
        except Exception:
            pass

        if "harvester" not in html_lower:
            result.harvester_found = False
            return

        result.harvester_found = True

        # Stock check
        oos_signals = ["out of stock", "sold out", "unavailable"]
        has_oos = any(s in html_lower for s in oos_signals)

        try:
            atc_btns = await page.query_selector_all(
                'button:has-text("Add to Cart"), button:has-text("Buy Now"), '
                'button:has-text("Purchase")'
            )
            atc_enabled = any(
                [await btn.is_enabled() for btn in atc_btns]
            ) if atc_btns else False
        except Exception:
            atc_enabled = False

        result.harvester_in_stock = atc_enabled or (
            not has_oos and "in stock" in html_lower
        )

        # Price extraction
        try:
            body_text = await page.inner_text("body")
            body_lower = body_text.lower()
            idx = body_lower.find("harvester")
            prices: list[float] = []
            if idx != -1:
                window = body_text[max(0, idx - 300): idx + 500]
                prices = [float(m.group(1)) for m in PRICE_RE.finditer(window)]
            if not prices:
                prices = [float(m.group(1)) for m in PRICE_RE.finditer(body_text)]
            if prices:
                result.harvester_price = min(prices)
        except Exception:
            pass
