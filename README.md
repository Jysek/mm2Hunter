# mm2Hunter

Automated search and validation tool for discovering Roblox **Murder Mystery 2** (MM2) item shops. Finds e-commerce sites selling MM2 items, verifies they use **Stripe** as a payment gateway, have an **Add Funds / Wallet** system, and checks that the **Harvester** item is in stock at **$6.00 or less**.

## Features

- **Search & Discovery** -- generates advanced Google queries via the Serper.dev API to find MM2 shops
- **API Key Auto-Rotation** -- pool of Serper.dev keys with automatic failover on 403/429/exhaustion
- **Playwright Scraping** -- headless Chromium visits each discovered site and validates:
  - Stripe payment gateway (DOM scanning for `js.stripe.com`, Stripe elements, etc.)
  - Wallet / "Add Funds" system
  - Harvester item presence, stock status, and price extraction
- **Concurrent Validation** -- configurable concurrency with asyncio semaphore
- **Proxy Support** -- route requests through rotating proxies to avoid IP bans
- **Reporting** -- exports results to **JSON** and **CSV**
- **Web Dashboard** -- lightweight aiohttp dashboard with stats, table, and download buttons

## Project Structure

```
mm2Hunter/
├── mm2hunter/
│   ├── __init__.py
│   ├── cli.py                 # CLI entry-point
│   ├── config.py              # Central configuration (env-driven)
│   ├── orchestrator.py        # Wires search → validate → report
│   ├── search/
│   │   ├── engine.py          # Serper.dev search client
│   │   └── key_manager.py     # API key pool & rotation
│   ├── scraper/
│   │   └── validator.py       # Playwright site validator
│   ├── reporting/
│   │   ├── exporter.py        # JSON / CSV export
│   │   └── dashboard.py       # Web dashboard (aiohttp)
│   └── utils/
│       └── logging.py         # Structured logging helper
├── tests/
│   ├── test_config.py
│   ├── test_key_manager.py
│   ├── test_exporter.py
│   └── test_validator.py
├── pyproject.toml
├── requirements.txt
├── .env.example
└── .gitignore
```

## Quick Start

### 1. Clone & Install

```bash
git clone https://github.com/Jysek/mm2Hunter.git
cd mm2Hunter

python -m venv venv && source venv/bin/activate
pip install -e ".[dev]"

# Install Playwright browsers
playwright install chromium
```

### 2. Configure

```bash
cp .env.example .env
# Edit .env and add your Serper.dev API key(s):
#   SERPER_API_KEYS=your_key_1,your_key_2
```

### 3. Run

```bash
# Search + validate + export reports
mm2hunter search

# Start the web dashboard (reads data/ folder)
mm2hunter dashboard

# Do both: run pipeline then serve dashboard
mm2hunter run
```

### 4. View Results

- **Dashboard**: open `http://localhost:8080` in your browser
- **JSON**: `data/results.json`
- **CSV**: `data/results.csv`

## Configuration

All settings are driven by environment variables (or a `.env` file):

| Variable | Default | Description |
|---|---|---|
| `SERPER_API_KEYS` | *(required)* | Comma-separated Serper.dev API keys |
| `SCRAPER_HEADLESS` | `true` | Run Playwright in headless mode |
| `SCRAPER_TIMEOUT_MS` | `30000` | Page-load timeout in milliseconds |
| `SCRAPER_MAX_CONCURRENCY` | `5` | Max concurrent browser tabs |
| `PROXY_URL` | *(none)* | Optional rotating proxy URL |
| `DASHBOARD_HOST` | `0.0.0.0` | Dashboard bind address |
| `DASHBOARD_PORT` | `8080` | Dashboard port |

## Validation Criteria

A site **passes** when all of the following are true:

1. Stripe payment gateway detected on the page
2. "Add Funds" / Wallet system detected
3. Harvester item found on the site
4. Harvester is currently in stock
5. Harvester price is **<= $6.00**

## Running Tests

```bash
python -m pytest tests/ -v
```

## Tech Stack

| Component | Technology |
|---|---|
| Language | Python 3.10+ |
| Search API | Serper.dev |
| Scraping | Playwright (async) |
| HTTP client | httpx |
| Dashboard | aiohttp |
| Config | python-dotenv |
| Testing | pytest + pytest-asyncio |

## License

MIT
