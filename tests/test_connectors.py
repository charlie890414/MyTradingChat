"""Tests for external evidence connectors."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pandas as pd

from trading_debate.connectors.bing_news import fetch_bing_news
from trading_debate.connectors.finmind import fetch_finmind
from trading_debate.connectors.finnhub import fetch_finnhub
from trading_debate.connectors.google_news import fetch_google_news
from trading_debate.connectors.reddit import _fetch_subreddit_rss, fetch_reddit_summary
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


@patch("trading_debate.connectors.google_news.feedparser")
def test_fetch_google_news_returns_items(mock_feedparser):
    mock_feedparser.parse.return_value = type(
        "Feed",
        (),
        {
            "entries": [
                {
                    "title": "Apple hits new high",
                    "link": "https://example.com/1",
                    "published": "Mon, 28 Jul 2026 10:00:00 GMT",
                    "summary": "Apple stock reaches record.",
                    "source": {"title": "Reuters", "href": "https://reuters.com"},
                },
                {
                    "title": "iPhone sales surge",
                    "link": "https://example.com/2",
                    "published": "",
                    "summary": "Sales top estimates.",
                },
            ]
        },
    )()
    items = fetch_google_news("run-1", "AAPL", 10)
    assert len(items) == 2
    assert items[0].source == "Google News RSS"
    assert items[0].title == "Apple hits new high"
    assert items[0].url == "https://example.com/1"
    assert items[0].published_at is not None


@patch("trading_debate.connectors.bing_news.feedparser")
def test_fetch_bing_news_returns_items(mock_feedparser):
    mock_feedparser.parse.return_value = type(
        "Feed",
        (),
        {
            "entries": [
                {
                    "title": "Microsoft earnings beat",
                    "link": "https://example.com/1",
                    "published": "Mon, 28 Jul 2026 14:00:00 GMT",
                    "summary": "MSFT reports strong quarter.",
                },
                {
                    "title": "Azure growth accelerates",
                    "link": "https://example.com/2",
                    "published": "Mon, 28 Jul 2026 15:00:00 GMT",
                    "summary": "Cloud revenue up 30%.",
                },
            ]
        },
    )()
    items = fetch_bing_news("run-1", "MSFT", 10)
    assert len(items) == 2
    assert items[0].source == "Bing News RSS"
    assert items[0].title == "Microsoft earnings beat"
    assert items[0].url == "https://example.com/1"


@patch("trading_debate.connectors.google_news.feedparser")
def test_fetch_google_news_respects_limit(mock_feedparser):
    mock_feedparser.parse.return_value = type(
        "Feed",
        (),
        {
            "entries": [
                {"title": f"Article {i}", "link": f"https://e.com/{i}", "published": ""}
                for i in range(20)
            ]
        },
    )()
    items = fetch_google_news("run-1", "AAPL", 5)
    assert len(items) == 5


@patch("trading_debate.connectors.bing_news.feedparser")
def test_fetch_bing_news_respects_limit(mock_feedparser):
    mock_feedparser.parse.return_value = type(
        "Feed",
        (),
        {
            "entries": [
                {"title": f"Article {i}", "link": f"https://e.com/{i}", "published": ""}
                for i in range(15)
            ]
        },
    )()
    items = fetch_bing_news("run-1", "MSFT", 3)
    assert len(items) == 3


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


def test_fetch_reddit_summary_returns_aggregate():
    posts = [
        {
            "subreddit": "stocks",
            "title": "AAPL discussion",
            "url": "https://reddit.com/r/stocks/comments/1/aapl",
            "created_utc": 1704067200.0,
            "published": "2026-01-01T00:00:00+00:00",
            "source": "rss",
        }
    ]
    with patch(
        "trading_debate.connectors.reddit._fetch_all_subreddits", return_value=posts
    ):
        items = fetch_reddit_summary("run-1", "AAPL", 10)
    assert len(items) == 1
    payload = items[0].payload
    assert payload["post_count"] == 1
    assert payload["score_total"] is None
    assert payload["comment_total"] is None
    assert payload["sample_urls"] == ["https://reddit.com/r/stocks/comments/1/aapl"]


def test_fetch_reddit_rss_parses_atom_entries():
    atom = b"""<?xml version="1.0" encoding="UTF-8"?>
    <feed xmlns="http://www.w3.org/2005/Atom">
      <entry>
        <title>NVDA earnings beat</title>
        <published>2026-05-20T14:30:00Z</published>
        <link rel="alternate" href="https://reddit.com/r/stocks/comments/1/nvda" />
      </entry>
    </feed>
    """

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self):
            return atom

    with patch("trading_debate.connectors.reddit.urlopen", return_value=Response()):
        posts = _fetch_subreddit_rss("NVDA", "stocks", 5, timeout=5.0)

    assert len(posts) == 1
    assert posts[0]["title"] == "NVDA earnings beat"
    assert posts[0]["source"] == "rss"
    assert posts[0]["url"] == "https://reddit.com/r/stocks/comments/1/nvda"


def test_fetch_reddit_summary_skips_taiwan_stock():
    items = fetch_reddit_summary("run-1", "2330.TW", 10)
    assert len(items) == 1
    assert items[0].title == "Connector skipped"
