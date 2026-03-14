"""Tests for the web dashboard."""

import json
from pathlib import Path

import pytest
from aiohttp import web
from aiohttp.test_utils import AioHTTPTestCase, unittest_run_loop

from mm2hunter.config import DashboardConfig
from mm2hunter.reporting.dashboard import Dashboard


@pytest.fixture
def data_dir(tmp_path: Path) -> Path:
    """Create a temporary data directory with sample data."""
    d = tmp_path / "data"
    d.mkdir()

    # Write sample results
    results = [
        {
            "url": "https://shop1.example.com",
            "has_stripe": True,
            "has_wallet": True,
            "harvester_found": True,
            "harvester_in_stock": True,
            "harvester_price": 4.50,
            "passed": True,
            "error": None,
            "discovered_at": "2026-03-14T12:00:00+00:00",
        }
    ]
    (d / "results.json").write_text(json.dumps(results))

    # Write sample stats
    stats = {
        "total_scanned": 1,
        "total_passed": 1,
        "total_failed": 0,
        "stripe_detected": 1,
        "wallet_detected": 1,
        "harvester_found": 1,
        "generated_at": "2026-03-14T12:00:00+00:00",
    }
    (d / "stats.json").write_text(json.dumps(stats))

    # Write discovered URLs
    (d / "discovered_urls.txt").write_text(
        "https://shop1.example.com\nhttps://shop2.example.com\n"
    )

    return d


@pytest.fixture
def empty_data_dir(tmp_path: Path) -> Path:
    """Create an empty data directory."""
    d = tmp_path / "data_empty"
    d.mkdir()
    return d


@pytest.fixture
def dashboard_app(data_dir: Path) -> web.Application:
    cfg = DashboardConfig(host="127.0.0.1", port=0)
    dash = Dashboard(cfg, data_dir)
    return dash._app


@pytest.fixture
def empty_dashboard_app(empty_data_dir: Path) -> web.Application:
    cfg = DashboardConfig(host="127.0.0.1", port=0)
    dash = Dashboard(cfg, empty_data_dir)
    return dash._app


# ---------------------------------------------------------------------------
# Tests with data
# ---------------------------------------------------------------------------

async def test_index_returns_html(aiohttp_client, dashboard_app):
    client = await aiohttp_client(dashboard_app)
    resp = await client.get("/")
    assert resp.status == 200
    text = await resp.text()
    assert "MM2 Shop Discovery Tool" in text
    assert "shop1.example.com" in text


async def test_api_results_json(aiohttp_client, dashboard_app):
    client = await aiohttp_client(dashboard_app)
    resp = await client.get("/api/results")
    assert resp.status == 200
    data = await resp.json()
    assert len(data) == 1
    assert data[0]["passed"] is True


async def test_api_stats(aiohttp_client, dashboard_app):
    client = await aiohttp_client(dashboard_app)
    resp = await client.get("/api/stats")
    assert resp.status == 200
    data = await resp.json()
    assert data["total_scanned"] == 1
    assert data["total_passed"] == 1


async def test_api_discovered(aiohttp_client, dashboard_app):
    client = await aiohttp_client(dashboard_app)
    resp = await client.get("/api/discovered")
    assert resp.status == 200


# ---------------------------------------------------------------------------
# Tests with empty data
# ---------------------------------------------------------------------------

async def test_index_empty_data(aiohttp_client, empty_dashboard_app):
    client = await aiohttp_client(empty_dashboard_app)
    resp = await client.get("/")
    assert resp.status == 200
    text = await resp.text()
    assert "No validated results yet" in text


async def test_api_discovered_404_when_missing(aiohttp_client, empty_dashboard_app):
    client = await aiohttp_client(empty_dashboard_app)
    resp = await client.get("/api/discovered")
    assert resp.status == 404
