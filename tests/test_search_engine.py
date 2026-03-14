"""Tests for the search engine – query loading and pagination."""

import textwrap
from pathlib import Path

from mm2hunter.search.engine import DEFAULT_QUERIES, SearchEngine, load_queries_from_file
from mm2hunter.config import SerperConfig


# ---------------------------------------------------------------------------
# load_queries_from_file
# ---------------------------------------------------------------------------

def test_load_queries_from_file(tmp_path: Path):
    qf = tmp_path / "queries.txt"
    qf.write_text(textwrap.dedent("""\
        # comment line
        "MM2" shop harvester
        "Murder Mystery 2" buy cheap

        # another comment
        roblox mm2 godly shop
    """))
    result = load_queries_from_file(str(qf))
    assert result == [
        '"MM2" shop harvester',
        '"Murder Mystery 2" buy cheap',
        "roblox mm2 godly shop",
    ]


def test_load_queries_from_missing_file():
    result = load_queries_from_file("/nonexistent/path/queries.txt")
    assert result == []


def test_load_queries_empty_file(tmp_path: Path):
    qf = tmp_path / "empty.txt"
    qf.write_text("# only comments\n\n  \n")
    result = load_queries_from_file(str(qf))
    assert result == []


# ---------------------------------------------------------------------------
# SearchEngine._get_queries
# ---------------------------------------------------------------------------

def test_engine_uses_default_queries():
    cfg = SerperConfig()
    cfg.api_keys = ["fake_key"]
    engine = SearchEngine(cfg)
    queries = engine._get_queries()
    assert queries == DEFAULT_QUERIES


def test_engine_uses_file_queries(tmp_path: Path):
    qf = tmp_path / "custom.txt"
    qf.write_text("query one\nquery two\n")
    cfg = SerperConfig()
    cfg.api_keys = ["fake_key"]
    cfg.queries_file = str(qf)
    engine = SearchEngine(cfg)
    queries = engine._get_queries()
    assert queries == ["query one", "query two"]


def test_engine_falls_back_if_file_empty(tmp_path: Path):
    qf = tmp_path / "empty.txt"
    qf.write_text("")
    cfg = SerperConfig()
    cfg.api_keys = ["fake_key"]
    cfg.queries_file = str(qf)
    engine = SearchEngine(cfg)
    queries = engine._get_queries()
    assert queries == DEFAULT_QUERIES


# ---------------------------------------------------------------------------
# pages_per_query config
# ---------------------------------------------------------------------------

def test_pages_per_query_default():
    cfg = SerperConfig()
    assert cfg.pages_per_query == 1


def test_pages_per_query_from_env(monkeypatch):
    monkeypatch.setenv("SERPER_PAGES_PER_QUERY", "3")
    cfg = SerperConfig()
    assert cfg.pages_per_query == 3
