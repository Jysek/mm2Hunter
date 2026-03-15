"""
CLI entry-point for MM2 Shop Discovery Tool.

Interactive menu interface -- the user selects an operation and configures
runtime parameters via keyboard input.  Designed for simplicity.
"""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

from mm2hunter.config import get_config
from mm2hunter.utils.logging import setup_logging

# ---------------------------------------------------------------------------
# ANSI helpers
# ---------------------------------------------------------------------------
BOLD = "\033[1m"
DIM = "\033[2m"
CYAN = "\033[96m"
GREEN = "\033[92m"
YELLOW = "\033[93m"
RED = "\033[91m"
MAGENTA = "\033[95m"
WHITE = "\033[97m"
RESET = "\033[0m"

LINE = f"{CYAN}{'=' * 60}{RESET}"


def _clear() -> None:
    """Clear the terminal screen."""
    os.system("cls" if os.name == "nt" else "clear")


# ---------------------------------------------------------------------------
# Input helpers
# ---------------------------------------------------------------------------

def _ask(prompt: str, default: str = "") -> str:
    """Prompt the user; return stripped input or *default*."""
    suffix = f" {DIM}[{default}]{RESET}" if default else ""
    try:
        value = input(f"  {YELLOW}{prompt}{suffix}: {RESET}").strip()
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
            print(f"  {RED}Please enter a positive integer.{RESET}")


def _ask_yes_no(prompt: str, default: bool = True) -> bool:
    """Prompt for a yes/no answer."""
    hint = "Y/n" if default else "y/N"
    raw = _ask(prompt, hint).lower()
    if raw in ("y", "yes", "si", "s"):
        return True
    if raw in ("n", "no"):
        return False
    return default


def _ask_file(prompt: str) -> str:
    """Prompt for a file path, re-ask until a valid file is given."""
    while True:
        raw = _ask(prompt)
        if not raw:
            print(f"  {RED}Please provide a file path.{RESET}")
            continue
        p = Path(raw).expanduser().resolve()
        if p.is_file():
            return str(p)
        print(f"  {RED}File not found: {p}{RESET}")


# ---------------------------------------------------------------------------
# Banner
# ---------------------------------------------------------------------------

def _show_banner() -> None:
    """Print the application banner."""
    print()
    print(LINE)
    print(f"{BOLD}{CYAN}   MM2 Shop Discovery Tool  v2.0{RESET}")
    print(f"{DIM}   High-performance MM2 shop finder & validator{RESET}")
    print(LINE)
    print()


# ---------------------------------------------------------------------------
# Menu
# ---------------------------------------------------------------------------

MENU_OPTIONS = [
    ("1", "Search & Validate", "Run search queries + validate found URLs"),
    ("2", "Validate URLs from File", "Skip search, validate URLs from a .txt file"),
    ("3", "Load Custom Queries", "Load queries from a .txt file, then search"),
    ("4", "Full Pipeline + Dashboard", "Search + validate, then start the web dashboard"),
    ("5", "Dashboard Only", "Start the web dashboard (view existing results)"),
    ("6", "Settings", "View / adjust current configuration"),
    ("0", "Exit", "Quit the tool"),
]


def _show_menu() -> str:
    """Display the main menu and return the user's choice."""
    print(f"  {BOLD}{WHITE}MAIN MENU{RESET}")
    print(f"  {DIM}{'─' * 50}{RESET}")
    print()

    for key, title, desc in MENU_OPTIONS:
        color = RED if key == "0" else GREEN
        print(f"    {color}{BOLD}{key}){RESET}  {WHITE}{title}{RESET}")
        print(f"       {DIM}{desc}{RESET}")
        print()

    while True:
        choice = _ask("Select an option")
        valid = {opt[0] for opt in MENU_OPTIONS}
        if choice in valid:
            return choice
        print(f"  {RED}Invalid choice. Please enter one of: {', '.join(sorted(valid))}{RESET}")


# ---------------------------------------------------------------------------
# Runtime parameters
# ---------------------------------------------------------------------------

def _ask_runtime_params(show_deep: bool = True) -> dict:
    """Ask the user for concurrency and scan settings."""
    print()
    print(f"  {CYAN}{BOLD}Runtime Parameters{RESET}")
    print(f"  {DIM}{'─' * 40}{RESET}")

    concurrency = _ask_int("Max concurrent connections (fast scan)", default=200)
    pages = _ask_int("Pages per query (search results)", default=1)

    deep_scan = False
    if show_deep:
        deep_scan = _ask_yes_no("Enable deep scan (Playwright) for passed URLs?", default=False)

    deep_concurrency = 5
    if deep_scan:
        deep_concurrency = _ask_int("Deep scan concurrency (browser tabs)", default=5)

    return {
        "concurrency": concurrency,
        "pages": pages,
        "deep_scan": deep_scan,
        "deep_concurrency": deep_concurrency,
    }


def _apply_params(cfg, params: dict) -> None:
    """Apply user-supplied runtime parameters to the config object."""
    cfg.scraper.max_concurrency = params["concurrency"]
    cfg.scraper.max_threads = params["concurrency"]
    cfg.serper.pages_per_query = params["pages"]
    cfg.scraper.enable_deep_scan = params["deep_scan"]
    cfg.scraper.deep_scan_concurrency = params["deep_concurrency"]


# ---------------------------------------------------------------------------
# Settings display
# ---------------------------------------------------------------------------

def _show_settings(cfg) -> None:
    """Display current configuration."""
    print()
    print(f"  {CYAN}{BOLD}Current Configuration{RESET}")
    print(f"  {DIM}{'─' * 40}{RESET}")

    keys_count = len(cfg.serper.api_keys)
    keys_str = f"{keys_count} key(s) configured" if keys_count > 0 else f"{RED}NONE{RESET}"

    settings = [
        ("API Keys", keys_str),
        ("Pages per Query", str(cfg.serper.pages_per_query)),
        ("Fast Scan Concurrency", str(cfg.scraper.max_concurrency)),
        ("Deep Scan Enabled", "Yes" if cfg.scraper.enable_deep_scan else "No"),
        ("Deep Scan Concurrency", str(cfg.scraper.deep_scan_concurrency)),
        ("HTTP Timeout (ms)", str(cfg.scraper.timeout_ms)),
        ("Proxy", cfg.scraper.proxy_url or "None"),
        ("Dashboard", f"http://{cfg.dashboard.host}:{cfg.dashboard.port}"),
        ("Data Directory", str(cfg.data_dir)),
        ("Queries File", cfg.serper.queries_file or "Built-in defaults"),
    ]

    for label, value in settings:
        print(f"    {WHITE}{label:<25}{RESET} {value}")

    print()
    input(f"  {DIM}Press Enter to return to the menu...{RESET}")


# ---------------------------------------------------------------------------
# Operation runners
# ---------------------------------------------------------------------------

def _run_search(cfg) -> None:
    """Option 1 -- search & validate."""
    params = _ask_runtime_params()
    _apply_params(cfg, params)

    print()
    print(f"  {GREEN}Starting search & validation pipeline...{RESET}")
    print()

    from mm2hunter.orchestrator import run_pipeline
    asyncio.run(run_pipeline(cfg))


def _run_validate_raw(cfg) -> None:
    """Option 2 -- validate URLs from a file."""
    print()
    url_file = _ask_file("Path to file containing URLs (one per line)")
    params = _ask_runtime_params()
    _apply_params(cfg, params)

    print()
    print(f"  {GREEN}Starting validation of URLs from file...{RESET}")
    print()

    from mm2hunter.orchestrator import run_validate_raw
    asyncio.run(run_validate_raw(cfg, url_file))


def _run_custom_queries(cfg) -> None:
    """Option 3 -- load queries from file, then search."""
    print()
    query_file = _ask_file("Path to file containing search queries (one per line)")
    cfg.serper.queries_file = query_file

    params = _ask_runtime_params()
    _apply_params(cfg, params)

    print()
    print(f"  {GREEN}Starting search with custom queries...{RESET}")
    print()

    from mm2hunter.orchestrator import run_pipeline
    asyncio.run(run_pipeline(cfg))


def _run_full(cfg) -> None:
    """Option 4 -- search + dashboard."""
    params = _ask_runtime_params()
    _apply_params(cfg, params)

    print()
    print(f"  {GREEN}Starting full pipeline + dashboard...{RESET}")
    print()

    from mm2hunter.orchestrator import run_full
    asyncio.run(run_full(cfg))


def _run_dashboard(cfg) -> None:
    """Option 5 -- dashboard only."""
    print()
    print(f"  {GREEN}Starting web dashboard...{RESET}")
    print(f"  {DIM}Open http://{cfg.dashboard.host}:{cfg.dashboard.port} in your browser.{RESET}")
    print()

    from mm2hunter.orchestrator import run_dashboard
    asyncio.run(run_dashboard(cfg))


# ---------------------------------------------------------------------------
# Entry-point
# ---------------------------------------------------------------------------

def main() -> None:
    setup_logging()
    cfg = get_config()

    _clear()
    _show_banner()

    dispatch = {
        "1": _run_search,
        "2": _run_validate_raw,
        "3": _run_custom_queries,
        "4": _run_full,
        "5": _run_dashboard,
        "6": lambda c: _show_settings(c),
    }

    while True:
        try:
            choice = _show_menu()

            if choice == "0":
                print(f"\n  {CYAN}Goodbye!{RESET}\n")
                sys.exit(0)

            if choice == "6":
                _show_settings(cfg)
                continue

            dispatch[choice](cfg)

            # After an operation completes, offer to return to menu
            print()
            again = _ask_yes_no("Return to main menu?", default=True)
            if not again:
                print(f"\n  {CYAN}Goodbye!{RESET}\n")
                sys.exit(0)

            _clear()
            _show_banner()

        except KeyboardInterrupt:
            print(f"\n\n  {YELLOW}Interrupted. Returning to menu...{RESET}\n")
            continue
        except Exception as exc:
            print(f"\n  {RED}Error: {exc}{RESET}\n")
            continue


if __name__ == "__main__":
    main()
