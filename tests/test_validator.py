"""Tests for the site validator detection helpers (unit-level, no browser)."""

from mm2hunter.scraper.validator import SiteValidator, STRIPE_INDICATORS, WALLET_KEYWORDS


def test_stripe_detection_positive():
    html = '<script src="https://js.stripe.com/v3/"></script>'
    assert SiteValidator._detect_stripe(html.lower()) is True


def test_stripe_detection_powered_by():
    html = '<footer>Powered by Stripe</footer>'
    assert SiteValidator._detect_stripe(html.lower()) is True


def test_stripe_detection_negative():
    html = '<footer>Powered by PayPal</footer>'
    assert SiteValidator._detect_stripe(html.lower()) is False


def test_wallet_detection_add_funds():
    html = '<a href="/wallet">Add Funds</a>'
    assert SiteValidator._detect_wallet(html.lower()) is True


def test_wallet_detection_balance():
    html = '<span class="user-balance">Balance: $0.00</span>'
    assert SiteValidator._detect_wallet(html.lower()) is True


def test_wallet_detection_negative():
    html = '<span>Welcome to our shop</span>'
    assert SiteValidator._detect_wallet(html.lower()) is False
