"""Tests for external evidence connectors."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from trading_debate.connectors.alpha_vantage import fetch_alpha_vantage
from trading_debate.connectors.finmind import fetch_finmind
from trading_debate.connectors.finnhub import fetch_finnhub
from trading_debate.connectors.reddit import fetch_reddit_summary
from trading_debate.connectors.twse import fetch_twse_mops
from trading_debate.connectors.yahoo import fetch_yahoo

from .conftest import make_history


def test_fetch_yahoo_returns_result_with_items():
    history = make_history(5)
    mock_ticker = MagicMock()
    mock_ticker.get_info.return_value = {"currentPrice": 150.0}
    mock_ticker.history.return_value = history
    mock_ticker.get_news.return_value = [
        {"content": {"title": "News 1", "pubDate": "2026-01-01"}}
    ]

    result = fetch_yahoo("run-1", "AAPL", 10, ticker=mock_ticker)
    assert result.stored_news == 1
    assert result.price["close"] is not None
    assert len(result.items) >= 4
    assert any(item.source == "Yahoo Finance News" for item in result.items)


def test_fetch_yahoo_uses_injected_ticker():
    mock_ticker = MagicMock()
    mock_ticker.get_info.return_value = {"currentPrice": 100.0}
    mock_ticker.history.return_value = pd.DataFrame(
        {"Close": [100.0]}, index=pd.to_datetime(["2026-01-01"], utc=True)
    )
    mock_ticker.get_news.return_value = []
    fetch_yahoo("run-1", "AAPL", 10, ticker=mock_ticker)
    mock_ticker.get_info.assert_called_once()


@patch("trading_debate.connectors.alpha_vantage.os.getenv")
@patch("trading_debate.connectors.alpha_vantage.request_json")
def test_fetch_alpha_vantage_returns_items_when_key_present(mock_request, mock_getenv):
    mock_getenv.return_value = "fake-key"
    mock_request.return_value = {
        "feed": [
            {
                "title": "Alpha article",
                "url": "https://example.com",
                "time_published": "20260101T000000",
            }
        ]
    }
    items = fetch_alpha_vantage("run-1", "AAPL", 10)
    assert len(items) == 1
    assert items[0].source == "Alpha Vantage News & Sentiment"


@patch("trading_debate.connectors.alpha_vantage.os.getenv")
def test_fetch_alpha_vantage_returns_skipped_status_when_key_missing(mock_getenv):
    mock_getenv.return_value = None
    items = fetch_alpha_vantage("run-1", "AAPL", 10)
    assert len(items) == 1
    assert items[0].title == "Connector skipped"


@patch("trading_debate.connectors.alpha_vantage.os.getenv")
@patch("trading_debate.connectors.alpha_vantage.request_json")
def test_fetch_alpha_vantage_raises_on_api_error(mock_request, mock_getenv):
    mock_getenv.return_value = "fake-key"
    mock_request.return_value = {"Information": "API rate limit reached"}
    with pytest.raises(RuntimeError, match="API rate limit"):
        fetch_alpha_vantage("run-1", "AAPL", 10)


@patch("trading_debate.connectors.finnhub.os.getenv")
@patch("trading_debate.connectors.finnhub.request_json")
def test_fetch_finnhub_returns_items_when_key_present(mock_request, mock_getenv):
    mock_getenv.return_value = "fake-key"
    mock_request.return_value = [
        {
            "headline": "Finnhub article",
            "url": "https://example.com",
            "datetime": 1704067200,
        }
    ]
    items = fetch_finnhub("run-1", "AAPL", 10)
    assert len(items) == 1
    assert items[0].source == "Finnhub Company News"


@patch("trading_debate.connectors.finnhub.os.getenv")
def test_fetch_finnhub_returns_skipped_status_when_key_missing(mock_getenv):
    mock_getenv.return_value = None
    items = fetch_finnhub("run-1", "AAPL", 10)
    assert len(items) == 1
    assert items[0].title == "Connector skipped"


@patch("trading_debate.connectors.finmind.os.getenv")
@patch("trading_debate.connectors.finmind.request_json")
def test_fetch_finmind_returns_items_for_taiwan_code(mock_request, mock_getenv):
    mock_getenv.return_value = "fake-token"
    mock_request.return_value = {
        "status": 200,
        "data": [
            {
                "title": "Taiwan news",
                "link": "https://example.com",
                "date": "2026-01-01",
            }
        ],
    }
    items = fetch_finmind("run-1", "2330.TW", 10)
    assert len(items) == 1
    assert items[0].source == "FinMind TaiwanStockNews"


def test_fetch_finmind_returns_skipped_for_non_taiwan_symbol():
    items = fetch_finmind("run-1", "AAPL", 10)
    assert len(items) == 1
    assert items[0].title == "Connector skipped"


@patch("trading_debate.connectors.twse.request_json")
def test_fetch_twse_mops_returns_profile_for_taiwan_code(mock_request):
    mock_request.return_value = [
        {"公司代號": "2330", "公司名稱": "TSMC", "產業別": "半導體"}
    ]
    items = fetch_twse_mops("run-1", "2330.TW", 0)
    assert len(items) == 1
    assert items[0].source == "TWSE OpenAPI / MOPS"


@patch("trading_debate.connectors.twse.request_json")
def test_fetch_twse_mops_returns_empty_when_no_profile(mock_request):
    mock_request.return_value = []
    items = fetch_twse_mops("run-1", "2330.TW", 0)
    assert len(items) == 1
    assert items[0].title == "Connector empty"


def test_fetch_twse_mops_returns_skipped_for_non_taiwan_symbol():
    items = fetch_twse_mops("run-1", "AAPL", 0)
    assert len(items) == 1
    assert items[0].title == "Connector skipped"


@patch("trading_debate.connectors.reddit.request_json")
def test_fetch_reddit_summary_returns_aggregate(mock_request):
    mock_request.return_value = {
        "data": {
            "children": [
                {"data": {"score": 10, "num_comments": 5, "permalink": "/r/x/1"}}
            ]
        }
    }
    items = fetch_reddit_summary("run-1", "AAPL", 10)
    assert len(items) == 1
    payload = items[0].payload
    assert payload["post_count"] == 1
    assert payload["score_total"] == 10


def test_fetch_reddit_summary_skips_taiwan_stock():
    items = fetch_reddit_summary("run-1", "2330.TW", 10)
    assert len(items) == 1
    assert items[0].title == "Connector skipped"
