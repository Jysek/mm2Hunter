# mm2Hunter v2.0

High-performance automated search and validation tool for discovering Roblox **Murder Mystery 2** (MM2) item shops. Finds e-commerce sites selling MM2 items, verifies they use **Stripe** as a payment gateway, have an **Add Funds / Wallet** system, and checks that the **Harvester** item is in stock at **$6.00 or less**.

## What's New in v2.0

- **250-500 URLs/sec** -- Two-tier validation architecture: fast async HTTP scan + optional Playwright deep scan
- **Redesigned interactive menu** -- cleaner UX, settings view, loop-back navigation
- **Connection pooling** -- high-throughput httpx transport with configurable concurrency
- **Scan mode tracking** -- results show whether they came from fast or deep scan
- **Throttled I/O** -- realtime exporter batches disk writes to avoid bottlenecks
- **Better error handling** -- graceful timeouts, URL validation, API key checks

## Features

- **Interactive Menu** -- choose operations from a numbered menu with runtime parameter configuration
- **Two-Tier Validation**:
  - **Fast Scan** (Tier 1): Pure async HTTP with httpx -- 250-500 URLs/sec with connection pooling
  - **Deep Scan** (Tier 2): Playwright headless Chromium for JS-heavy sites (optional, only for passed URLs)
- **Search & Discovery** -- generates advanced Google queries via the Serper.dev API
- **Validate Raw URLs** -- skip search and validate URLs from a text file
- **Load Custom Queries** -- load search queries from a TXT file
- **API Key Auto-Rotation** -- pool of Serper.dev keys with automatic failover
- **Deep Stripe Detection** (8-layer analysis in deep scan mode)
- **Real-time File Updates** -- results are flushed to disk incrementally
- **Concurrent Validation** -- configurable concurrency (up to 500+ connections)
- **Proxy Support** -- route requests through rotating proxies
- **Reporting** -- exports to JSON and CSV
- **Web Dashboard** -- lightweight aiohttp dashboard with stats, table, and downloads

## Project Structure

```
mm2Hunter/
├── mm2hunter/
│   ├── __init__.py
│   ├── cli.py                 # Interactive menu entry-point
│   ├── config.py              # Central configuration (env-driven)
│   ├── orchestrator.py        # Wires search -> validate -> report
│   ├── search/
│   │   ├── engine.py          # Serper.dev search client
│   │   └── key_manager.py     # API key pool & rotation
│   ├── scraper/
│   │   └── validator.py       # Two-tier validator (fast + deep)
│   ├── reporting/
│   │   ├── exporter.py        # JSON / CSV export + realtime writer
│   │   └── dashboard.py       # Web dashboard (aiohttp)
│   └── utils/
│       └── logging.py         # Structured logging helper
├── tests/
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

# Optional: install Playwright for deep scan mode
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
mm2hunter
```

The tool displays an interactive menu:

```
============================================================
   MM2 Shop Discovery Tool  v2.0
   High-performance MM2 shop finder & validator
============================================================

  MAIN MENU
  --------------------------------------------------

    1)  Search & Validate
        Run search queries + validate found URLs

    2)  Validate URLs from File
        Skip search, validate URLs from a .txt file

    3)  Load Custom Queries
        Load queries from a .txt file, then search

    4)  Full Pipeline + Dashboard
        Search + validate, then start the web dashboard

    5)  Dashboard Only
        Start the web dashboard (view existing results)

    6)  Settings
        View / adjust current configuration

    0)  Exit
        Quit the tool

  Select an option:
```

### 4. Runtime Parameters

After selecting an operation, you configure:

```
  Runtime Parameters
  ----------------------------------------
  Max concurrent connections (fast scan) [200]:
  Pages per query (search results) [1]:
  Enable deep scan (Playwright) for passed URLs? [Y/n]:
```

### 5. Operations

| # | Operation | Description |
|---|-----------|-------------|
| 1 | **Search & Validate** | Run built-in queries, fast-scan all found URLs |
| 2 | **Validate URLs from File** | Validate URLs from a .txt file (skip search) |
| 3 | **Load Custom Queries** | Load queries from file, then search + validate |
| 4 | **Full Pipeline + Dashboard** | Search + validate + start web dashboard |
| 5 | **Dashboard Only** | View existing results in the browser |
| 6 | **Settings** | View current configuration |

### 6. View Results

- **Dashboard**: open `http://localhost:8080` in your browser
- **Discovered URLs**: `data/discovered_urls.txt`
- **JSON**: `data/results.json`
- **CSV**: `data/results.csv`

## Configuration

All settings are driven by environment variables (or a `.env` file).

| Variable | Default | Description |
|---|---|---|
| `SERPER_API_KEYS` | *(required)* | Comma-separated Serper.dev API keys |
| `SERPER_PAGES_PER_QUERY` | `1` | Result pages per query |
| `QUERIES_FILE` | *(none)* | Custom queries TXT file |
| `SCRAPER_HEADLESS` | `true` | Headless browser mode |
| `SCRAPER_TIMEOUT_MS` | `15000` | HTTP timeout (fast scan) in ms |
| `SCRAPER_MAX_CONCURRENCY` | `200` | Max concurrent HTTP connections |
| `SCRAPER_DEEP_SCAN_CONCURRENCY` | `5` | Playwright browser tabs |
| `ENABLE_DEEP_SCAN` | `true` | Enable Playwright deep scan |
| `PROXY_URL` | *(none)* | Optional proxy URL |
| `DASHBOARD_HOST` | `0.0.0.0` | Dashboard bind address |
| `DASHBOARD_PORT` | `8080` | Dashboard port |

## Performance

| Mode | Speed | Use Case |
|------|-------|----------|
| **Fast Scan** | 250-500 URLs/sec | Default -- pure async HTTP, regex/string analysis |
| **Deep Scan** | 1-5 URLs/sec | Optional -- Playwright browser for JS-rendered sites |
| **Combined** | Fast scan all, deep scan only passed | Best balance of speed + accuracy |

## Validation Criteria

A site **passes** when all of the following are true:

1. Stripe payment gateway detected
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
| Fast Scan | httpx (async HTTP) |
| Deep Scan | Playwright (async, optional) |
| Dashboard | aiohttp |
| Config | python-dotenv |
| Testing | pytest + pytest-asyncio |

## License

MIT
