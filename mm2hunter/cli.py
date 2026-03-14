"""
CLI entry-point for MM2 Shop Discovery Tool.

Interactive menu interface – the user selects an operation and configures
runtime parameters (threads, concurrency, pages) via keyboard input.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

from mm2hunter.config import get_config
from mm2hunter.utils.logging import setup_logging

# ---------------------------------------------------------------------------
# ANSI helpers (works on most terminals; gracefully ignored otherwise)
# ---------------------------------------------------------------------------
BOLD = "\033[1m"
CYAN = "\033[96m"
GREEN = "\033[92m"
YELLOW = "\033[93m"
RED = "\033[91m"
RESET = "\033[0m"

BANNER = f"""
{CYAN}{BOLD}================================================================
   MM2 Shop Discovery Tool  --  Interactive Menu
================================================================{RESET}
"""


# ---------------------------------------------------------------------------
# Input helpers
# ---------------------------------------------------------------------------

def _ask(prompt: str, default: str = "") -> str:
    """Prompt the user; return stripped input or *default*."""
    suffix = f" [{default}]" if default else ""
    try:
        value = input(f"{YELLOW}{prompt}{suffix}: {RESET}").strip()
    except (EOFError, KeyboardInterrupt):
        print()
        sys.exit(0)
    return value or default


def _ask_int(prompt: str, default: int) -> int:
    """Prompt for an integer, re-ask on bad input."""
    while True:
        raw = _ask(prompt, str(default))
        try:
            val = int(raw)
            if val < 1:
                raise ValueError
            return val
        except ValueError:
            print(f"{RED}  Please enter a positive integer.{RESET}")


def _ask_file(prompt: str) -> str:
    """Prompt for a file path, re-ask until a valid file is given."""
    while True:
        raw = _ask(prompt)
        if not raw:
            print(f"{RED}  Please provide a file path.{RESET}")
            continue
        p = Path(raw).expanduser().resolve()
        if p.is_file():
            return str(p)
        print(f"{RED}  File not found: {p}{RESET}")


# ---------------------------------------------------------------------------
# Menu
# ---------------------------------------------------------------------------

def _show_menu() -> str:
    """Display the operation menu and return the user's choice."""
    print(BANNER)
    print(f"  {GREEN}1){RESET} Search              - Run search & validation pipeline")
    print(f"  {GREEN}2){RESET} Dashboard           - Start the web dashboard only")
    print(f"  {GREEN}3){RESET} Validate Raw URLs   - Validate URLs from a file (skip search)")
    print(f"  {GREEN}4){RESET} Run (Search + Dash) - Full pipeline then start dashboard")
    print(f"  {GREEN}5){RESET} Carica Query        - Load queries from file, then search")
    print()

    while True:
        choice = _ask("Select an operation (1-5)")
        if choice in ("1", "2", "3", "4", "5"):
            return choice
        print(f"{RED}  Invalid choice. Enter a number between 1 and 5.{RESET}")


def _ask_runtime_params() -> dict:
    """Ask the user for threads, concurrency, and pages-per-query."""
    print()
    print(f"{CYAN}--- Runtime Parameters ---{RESET}")
    threads = _ask_int("Number of threads (worker tasks)", default=5)
    concurrency = _ask_int("Max concurrency (simultaneous browser tabs)", default=5)
    pages = _ask_int("Pages per query (search result pages to fetch)", default=1)
    return {
        "threads": threads,
        "concurrency": concurrency,
        "pages": pages,
    }


# ---------------------------------------------------------------------------
# Runners
# ---------------------------------------------------------------------------

def _apply_params(cfg, params: dict) -> None:
    """Apply user-supplied runtime parameters to the config object."""
    cfg.scraper.max_concurrency = params["concurrency"]
    cfg.serper.pages_per_query = params["pages"]
    # 'threads' controls how many URL-validation workers run in parallel.
    # We store it on scraper config as well (concurrency == threads for I/O).
    cfg.scraper.max_threads = params["threads"]


def _run_search(cfg) -> None:
    """Option 1 – search & validate."""
    params = _ask_runtime_params()
    _apply_params(cfg, params)

    from mm2hunter.orchestrator import run_pipeline
    asyncio.run(run_pipeline(cfg))


def _run_dashboard(cfg) -> None:
    """Option 2 – dashboard only."""
    from mm2hunter.orchestrator import run_dashboard
    asyncio.run(run_dashboard(cfg))


def _run_validate_raw(cfg) -> None:
    """Option 3 – validate raw URLs from a file."""
    print()
    url_file = _ask_file("Enter the path to the file containing raw URLs")
    params = _ask_runtime_params()
    _apply_params(cfg, params)

    from mm2hunter.orchestrator import run_validate_raw
    asyncio.run(run_validate_raw(cfg, url_file))


def _run_full(cfg) -> None:
    """Option 4 – search + dashboard."""
    params = _ask_runtime_params()
    _apply_params(cfg, params)

    from mm2hunter.orchestrator import run_full
    asyncio.run(run_full(cfg))


def _run_carica_query(cfg) -> None:
    """Option 5 – load queries from file, then search."""
    print()
    query_file = _ask_file("Enter the path to the file containing queries")
    cfg.serper.queries_file = query_file

    params = _ask_runtime_params()
    _apply_params(cfg, params)

    from mm2hunter.orchestrator import run_pipeline
    asyncio.run(run_pipeline(cfg))


# ---------------------------------------------------------------------------
# Entry-point
# ---------------------------------------------------------------------------

def main() -> None:
    setup_logging()
    cfg = get_config()

    choice = _show_menu()

    dispatch = {
        "1": _run_search,
        "2": _run_dashboard,
        "3": _run_validate_raw,
        "4": _run_full,
        "5": _run_carica_query,
    }

    try:
        dispatch[choice](cfg)
    except KeyboardInterrupt:
        print(f"\n{YELLOW}Interrupted by user.{RESET}")
        sys.exit(0)


if __name__ == "__main__":
    main()
