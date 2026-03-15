# mm2Hunter

Automated search and validation tool for discovering Roblox **Murder Mystery 2** (MM2) item shops. Finds e-commerce sites selling MM2 items, verifies they use **Stripe** as a payment gateway, have an **Add Funds / Wallet** system, and checks that the **Harvester** item is in stock at **$6.00 or less**.

## Features

- **Interactive Menu** -- no more command-line flags; choose what to do from a numbered menu
- **Search & Discovery** -- generates advanced Google queries via the Serper.dev API to find MM2 shops
- **Validate Raw URLs** -- skip search entirely and validate URLs from a text file
- **Load Custom Queries** -- load search queries from a TXT file (one query per line)
- **Runtime Parameters** -- configure threads, concurrency, and pages-per-query at startup
- **Multi-Page Search** -- fetch multiple result pages per query for more results
- **API Key Auto-Rotation** -- pool of Serper.dev keys with automatic failover on 403/429/exhaustion
- **Pre-Validation URL Export** -- saves all discovered URLs to `discovered_urls.txt` before validation starts
- **Real-time File Updates** -- `discovered_urls.txt`, `results.json`, `results.csv`, and `stats.json` are updated incrementally as each URL is discovered or validated (no waiting for the whole pipeline to finish)
- **Playwright Scraping** -- headless Chromium visits each discovered site and validates:
  - **Deep Stripe detection** (8-layer analysis: HTML keywords, network request interception, inline script analysis, external script `src` inspection, DOM element/attribute scanning, iframe inspection, JavaScript global variable evaluation, CSP meta tag analysis)
  - Wallet / "Add Funds" system
  - Harvester item presence, stock status, and price extraction
- **Concurrent Validation** -- configurable concurrency with asyncio semaphore
- **Proxy Support** -- route requests through rotating proxies to avoid IP bans
- **Reporting** -- exports results to **JSON** and **CSV**
- **Web Dashboard** -- lightweight aiohttp dashboard with stats, table, discovered URLs tab, and download buttons

## Project Structure

```
mm2Hunter/
├── mm2hunter/
│   ├── __init__.py
│   ├── cli.py                 # Interactive menu entry-point
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
│   ├── test_orchestrator.py
│   └── test_dashboard.py
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
mm2hunter
```

The tool will display an interactive menu:

```
================================================================
   MM2 Shop Discovery Tool  --  Interactive Menu
================================================================

  1) Search              - Run search & validation pipeline
  2) Dashboard           - Start the web dashboard only
  3) Validate Raw URLs   - Validate URLs from a file (skip search)
  4) Run (Search + Dash) - Full pipeline then start dashboard
  5) Carica Query        - Load queries from file, then search

Select an operation (1-5):
```

After choosing an operation (except Dashboard), you will be asked:

```
--- Runtime Parameters ---
Number of threads (worker tasks) [5]:
Max concurrency (simultaneous browser tabs) [5]:
Pages per query (search result pages to fetch) [1]:
```

### 4. Operations Explained

| # | Operation | Description |
|---|-----------|-------------|
| 1 | **Search** | Run built-in queries, validate found URLs, export reports |
| 2 | **Dashboard** | Start the web dashboard to view existing results |
| 3 | **Validate Raw URLs** | Provide a file with URLs (one per line) to validate directly |
| 4 | **Run (Search + Dash)** | Full pipeline (search + validate) then serve the dashboard |
| 5 | **Carica Query** | Load queries from a TXT file, then run search + validate |

### 5. Query / URL File Format

**Queries file** (one query per line, `#` for comments):

```text
# My custom MM2 search queries
"Murder Mystery 2" "Harvester" buy cheap stripe
"MM2" godly shop "add funds" wallet
"Roblox MM2" items store harvester
```

**Raw URLs file** (one URL per line, `#` for comments):

```text
# URLs to validate
https://mm2shop.example.com
https://another-store.example.com/harvester
```

### 6. View Results

- **Dashboard**: open `http://localhost:8080` in your browser
- **Discovered URLs** (pre-validation): `data/discovered_urls.txt`
- **JSON**: `data/results.json`
- **CSV**: `data/results.csv`

## Configuration

All settings are driven by environment variables (or a `.env` file).
Runtime parameters entered via the interactive menu **override** env defaults.

| Variable | Default | Description |
|---|---|---|
| `SERPER_API_KEYS` | *(required)* | Comma-separated Serper.dev API keys |
| `SERPER_PAGES_PER_QUERY` | `1` | Number of result pages per query |
| `QUERIES_FILE` | *(none)* | Path to a TXT file with custom queries |
| `SCRAPER_HEADLESS` | `true` | Run Playwright in headless mode |
| `SCRAPER_TIMEOUT_MS` | `30000` | Page-load timeout in milliseconds |
| `SCRAPER_MAX_CONCURRENCY` | `5` | Max concurrent browser tabs |
| `SCRAPER_MAX_THREADS` | `5` | Max worker tasks for batch validation |
| `PROXY_URL` | *(none)* | Optional rotating proxy URL |
| `DASHBOARD_HOST` | `0.0.0.0` | Dashboard bind address |
| `DASHBOARD_PORT` | `8080` | Dashboard port |

## Validation Criteria

A site **passes** when all of the following are true:

1. Stripe payment gateway detected on the page (deep 8-layer detection)
2. "Add Funds" / Wallet system detected
3. Harvester item found on the site
4. Harvester is currently in stock
5. Harvester price is **<= $6.00**

### Stripe Detection Layers

| Layer | Method | What It Checks |
|-------|--------|----------------|
| 1 | HTML string scan | `js.stripe.com`, `pk_live_`, `powered by stripe`, `checkout.stripe.com`, `api.stripe.com`, DOM class/id markers, etc. |
| 2 | Network interception | Intercepts all outgoing requests and checks for Stripe domains (`js.stripe.com`, `api.stripe.com`, `m.stripe.network`, `q.stripe.com`, etc.) |
| 3 | Inline `<script>` analysis | Regex patterns for `Stripe(`, `loadStripe(`, `confirmCardPayment`, `createPaymentIntent`, `payment_intent`, `pk_live_*` keys, etc. |
| 4 | External script `src` | Checks all `<script src="...">` attributes for Stripe URLs |
| 5 | DOM element inspection | Queries for `[class*="stripe"]`, `[data-stripe]`, `iframe[src*="stripe"]`, `StripeElement` classes, etc. |
| 6 | iframe deep inspection | Inspects all page frames for Stripe URLs and frame names |
| 7 | JavaScript globals | Evaluates `window.Stripe`, `window.StripeCheckout`, `__stripe_mid`, `__stripe_sid`, Stripe cookies, meta tags, payment form elements |
| 8 | CSP meta tags | Checks `Content-Security-Policy` meta tags for whitelisted Stripe domains |

### Real-time File Updates

During both **search** and **validation**, output files are updated incrementally:

- **Search phase**: each batch of discovered URLs is appended to `data/discovered_urls.txt` immediately
- **Validation phase**: after each URL is validated, `data/results.json`, `data/results.csv`, and `data/stats.json` are refreshed
- The **dashboard** can be opened in parallel and will always show the latest data by refreshing the page

## Output Files

| File | Description |
|---|---|
| `data/discovered_urls.txt` | All URLs found by search, saved **before** validation |
| `data/results.json` | Full validation results in JSON format |
| `data/results.csv` | Full validation results in CSV format |
| `data/stats.json` | Summary statistics for the dashboard |

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
