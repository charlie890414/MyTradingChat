"""Live integration tests for external evidence connectors.

These tests hit real services and require internet access. Run with:

    pytest -m network
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from dotenv import load_dotenv

from trading_debate.connectors.bing_news import fetch_bing_news
from trading_debate.connectors.finmind import fetch_finmind
from trading_debate.connectors.finnhub import fetch_finnhub
from trading_debate.connectors.google_news import fetch_google_news
from trading_debate.connectors.sec import fetch_sec
from trading_debate.connectors.twse import fetch_twse_mops
from trading_debate.connectors.yahoo import fetch_yahoo
from trading_debate.utils import is_recent_news

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


def test_fetch_twse_mops_live_returns_real_profile():
    items = fetch_twse_mops("test-live", "1101", 0)
    profile_items = [
        item for item in items if item.source == "TWSE/TPEX Official Company Profile"
    ]
    assert profile_items
    assert profile_items[0].title == "Official company profile"
    assert str(profile_items[0].payload.get("公司代號", "")).strip() == "1101"


def test_fetch_finmind_live_returns_real_taiwan_news_or_empty_list():
    if not os.getenv("FINMIND_TOKEN"):
        pytest.skip("Set FINMIND_TOKEN to run FinMind live integration test")
    items = fetch_finmind("test-live", "2330", 5)
    assert len(items) > 0, "Expected at least one article from FinMind"
    news_items = [item for item in items if item.source == "FinMind TaiwanStockNews"]
    for item in news_items:
        assert item.title
        assert item.url
        assert is_recent_news(item.published_at)


def test_fetch_finnhub_live_returns_real_company_news():
    if not os.getenv("FINNHUB_API_KEY"):
        pytest.skip("Set FINNHUB_API_KEY to run Finnhub live integration test")
    items = fetch_finnhub("test-live", "AAPL", 5)
    assert len(items) > 0, "Expected at least one article from Finnhub"
    news_items = [item for item in items if item.source == "Finnhub Company News"]
    assert news_items, "Expected at least one Finnhub company-news item"
    for item in news_items:
        assert item.title
        assert item.url


def test_fetch_sec_live_returns_official_filings():
    items = fetch_sec("test-live", "AAPL", 5)
    assert any(item.source == "SEC EDGAR" for item in items)
    assert any(item.source == "SEC EDGAR Company Facts" for item in items)
