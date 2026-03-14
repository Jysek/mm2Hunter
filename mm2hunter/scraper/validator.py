"""
Playwright-based scraper that validates discovered MM2 shop sites.

Checks performed per site:
  1. Stripe payment gateway detection  (deep: HTML, DOM, scripts, network, iframes)
  2. "Add Funds" / wallet system detection
  3. Harvester item – stock status & price <= $6.00
"""

from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Callable, Awaitable

from playwright.async_api import Browser, BrowserContext, Page, Request, async_playwright

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
            "discovered_at": self.discovered_at,
        }


# ---------------------------------------------------------------------------
# Regex / keyword helpers
# ---------------------------------------------------------------------------

# ---- HTML / DOM string indicators ----
STRIPE_HTML_INDICATORS = [
    # Script sources
    "js.stripe.com",
    "stripe.com/v3",
    "stripe.com/v2",
    # Branding
    "powered by stripe",
    "powered by <a",  # partial anchor with Stripe branding
    # JS SDK object names
    "stripe.js",
    "stripe-js",
    "stripe elements",
    "@stripe/stripe-js",
    "@stripe/react-stripe-js",
    # Public keys
    "pk_live_",
    "pk_test_",
    # DOM class / id markers
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
    # Checkout / Payment Intents / Setup Intents
    "checkout.stripe.com",
    "api.stripe.com",
    "m.stripe.com",
    "m.stripe.network",
    "q.stripe.com",
    "r.stripe.com",
    "hooks.stripe.com",
    "invoice.stripe.com",
    "billing.stripe.com",
    # Meta / CSP headers sometimes mention stripe
    "connect.stripe.com",
]

# ---- Network URL patterns that indicate Stripe activity ----
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

# ---- Patterns to search inside <script> tag contents ----
STRIPE_SCRIPT_PATTERNS = [
    re.compile(r"Stripe\s*\(", re.I),               # new Stripe( or Stripe(
    re.compile(r"loadStripe\s*\(", re.I),            # loadStripe(
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
ResultCallback = Callable[[ValidationResult], Awaitable[None]] | Callable[[ValidationResult], None] | None


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
    async def validate_many(
        self,
        urls: list[str],
        on_result: ResultCallback = None,
    ) -> list[ValidationResult]:
        """Validate a list of URLs concurrently.

        If *on_result* is provided, it is called with each
        ``ValidationResult`` as soon as the validation of that URL
        completes – enabling real-time file writes.

        * **max_concurrency** limits simultaneous browser tabs (semaphore).
        * **max_threads** controls how many URL-worker tasks are spawned
          per batch.  URLs are processed in chunks of *max_threads* size.
        """
        sem = asyncio.Semaphore(self._scfg.max_concurrency)
        threads = getattr(self._scfg, "max_threads", len(urls)) or len(urls)

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
                    result = await self._validate_one(browser, url)
                    # Fire the callback immediately
                    if on_result is not None:
                        ret = on_result(result)
                        if asyncio.iscoroutine(ret) or asyncio.isfuture(ret):
                            await ret
                    return result

            all_results: list[ValidationResult] = []
            # Process URLs in chunks of `threads` size
            for i in range(0, len(urls), threads):
                chunk = urls[i : i + threads]
                logger.info(
                    "Processing batch %d-%d of %d URLs ...",
                    i + 1,
                    min(i + threads, len(urls)),
                    len(urls),
                )
                batch = await asyncio.gather(
                    *[_bounded(u) for u in chunk], return_exceptions=False
                )
                all_results.extend(batch)

            await browser.close()

        return all_results

    # ------------------------------------------------------------------
    async def _validate_one(self, browser: Browser, url: str) -> ValidationResult:
        """Run all checks on a single URL."""
        result = ValidationResult(url=url)
        context: BrowserContext | None = None
        try:
            context = await browser.new_context(
                user_agent=self._scfg.user_agent,
                viewport={"width": 1280, "height": 720},
                java_script_enabled=True,
            )
            page = await context.new_page()

            # ----------------------------------------------------------
            # Network-level Stripe detection: intercept all requests
            # ----------------------------------------------------------
            network_stripe_hits: list[str] = []

            def _on_request(request: Request) -> None:
                req_url = request.url
                for pat in STRIPE_NETWORK_PATTERNS:
                    if pat.search(req_url):
                        network_stripe_hits.append(req_url)
                        break

            page.on("request", _on_request)

            # Block heavy resources to speed up loading (but allow JS!)
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

            # 1. Stripe detection (deep multi-layer)
            result.has_stripe, result.stripe_evidence = await self._detect_stripe_deep(
                page, html, html_lower, network_stripe_hits
            )

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
        evidence_str = ", ".join(result.stripe_evidence[:3]) if result.stripe_evidence else "none"
        logger.info(
            "[%s] %s  stripe=%s(%s) wallet=%s price=%s stock=%s",
            status, url[:80], result.has_stripe, evidence_str,
            result.has_wallet, result.harvester_price, result.harvester_in_stock,
        )
        return result

    # ------------------------------------------------------------------
    # Stripe detection – deep multi-layer analysis
    # ------------------------------------------------------------------

    async def _detect_stripe_deep(
        self,
        page: Page,
        html: str,
        html_lower: str,
        network_hits: list[str],
    ) -> tuple[bool, list[str]]:
        """Perform deep Stripe detection across multiple layers.

        Returns (detected: bool, evidence: list[str]).
        """
        evidence: list[str] = []

        # ---- Layer 1: HTML string indicators ----
        for indicator in STRIPE_HTML_INDICATORS:
            if indicator.lower() in html_lower:
                evidence.append(f"html:{indicator}")

        # ---- Layer 2: Network requests ----
        for hit in network_hits:
            evidence.append(f"network:{hit[:80]}")

        # ---- Layer 3: Inline <script> content analysis ----
        try:
            script_elements = await page.query_selector_all("script:not([src])")
            for el in script_elements[:30]:  # cap to avoid slowness
                try:
                    text_content = await el.text_content()
                    if text_content:
                        for pat in STRIPE_SCRIPT_PATTERNS:
                            if pat.search(text_content):
                                evidence.append(f"inline_script:{pat.pattern[:40]}")
                                break  # one match per script tag is enough
                except Exception:
                    pass
        except Exception:
            pass

        # ---- Layer 4: External script src attributes ----
        try:
            ext_scripts = await page.query_selector_all("script[src]")
            for el in ext_scripts:
                src = await el.get_attribute("src") or ""
                src_lower = src.lower()
                if "stripe" in src_lower:
                    evidence.append(f"script_src:{src[:80]}")
        except Exception:
            pass

        # ---- Layer 5: DOM element inspection ----
        try:
            stripe_dom_selectors = [
                '[class*="stripe" i]',
                '[id*="stripe" i]',
                '[data-stripe]',
                '[data-stripe-key]',
                '[data-stripe-publishable-key]',
                'iframe[src*="stripe"]',
                'iframe[name*="stripe"]',
                'iframe[title*="stripe" i]',
                '[class*="StripeElement"]',
                '[class*="__PrivateStripeElement"]',
            ]
            for selector in stripe_dom_selectors:
                try:
                    matches = await page.query_selector_all(selector)
                    if matches:
                        evidence.append(f"dom:{selector}({len(matches)})")
                except Exception:
                    pass
        except Exception:
            pass

        # ---- Layer 6: iframe deep inspection ----
        try:
            frames = page.frames
            for frame in frames:
                try:
                    frame_url = frame.url.lower()
                    if "stripe" in frame_url:
                        evidence.append(f"iframe_url:{frame.url[:80]}")
                    # Check frame name
                    frame_name = frame.name.lower() if frame.name else ""
                    if "stripe" in frame_name:
                        evidence.append(f"iframe_name:{frame.name}")
                except Exception:
                    pass
        except Exception:
            pass

        # ---- Layer 7: JavaScript global variable check ----
        try:
            js_check = await page.evaluate("""() => {
                const indicators = [];
                if (typeof Stripe !== 'undefined') indicators.push('Stripe_global');
                if (typeof StripeCheckout !== 'undefined') indicators.push('StripeCheckout_global');
                if (window.__stripe_mid) indicators.push('__stripe_mid');
                if (window.__stripe_sid) indicators.push('__stripe_sid');
                if (document.querySelector('[data-stripe]')) indicators.push('data-stripe_attr');
                // Check for Stripe in meta tags (CSP, etc.)
                const metas = document.querySelectorAll('meta[content*="stripe"]');
                if (metas.length > 0) indicators.push('meta_stripe(' + metas.length + ')');
                // Check for Stripe payment form elements
                const stripeInputs = document.querySelectorAll(
                    'input[name*="stripe"], input[data-stripe], [data-elements-stable-field-name]'
                );
                if (stripeInputs.length > 0) indicators.push('stripe_inputs(' + stripeInputs.length + ')');
                // Check cookies
                try {
                    if (document.cookie.includes('__stripe')) indicators.push('stripe_cookie');
                } catch(e) {}
                return indicators;
            }""")
            for ind in (js_check or []):
                evidence.append(f"js:{ind}")
        except Exception:
            pass

        # ---- Layer 8: Check response headers / CSP for stripe domains ----
        # (We already captured network requests; also check the main page's
        #  Content-Security-Policy or other headers via meta tags.)
        try:
            csp_meta = await page.query_selector_all(
                'meta[http-equiv="Content-Security-Policy"]'
            )
            for meta in csp_meta:
                content = (await meta.get_attribute("content") or "").lower()
                if "stripe" in content:
                    evidence.append("csp_meta:stripe_in_policy")
        except Exception:
            pass

        # De-duplicate evidence
        evidence = list(dict.fromkeys(evidence))

        detected = len(evidence) > 0
        return detected, evidence

    # ------------------------------------------------------------------
    # Wallet / Add-Funds detection
    # ------------------------------------------------------------------

    @staticmethod
    def _detect_wallet(html_lower: str) -> bool:
        return any(kw in html_lower for kw in WALLET_KEYWORDS)

    # ------------------------------------------------------------------
    # Harvester item detection
    # ------------------------------------------------------------------

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
        price_candidates: list[float] = []

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
