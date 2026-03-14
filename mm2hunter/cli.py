"""
CLI entry-point for MM2 Shop Discovery Tool.

Usage:
    mm2hunter search        – Run the search & validation pipeline
    mm2hunter dashboard     – Start the web dashboard only
    mm2hunter run           – Run pipeline then start dashboard
"""

from __future__ import annotations

import argparse
import asyncio
import sys

from mm2hunter.config import get_config
from mm2hunter.utils.logging import setup_logging


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="mm2hunter",
        description="MM2 Shop Discovery Tool – find & validate Murder Mystery 2 item shops.",
    )
    sub = parser.add_subparsers(dest="command")

    # search ------------------------------------------------------------------
    search_p = sub.add_parser("search", help="Run the search & validation pipeline")
    search_p.add_argument(
        "--queries-file", "-q",
        type=str, default=None,
        help="Path to a TXT file with custom queries (one per line)",
    )
    search_p.add_argument(
        "--pages", "-p",
        type=int, default=None,
        help="Number of result pages to fetch per query (default: 1)",
    )

    # dashboard ---------------------------------------------------------------
    dash_p = sub.add_parser("dashboard", help="Start the web dashboard only")
    dash_p.add_argument("--port", type=int, default=None, help="Dashboard port")

    # run (full) --------------------------------------------------------------
    run_p = sub.add_parser("run", help="Run pipeline then start the dashboard")
    run_p.add_argument("--port", type=int, default=None, help="Dashboard port")
    run_p.add_argument(
        "--queries-file", "-q",
        type=str, default=None,
        help="Path to a TXT file with custom queries (one per line)",
    )
    run_p.add_argument(
        "--pages", "-p",
        type=int, default=None,
        help="Number of result pages to fetch per query (default: 1)",
    )

    return parser.parse_args()


def main() -> None:
    setup_logging()
    args = _parse_args()
    cfg = get_config()

    if args.command in ("dashboard", "run") and getattr(args, "port", None):
        cfg.dashboard.port = args.port

    # Apply search-related CLI overrides
    if args.command in ("search", "run"):
        if getattr(args, "queries_file", None):
            cfg.serper.queries_file = args.queries_file
        if getattr(args, "pages", None):
            cfg.serper.pages_per_query = max(1, args.pages)

    # Lazy import to keep startup fast
    from mm2hunter.orchestrator import run_dashboard, run_full, run_pipeline

    if args.command == "search":
        asyncio.run(run_pipeline(cfg))
    elif args.command == "dashboard":
        asyncio.run(run_dashboard(cfg))
    elif args.command == "run":
        asyncio.run(run_full(cfg))
    else:
        print("Usage: mm2hunter {search|dashboard|run}")
        print("Run 'mm2hunter --help' for details.")
        sys.exit(1)


if __name__ == "__main__":
    main()
