"""Live integration tests for external evidence connectors.

These tests hit real services and require internet access. Run with:

    pytest -m network
"""

from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import patch

import pytest
from dotenv import load_dotenv

from trading_debate.connectors.bing_news import fetch_bing_news
from trading_debate.connectors.finmind import fetch_finmind
from trading_debate.connectors.finnhub import fetch_finnhub
from trading_debate.connectors.google_news import fetch_google_news
from trading_debate.connectors.reddit import fetch_reddit_summary
from trading_debate.connectors.twse import fetch_twse_mops
from trading_debate.connectors.yahoo import fetch_yahoo

load_dotenv(Path(__file__).resolve().parents[1] / ".env")

pytestmark = pytest.mark.network


def test_fetch_google_news_live_returns_real_articles():
    items = fetch_google_news("test-live", "AAPL", 10)
    assert len(items) > 0, "Expected at least one article from Google News RSS"
    for item in items:
        assert item.source == "Google News RSS"
        assert item.title, "Article has empty title"
        assert item.url, f"Article '{item.title}' has no URL"
        assert item.payload.get("link"), f"Payload missing link for '{item.title}'"


def test_fetch_bing_news_live_returns_real_articles():
    items = fetch_bing_news("test-live", "AAPL", 10)
    assert len(items) > 0, "Expected at least one article from Bing News RSS"
    for item in items:
        assert item.source == "Bing News RSS"
        assert item.title, "Article has empty title"
        assert item.url, f"Article '{item.title}' has no URL"


def test_fetch_yahoo_live_returns_real_market_data():
    result = fetch_yahoo("test-live", "AAPL", 5)
    assert len(result.items) >= 4
    assert result.fundamentals, "Expected Yahoo Finance fundamentals"
    assert result.price["close"] is not None, "Expected Yahoo Finance close price"
    assert result.technicals["as_of"] is not None, "Expected computed technicals"


def test_fetch_reddit_summary_live_returns_real_aggregate():
    items = fetch_reddit_summary("test-live", "AAPL", 10)
    assert len(items) == 1
    assert items[0].source == "Reddit search aggregate"
    payload = items[0].payload
    assert payload["query"] == "AAPL"
    assert isinstance(payload["post_count"], int)
    assert payload["source"] == "rss"
    assert isinstance(payload["sample_urls"], list)


def test_fetch_twse_mops_live_returns_real_profile():
    items = fetch_twse_mops("test-live", "1101", 0)
    assert len(items) == 1
    assert items[0].source == "TWSE OpenAPI / MOPS"
    assert items[0].title == "Official listed-company disclosure profile"
    assert str(items[0].payload.get("公司代號", "")).strip() == "1101"


def test_fetch_finmind_live_returns_real_taiwan_news_or_empty_list():
    if not os.getenv("FINMIND_TOKEN"):
        pytest.skip("Set FINMIND_TOKEN to run FinMind live integration test")
    with patch(
        "trading_debate.connectors.finmind.date_range_days",
        return_value=("2024-01-02", "2024-01-02"),
    ):
        items = fetch_finmind("test-live", "2330", 5)
    assert len(items) > 0, "Expected at least one article from FinMind"
    for item in items:
        assert item.source == "FinMind TaiwanStockNews"
        assert item.title
        assert item.url


def test_fetch_finnhub_live_returns_real_company_news():
    if not os.getenv("FINNHUB_API_KEY"):
        pytest.skip("Set FINNHUB_API_KEY to run Finnhub live integration test")
    items = fetch_finnhub("test-live", "AAPL", 5)
    assert len(items) > 0, "Expected at least one article from Finnhub"
    for item in items:
        assert item.source == "Finnhub Company News"
        assert item.title
        assert item.url
