"""Tests for the site validator detection helpers (unit-level, no browser)."""

from mm2hunter.scraper.validator import (
    SiteValidator,
    STRIPE_HTML_INDICATORS,
    WALLET_KEYWORDS,
)


# ---------------------------------------------------------------------------
# Static HTML-level stripe detection helper (quick unit test)
# ---------------------------------------------------------------------------

def _detect_stripe_html(html_lower: str) -> bool:
    """Check HTML string indicators only (mirrors the old _detect_stripe)."""
    return any(ind.lower() in html_lower for ind in STRIPE_HTML_INDICATORS)


def test_stripe_detection_positive():
    html = '<script src="https://js.stripe.com/v3/"></script>'
    assert _detect_stripe_html(html.lower()) is True


def test_stripe_detection_powered_by():
    html = '<footer>Powered by Stripe</footer>'
    assert _detect_stripe_html(html.lower()) is True


def test_stripe_detection_negative():
    html = '<footer>Powered by PayPal</footer>'
    assert _detect_stripe_html(html.lower()) is False


def test_stripe_detection_pk_live():
    html = '<script>var key = "pk_live_abc123def456";</script>'
    assert _detect_stripe_html(html.lower()) is True


def test_stripe_detection_checkout_url():
    html = '<a href="https://checkout.stripe.com/pay/cs_test_abc">Pay</a>'
    assert _detect_stripe_html(html.lower()) is True


def test_stripe_detection_api_url():
    html = '<meta content="https://api.stripe.com" />'
    assert _detect_stripe_html(html.lower()) is True


def test_stripe_detection_data_attribute():
    html = '<div data-stripe="true">payment</div>'
    assert _detect_stripe_html(html.lower()) is True


def test_stripe_detection_stripe_element_class():
    html = '<div class="StripeElement">card input</div>'
    assert _detect_stripe_html(html.lower()) is True


# ---------------------------------------------------------------------------
# Wallet detection
# ---------------------------------------------------------------------------

def test_wallet_detection_add_funds():
    html = '<a href="/wallet">Add Funds</a>'
    assert SiteValidator._detect_wallet(html.lower()) is True


def test_wallet_detection_balance():
    html = '<span class="user-balance">Balance: $0.00</span>'
    assert SiteValidator._detect_wallet(html.lower()) is True


def test_wallet_detection_negative():
    html = '<span>Welcome to our shop</span>'
    assert SiteValidator._detect_wallet(html.lower()) is False
