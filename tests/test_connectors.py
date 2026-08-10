"""Tests for external evidence connectors."""

from __future__ import annotations

import sys
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pandas as pd

from trading_debate.connectors.bing_news import fetch_bing_news
from trading_debate.connectors.finmind import fetch_finmind
from trading_debate.connectors.finnhub import fetch_finnhub
from trading_debate.connectors.gdelt import fetch_gdelt_news
from trading_debate.connectors.google_news import fetch_google_news
from trading_debate.connectors.market import (
    fetch_official_market_data,
    fetch_official_valuation_data,
)
from trading_debate.connectors.mops import _extract_pdf_text, fetch_mops_documents
from trading_debate.connectors.sec import fetch_sec
from trading_debate.connectors.twse import fetch_twse_mops
from trading_debate.connectors.yahoo import fetch_yahoo

from .conftest import make_history


def test_fetch_yahoo_returns_result_with_items():
    history = make_history(5)
    mock_ticker = MagicMock()
    mock_ticker.get_info.return_value = {"currentPrice": 150.0}
    mock_ticker.history.return_value = history
    mock_ticker.get_news.return_value = [
        {
            "content": {
                "title": "News 1",
                "pubDate": datetime.now(UTC).isoformat(),
            }
        },
        {"content": {"title": "Old news", "pubDate": "2020-01-01"}},
    ]
    mock_ticker.get_earnings_estimate.return_value = pd.DataFrame(
        {"avg": [2.0], "growth": [0.05]}, index=["0q"]
    )
    mock_ticker.get_revenue_estimate.return_value = pd.DataFrame(
        {"avg": [500.0]}, index=["0q"]
    )
    mock_ticker.get_growth_estimates.return_value = pd.DataFrame(
        {"stock": [0.1]}, index=["0y"]
    )
    mock_ticker.get_eps_trend.return_value = pd.DataFrame(
        {"current": [2.0], "7daysAgo": [1.9]}, index=["0q"]
    )
    mock_ticker.get_eps_revisions.return_value = pd.DataFrame(
        {"upLast7days": [1]}, index=["0q"]
    )
    mock_ticker.get_analyst_price_targets.return_value = {
        "current": 150.0,
        "mean": 160.0,
    }
    mock_ticker.get_recommendations.return_value = pd.DataFrame(
        {"period": ["0m"], "strongBuy": [2], "buy": [5]}
    )
    mock_ticker.get_income_stmt.return_value = pd.DataFrame(
        {"TotalRevenue": [100.0]}, index=[pd.Timestamp("2025-12-31")]
    )
    mock_ticker.get_balance_sheet.return_value = pd.DataFrame(
        {"TotalAssets": [300.0]}, index=[pd.Timestamp("2025-12-31")]
    )
    mock_ticker.get_cash_flow.return_value = pd.DataFrame(
        {"OperatingCashFlow": [40.0]}, index=[pd.Timestamp("2025-12-31")]
    )
    mock_ticker.get_calendar.return_value = {"earningsDate": "2026-04-20"}
    mock_ticker.get_earnings_dates.return_value = pd.DataFrame(
        {"Reported EPS": [2.0]}, index=[pd.Timestamp("2026-01-29")]
    )
    mock_ticker.get_dividends.return_value = pd.Series(
        {pd.Timestamp("2026-02-01"): 0.25}
    )
    mock_ticker.get_splits.return_value = pd.Series({pd.Timestamp("2025-08-01"): 4.0})
    mock_ticker.get_institutional_holders.return_value = pd.DataFrame(
        {"holder": ["Vanguard"], "shares": [1000]}
    )
    mock_ticker.get_insider_purchases.return_value = pd.DataFrame({"shares": [10.0]})
    mock_ticker.get_insider_transactions.return_value = pd.DataFrame({"shares": [20.0]})

    result = fetch_yahoo("run-1", "AAPL", 10, ticker=mock_ticker)
    assert result.stored_news == 1
    assert result.price["close"] is not None
    assert len(result.items) >= 4
    assert any(item.source == "Yahoo Finance News" for item in result.items)
    assert not any(item.title == "Old news" for item in result.items)
    daily = next(item for item in result.items if item.title == "Daily OHLCV history")
    assert daily.payload["price_adjustment"]
    assert any(item.title == "Weekly adjusted OHLCV history" for item in result.items)
    assert any(item.title == "Monthly adjusted OHLCV history" for item in result.items)
    analyst = next(
        item for item in result.items if item.title.startswith("Analyst estimates")
    )
    assert analyst.payload["earnings_estimate"]["rows"][0]["avg"] == 2.0
    assert any(item.title == "Analyst price targets" for item in result.items)
    assert any(item.title == "Analyst recommendations" for item in result.items)
    assert any(item.title.startswith("Income statement") for item in result.items)
    assert any(item.title.startswith("Balance sheet") for item in result.items)
    assert any(item.title.startswith("Cash flow statement") for item in result.items)
    assert any(item.title == "Earnings calendar & dates" for item in result.items)
    assert any(item.title == "Dividends & splits history" for item in result.items)
    assert any(item.title == "Institutional holders" for item in result.items)
    assert any(
        item.title == "Insider purchases & transactions" for item in result.items
    )
    statements = [
        item
        for item in result.items
        if item.title.startswith(("Income statement", "Balance sheet"))
    ]
    assert all(len(item.payload["data"]["rows"]) <= 4 for item in statements)


def test_fetch_yahoo_uses_injected_ticker():
    mock_ticker = MagicMock()
    mock_ticker.get_info.return_value = {"currentPrice": 100.0}
    mock_ticker.history.return_value = pd.DataFrame(
        {"Close": [100.0]}, index=pd.to_datetime(["2026-01-01"], utc=True)
    )
    mock_ticker.get_news.return_value = []
    fetch_yahoo("run-1", "AAPL", 10, ticker=mock_ticker)
    mock_ticker.get_info.assert_called_once()


def test_fetch_yahoo_uses_default_session_when_no_ticker():
    mock_ticker = MagicMock()
    mock_ticker.get_info.return_value = {}
    mock_ticker.history.return_value = pd.DataFrame(
        {"Close": [100.0]}, index=pd.to_datetime(["2026-01-01"], utc=True)
    )
    mock_ticker.get_news.return_value = []
    with patch(
        "trading_debate.connectors.yahoo.yfinance.Ticker", return_value=mock_ticker
    ) as mock_factory:
        with patch("trading_debate.connectors.yahoo._enable_retries") as mock_retries:
            fetch_yahoo("run-1", "AAPL", 10)
    mock_retries.assert_called_once()
    mock_factory.assert_called_once_with("AAPL")


def test_enable_retries_raises_yfinance_retry_budget():
    from yfinance.utils import YfConfig

    from trading_debate.connectors.yahoo import _enable_retries

    original = YfConfig.network.retries
    try:
        _enable_retries()
        assert int(YfConfig.network.retries) >= 3
        _enable_retries()
        assert int(YfConfig.network.retries) >= 3
    finally:
        YfConfig.network.retries = original


@patch("trading_debate.connectors.google_news.feedparser")
def test_fetch_google_news_returns_items(mock_feedparser):
    recent = datetime.now(UTC).strftime("%a, %d %b %Y %H:%M:%S GMT")
    old = (datetime.now(UTC) - timedelta(days=31)).strftime("%a, %d %b %Y %H:%M:%S GMT")
    mock_feedparser.parse.return_value = type(
        "Feed",
        (),
        {
            "entries": [
                {
                    "title": "Apple hits new high",
                    "link": "https://example.com/1",
                    "published": recent,
                    "summary": "Apple stock reaches record.",
                    "source": {"title": "Reuters", "href": "https://reuters.com"},
                },
                {
                    "title": "iPhone sales surge",
                    "link": "https://example.com/2",
                    "published": old,
                    "summary": "Sales top estimates.",
                },
            ]
        },
    )()
    items = fetch_google_news("run-1", "AAPL", 10)
    assert len(items) == 1
    assert items[0].source == "Google News RSS"
    assert items[0].title == "Apple hits new high"
    assert items[0].url == "https://example.com/1"
    assert items[0].published_at is not None


@patch("trading_debate.connectors.bing_news.feedparser")
def test_fetch_bing_news_returns_items(mock_feedparser):
    recent = datetime.now(UTC).strftime("%a, %d %b %Y %H:%M:%S GMT")
    mock_feedparser.parse.return_value = type(
        "Feed",
        (),
        {
            "entries": [
                {
                    "title": "Microsoft earnings beat",
                    "link": "https://example.com/1",
                    "published": recent,
                    "summary": "MSFT reports strong quarter.",
                },
                {
                    "title": "Azure growth accelerates",
                    "link": "https://example.com/2",
                    "published": recent,
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


@patch("trading_debate.connectors.bing_news.feedparser")
def test_fetch_bing_news_skips_items_older_than_7_days(mock_feedparser):
    recent = datetime.now(UTC).strftime("%a, %d %b %Y %H:%M:%S GMT")
    old = (datetime.now(UTC) - timedelta(days=8)).strftime("%a, %d %b %Y %H:%M:%S GMT")
    mock_feedparser.parse.return_value = type(
        "Feed",
        (),
        {
            "entries": [
                {
                    "title": "Old Microsoft article",
                    "link": "https://example.com/old",
                    "published": old,
                },
                {
                    "title": "Recent Microsoft article",
                    "link": "https://example.com/recent",
                    "published": recent,
                },
            ]
        },
    )()

    items = fetch_bing_news("run-1", "MSFT", 10)

    assert [item.title for item in items] == ["Recent Microsoft article"]


@patch("trading_debate.connectors.google_news.feedparser")
def test_fetch_google_news_uses_company_name_for_taiwan_symbol(mock_feedparser):
    mock_feedparser.parse.return_value = type(
        "Feed",
        (),
        {
            "entries": [
                {
                    "title": "Unimicron expands capacity",
                    "link": "https://example.com/1",
                    "published": datetime.now(UTC).strftime(
                        "%a, %d %b %Y %H:%M:%S GMT"
                    ),
                    "summary": "",
                    "source": {"title": "Reuters", "href": "https://reuters.com"},
                }
            ]
        },
    )()
    items = fetch_google_news("run-1", "3037.TW", 10, company_name="欣興電子")
    assert len(items) == 1
    called_url = mock_feedparser.parse.call_args[0][0]
    assert "%E6%AC%A3%E8%88%88" in called_url  # URL-encoded 欣興
    assert "3037.TW" not in called_url
    assert "stock" not in called_url


@patch("trading_debate.connectors.google_news.feedparser")
def test_fetch_google_news_disambiguates_short_us_ticker(mock_feedparser):
    mock_feedparser.parse.return_value = type("Feed", (), {"entries": []})()

    fetch_google_news("run-1", "BE", 10, company_name="Bloom Energy Corporation")

    called_url = mock_feedparser.parse.call_args[0][0]
    assert "Bloom%20Energy%20Corporation" in called_url
    assert "q=BE%2Bstock" not in called_url


@patch("trading_debate.connectors.google_news.feedparser")
def test_fetch_google_news_respects_limit(mock_feedparser):
    recent = datetime.now(UTC).strftime("%a, %d %b %Y %H:%M:%S GMT")
    mock_feedparser.parse.return_value = type(
        "Feed",
        (),
        {
            "entries": [
                {
                    "title": f"Article {i}",
                    "link": f"https://e.com/{i}",
                    "published": recent,
                }
                for i in range(20)
            ]
        },
    )()
    items = fetch_google_news("run-1", "AAPL", 5)
    assert len(items) == 5


@patch("trading_debate.connectors.bing_news.feedparser")
def test_fetch_bing_news_uses_company_name_for_taiwan_symbol(mock_feedparser):
    mock_feedparser.parse.return_value = type(
        "Feed",
        (),
        {
            "entries": [
                {
                    "title": "Unimicron raises guidance",
                    "link": "https://example.com/1",
                    "published": datetime.now(UTC).strftime(
                        "%a, %d %b %Y %H:%M:%S GMT"
                    ),
                    "summary": "",
                }
            ]
        },
    )()
    items = fetch_bing_news("run-1", "3037.TW", 10, company_name="欣興電子")
    assert len(items) == 1
    called_url = mock_feedparser.parse.call_args[0][0]
    assert "%E6%AC%A3%E8%88%88" in called_url  # URL-encoded 欣興
    assert "3037.TW" not in called_url
    assert "stock" not in called_url


@patch("trading_debate.connectors.bing_news.feedparser")
def test_fetch_bing_news_disambiguates_short_us_ticker(mock_feedparser):
    mock_feedparser.parse.return_value = type("Feed", (), {"entries": []})()

    fetch_bing_news("run-1", "BE", 10, company_name="Bloom Energy Corporation")

    called_url = mock_feedparser.parse.call_args[0][0]
    assert "Bloom%20Energy%20Corporation" in called_url
    assert "q=BE%2Bstock" not in called_url


@patch("trading_debate.connectors.bing_news.feedparser")
def test_fetch_bing_news_respects_limit(mock_feedparser):
    recent = datetime.now(UTC).strftime("%a, %d %b %Y %H:%M:%S GMT")
    mock_feedparser.parse.return_value = type(
        "Feed",
        (),
        {
            "entries": [
                {
                    "title": f"Article {i}",
                    "link": f"https://e.com/{i}",
                    "published": recent,
                }
                for i in range(15)
            ]
        },
    )()
    items = fetch_bing_news("run-1", "MSFT", 3)
    assert len(items) == 3


@patch("trading_debate.connectors.gdelt.request_json")
def test_fetch_gdelt_news_returns_recent_articles(mock_request):
    mock_request.return_value = {
        "articles": [
            {
                "title": "台積電 expands capacity",
                "url": "https://example.com/tsmc",
                "seendate": datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ"),
                "domain": "example.com",
                "language": "Chinese",
                "sourcecountry": "Taiwan",
            },
            {
                "title": "Old article",
                "url": "https://example.com/old",
                "seendate": "20200101T000000Z",
            },
        ]
    }

    items = fetch_gdelt_news("run-1", "2330.TW", 10, company_name="台積電")

    assert len(items) == 1
    assert items[0].source == "GDELT News"
    assert items[0].payload["source_country"] == "Taiwan"
    params = mock_request.call_args.args[1]
    assert params["query"] == '"台積電"'
    assert params["timespan"] == "7d"


@patch("trading_debate.connectors.gdelt.request_json")
def test_fetch_gdelt_news_records_empty_and_errors(mock_request):
    mock_request.return_value = {"articles": []}
    assert fetch_gdelt_news("run-1", "AAPL", 10)[0].title == "Connector empty"

    mock_request.side_effect = RuntimeError("rate limited")
    assert fetch_gdelt_news("run-1", "AAPL", 10)[0].title == "Connector error"


@patch("trading_debate.connectors.gdelt.request_json")
def test_fetch_gdelt_news_skips_requests_when_limit_is_zero(mock_request):
    items = fetch_gdelt_news("run-1", "AAPL", 0)

    assert items[0].title == "Connector empty"
    mock_request.assert_not_called()


@patch("trading_debate.connectors.finnhub.os.getenv")
@patch("trading_debate.connectors.finnhub.request_json")
def test_fetch_finnhub_returns_items_when_key_present(mock_request, mock_getenv):
    mock_getenv.return_value = "fake-key"
    mock_request.side_effect = [
        [
            {
                "headline": "Finnhub article",
                "url": "https://example.com",
                "datetime": int(datetime.now(UTC).timestamp()),
            }
        ],
        {"metric": {"grossMarginTTM": 0.5}},
        [{"period": "2026-01-01", "actual": 1.2, "estimate": 1.1}],
        [{"period": "2026-01-01", "buy": 10, "hold": 2, "sell": 1}],
        {"targetMean": 200.0, "targetHigh": 220.0, "targetLow": 180.0},
        {"data": [{"endDate": "2026-01-01", "report": {}}]},
    ]
    items = fetch_finnhub("run-1", "AAPL", 10)
    assert any(item.source == "Finnhub Company News" for item in items)
    assert any(item.source == "Finnhub Basic Financials" for item in items)
    assert any(item.source == "Finnhub Earnings" for item in items)
    assert any(item.source == "Finnhub Recommendation Trends" for item in items)
    assert any(item.source == "Finnhub Price Targets" for item in items)
    assert any(item.source == "Finnhub Financials As Reported" for item in items)
    requested_urls = [call.args[0] for call in mock_request.call_args_list]
    assert not any("stock/revenue-estimate" in url for url in requested_urls)
    assert not any("stock/eps-estimate" in url for url in requested_urls)
    assert any("stock/price-target" in url for url in requested_urls)
    assert "price-target" not in requested_urls


@patch("trading_debate.connectors.finnhub.os.getenv")
def test_fetch_finnhub_returns_skipped_status_when_key_missing(mock_getenv):
    mock_getenv.return_value = None
    items = fetch_finnhub("run-1", "AAPL", 10)
    assert len(items) == 1
    assert items[0].title == "Connector skipped"


def test_active_connectors_do_not_register_valuation_twice():
    from trading_debate.connectors import CONNECTORS

    assert "TWSE Official Valuation Data" not in CONNECTORS


@patch("trading_debate.connectors.finmind.os.getenv")
@patch("trading_debate.connectors.finmind.request_json")
def test_fetch_finmind_returns_items_for_taiwan_code(mock_request, mock_getenv):
    mock_getenv.return_value = "fake-token"
    mock_request.side_effect = [
        {
            "status": 200,
            "data": [
                {
                    "title": "Taiwan news",
                    "link": "https://example.com",
                    "date": datetime.now(UTC).date().isoformat(),
                }
            ],
        },
        {"status": 200, "data": [{"date": "2026-01-01", "revenue": 100}]},
        {"status": 200, "data": []},
        {"status": 200, "data": []},
        {"status": 200, "data": []},
        {"status": 200, "data": []},
        {"status": 200, "data": []},
    ]
    items = fetch_finmind("run-1", "2330.TW", 10)
    assert any(item.source == "FinMind TaiwanStockNews" for item in items)
    assert any(item.source == "FinMind TaiwanStockMonthRevenue" for item in items)


@patch("trading_debate.connectors.finmind.os.getenv")
@patch("trading_debate.connectors.finmind.request_json")
def test_fetch_finmind_adds_latest_financial_and_trading_snapshots(
    mock_request, mock_getenv
):
    mock_getenv.return_value = "fake-token"
    mock_request.side_effect = [
        {"status": 200, "data": []},
        {"status": 200, "data": []},
        {
            "status": 200,
            "data": [{"date": "2026-06-30", "type": "Revenue", "value": 100}],
        },
        {
            "status": 200,
            "data": [{"date": "2026-06-30", "type": "Assets", "value": 200}],
        },
        {
            "status": 200,
            "data": [
                {
                    "date": "2026-06-30",
                    "type": "CashFlowFromOperatingActivities",
                    "value": 50,
                }
            ],
        },
        {
            "status": 200,
            "data": [
                {"date": "2026-07-30", "name": "Foreign_Investor", "buy": 10, "sell": 5}
            ],
        },
        {"status": 200, "data": [{"date": "2026-07-30", "MarginPurchaseBuy": 20}]},
    ]
    items = fetch_finmind("run-1", "2330.TW", 10)
    titles = {item.title for item in items}
    assert "Latest consolidated income statement" in titles
    assert "Latest consolidated balance sheet" in titles
    assert "Latest consolidated cash flow statement" in titles
    assert "Latest institutional investor buy/sell" in titles
    assert "Latest margin purchase and short sale" in titles


@patch("trading_debate.connectors.finmind.os.getenv", return_value="fake-token")
@patch("trading_debate.connectors.finmind.request_json")
def test_fetch_finmind_adds_five_day_trading_trends(mock_request, mock_getenv):
    institutional_rows = [
        {
            "date": f"2026-07-{day:02d}",
            "name": "Foreign_Investor",
            "buy": day * 10,
            "sell": day,
        }
        for day in range(20, 26)
    ]
    margin_rows = [
        {"date": f"2026-07-{day:02d}", "MarginPurchaseTodayBalance": day * 100}
        for day in range(20, 26)
    ]
    mock_request.side_effect = [
        {"status": 200, "data": []},
        {"status": 200, "data": []},
        {"status": 200, "data": []},
        {"status": 200, "data": []},
        {"status": 200, "data": []},
        {"status": 200, "data": institutional_rows},
        {"status": 200, "data": margin_rows},
    ]

    items = fetch_finmind("run-1", "2330.TW", 10)
    institutional = next(
        item for item in items if item.title == "Latest institutional investor buy/sell"
    )
    margin = next(
        item for item in items if item.title == "Latest margin purchase and short sale"
    )

    assert institutional.payload["five_day_trend"]["trading_dates"] == [
        "2026-07-21",
        "2026-07-22",
        "2026-07-23",
        "2026-07-24",
        "2026-07-25",
    ]
    assert (
        institutional.payload["five_day_trend"]["investors"][0]["net_buy_sell"] == 1035
    )
    assert (
        margin.payload["five_day_trend"]["field_changes"]["MarginPurchaseTodayBalance"]
        == 400
    )


@patch("trading_debate.connectors.finmind.os.getenv", return_value="fake-token")
@patch("trading_debate.connectors.finmind.request_json")
def test_fetch_finmind_adds_compact_valuation_and_ownership_snapshots(
    mock_request, mock_getenv
):
    mock_request.return_value = {
        "status": 200,
        "data": [
            {"date": "2026-07-30", "PER": 20, "PBR": 4},
            {"date": "2026-08-01", "PER": 21, "PBR": 4.2},
        ],
    }

    items = fetch_finmind("run-1", "2330.TW", 10)

    compact = [item for item in items if item.title.startswith("Latest ")]
    assert len(compact) >= 7
    valuation = next(item for item in compact if "Valuation history" in item.title)
    assert valuation.payload["latest_date"] == "2026-08-01"
    assert valuation.payload["available_rows"] == 2
    assert valuation.payload["recent_dates"] == ["2026-07-30", "2026-08-01"]
    datasets = {call.args[1]["dataset"] for call in mock_request.call_args_list}
    assert {
        "TaiwanStockPER",
        "TaiwanStockShareholding",
        "TaiwanStockHoldingSharesPer",
        "TaiwanStockSecuritiesLending",
        "TaiwanDailyShortSaleBalances",
        "TaiwanStockDividend",
        "TaiwanStockDividendResult",
    } <= datasets


def test_fetch_finmind_returns_skipped_for_non_taiwan_symbol():
    items = fetch_finmind("run-1", "AAPL", 10)
    assert len(items) == 1
    assert items[0].title == "Connector skipped"


@patch("trading_debate.connectors.finmind.os.getenv")
@patch("trading_debate.connectors.finmind.request_json")
def test_fetch_finmind_uses_correct_institutional_dataset_name(
    mock_request, mock_getenv
):
    mock_getenv.return_value = "fake-token"
    mock_request.return_value = {"status": 200, "data": []}
    fetch_finmind("run-1", "2330.TW", 10)
    datasets = {
        call.args[1]["dataset"]
        for call in mock_request.call_args_list
        if len(call.args) >= 2
    }
    assert "TaiwanStockInstitutionalInvestorsBuySell" in datasets


@patch("trading_debate.connectors.finmind.os.getenv")
@patch("trading_debate.connectors.finmind.request_json")
def test_fetch_finmind_taiwan_stock_news_uses_single_day(mock_request, mock_getenv):
    mock_getenv.return_value = "fake-token"
    mock_request.return_value = {"status": 200, "data": []}
    fetch_finmind("run-1", "2330.TW", 10)
    news_calls = [
        call.args[1]
        for call in mock_request.call_args_list
        if len(call.args) >= 2 and call.args[1].get("dataset") == "TaiwanStockNews"
    ]
    assert len(news_calls) == 1
    assert "end_date" not in news_calls[0]


@patch("trading_debate.connectors.finmind.os.getenv")
@patch("trading_debate.connectors.finmind.request_json")
def test_fetch_finmind_news_limit_zero_skips_only_news(mock_request, mock_getenv):
    mock_getenv.return_value = None
    mock_request.return_value = {"status": 200, "data": []}

    fetch_finmind("run-1", "2330.TW", 0)

    datasets = [call.args[1]["dataset"] for call in mock_request.call_args_list]
    assert "TaiwanStockNews" not in datasets
    assert "TaiwanStockFinancialStatements" in datasets


@patch("trading_debate.connectors.finmind.os.getenv")
@patch("trading_debate.connectors.finmind.request_json")
def test_fetch_finmind_other_datasets_include_end_date(mock_request, mock_getenv):
    mock_getenv.return_value = "fake-token"
    mock_request.return_value = {"status": 200, "data": []}
    fetch_finmind("run-1", "2330.TW", 10)
    non_news_calls = [
        call.args[1]
        for call in mock_request.call_args_list
        if len(call.args) >= 2 and call.args[1].get("dataset") != "TaiwanStockNews"
    ]
    assert non_news_calls
    for params in non_news_calls:
        assert "end_date" in params


@patch("trading_debate.connectors.twse.request_json")
def test_fetch_twse_mops_uses_only_the_resolved_market_for_taiwan_code(mock_request):
    mock_request.return_value = [
        {"公司代號": "2330", "公司名稱": "TSMC", "產業別": "半導體"}
    ]
    items = fetch_twse_mops("run-1", "2330.TW", 0)
    assert any(item.source == "TWSE/TPEX Monthly Revenue" for item in items)
    assert any(item.title.startswith("Official Income statement") for item in items)
    assert any(item.title.startswith("Official Balance sheet") for item in items)
    requested_urls = [call.args[0] for call in mock_request.call_args_list]
    assert not any("t187ap04" in url for url in requested_urls)
    assert not any("tpex.org.tw" in url for url in requested_urls)


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


@patch("trading_debate.connectors.sec.request_text")
@patch("trading_debate.connectors.sec.request_json")
def test_fetch_sec_returns_company_facts_and_filings(mock_request, mock_request_text):
    mock_request.side_effect = [
        {"0": {"cik_str": 320193, "ticker": "AAPL", "title": "Apple Inc."}},
        {
            "facts": {
                "us-gaap": {
                    "Revenues": {
                        "units": {
                            "USD": [
                                {
                                    "val": 100,
                                    "form": "10-K",
                                    "end": "2026-01-01",
                                    "filed": "2026-02-01",
                                }
                            ]
                        }
                    }
                }
            }
        },
        {
            "cik": "0000320193",
            "filings": {
                "recent": {
                    "form": ["10-K", "4"],
                    "accessionNumber": ["0000320193-26-000001", "0000320193-26-000002"],
                    "filingDate": ["2026-02-01", "2026-02-02"],
                    "reportDate": ["2026-01-01", "2026-02-01"],
                    "primaryDocument": ["aapl-20260101.htm", "xslF345X05/doc4.xml"],
                }
            },
        },
    ]
    mock_request_text.return_value = """
    <ownershipDocument>
      <reportingOwner><reportingOwnerId><rptOwnerName>Jane Doe</rptOwnerName></reportingOwnerId></reportingOwner>
      <nonDerivativeTransaction>
        <securityTitle><value>Common Stock</value></securityTitle>
        <transactionDate><value>2026-02-01</value></transactionDate>
        <transactionCoding><transactionCode>P</transactionCode></transactionCoding>
        <transactionAmounts>
          <transactionShares><value>100</value></transactionShares>
          <transactionPricePerShare><value>200.00</value></transactionPricePerShare>
          <transactionAcquiredDisposedCode><value>A</value></transactionAcquiredDisposedCode>
        </transactionAmounts>
        <postTransactionAmounts><sharesOwnedFollowingTransaction><value>500</value></sharesOwnedFollowingTransaction></postTransactionAmounts>
        <ownershipNature><directOrIndirectOwnership><value>D</value></directOrIndirectOwnership></ownershipNature>
      </nonDerivativeTransaction>
    </ownershipDocument>
    """
    items = fetch_sec("run-1", "AAPL", 10)
    assert any(item.source == "SEC EDGAR Company Facts" for item in items)
    assert any(item.source == "SEC EDGAR Submissions" for item in items)
    filing = next(item for item in items if item.source == "SEC EDGAR Filing")
    assert filing.title == "10-K filing excerpt"
    assert filing.payload["extraction_status"]["state"] == "available"
    assert any(item.source == "SEC EDGAR Form 4" for item in items)
    form4 = next(item for item in items if item.source == "SEC EDGAR Form 4")
    assert form4.payload["transactions"][0]["owner"] == "Jane Doe"
    assert form4.payload["transactions"][0]["acquired_disposed"] == "A"


def test_fetch_sec_skips_taiwan_stock():
    items = fetch_sec("run-1", "2330.TW", 10)
    assert len(items) == 1
    assert items[0].title == "Connector skipped"


def test_fetch_sec_accepts_company_name():
    items = fetch_sec("run-1", "2330.TW", 10, company_name="台積電")
    assert len(items) == 1
    assert items[0].title == "Connector skipped"


def test_fetch_finnhub_accepts_company_name():
    with patch("trading_debate.connectors.finnhub.os.getenv", return_value=None):
        items = fetch_finnhub("run-1", "AAPL", 10, company_name="Apple")
    assert len(items) == 1
    assert items[0].title == "Connector skipped"


@patch("trading_debate.connectors.finmind.request_json")
@patch("trading_debate.connectors.finmind.os.getenv", return_value="fake-token")
def test_fetch_finmind_accepts_company_name(mock_getenv, mock_request):
    mock_request.return_value = {"status": 200, "data": []}
    items = fetch_finmind("run-1", "2330.TW", 10, company_name="台積電")
    assert not any(item.title == "Connector error" for item in items)


@patch("trading_debate.connectors.twse.request_json", return_value=[])
def test_fetch_twse_mops_accepts_company_name(mock_request):
    items = fetch_twse_mops("run-1", "2330.TW", 0, company_name="台積電")
    assert not any(item.title == "Connector error" for item in items)


@patch("trading_debate.connectors.market.request_json")
def test_fetch_official_valuation_data_returns_twse_snapshot(mock_request):
    mock_request.return_value = [
        {
            "Date": "1150805",
            "Code": "2330",
            "Name": "台積電",
            "PEratio": "20",
            "DividendYield": "1.2",
            "PBratio": "5.0",
        }
    ]

    items = fetch_official_valuation_data("run-1", "2330.TW", 10)

    assert len(items) == 1
    assert items[0].source == "TWSE Official Valuation Data"
    assert items[0].payload["dataset"] == "BWIBBU_ALL"
    assert items[0].payload["record"]["PEratio"] == "20"
    assert items[0].published_at == "1150805"


@patch("trading_debate.connectors.market.request_json")
def test_fetch_official_market_data_returns_twse_records(mock_request):
    def response(url):
        if "t187ap17" in url:
            return [{"公司代號": "2330", "毛利率": "58.0", "年度": "115"}]
        if "t187ap45" in url:
            return [{"公司代號": "2330", "現金股利總額": "100", "年度": "115"}]
        if "MI_MARGN" in url:
            return [{"股票代號": "2330", "融資今日餘額": "10", "Date": "1150805"}]
        return [{"Code": "2330", "Date": "1150805"}]

    mock_request.side_effect = response

    items = fetch_official_market_data("run-1", "2330.TW", 10)

    assert {item.payload["dataset"] for item in items} == {
        "valuation",
        "profitability",
        "dividend",
        "ex_right",
        "margin",
        "securities_lending",
    }
    assert all(item.payload["market"] == "twse" for item in items)
    assert all(item.source == "TWSE/TPEX Official Market Data" for item in items)
    assert any("TWT96U" in call.args[0] for call in mock_request.call_args_list)


@patch("trading_debate.connectors.market.request_json")
def test_fetch_official_market_data_routes_tpex_and_matches_tpex_code(mock_request):
    def response(url):
        if "tpex_3insti_qfii" in url:
            return [{"SecuritiesCompanyCode": "6488", "外資持股比率": "12"}]
        if "tpex_margin_sbl" in url:
            return [
                {
                    "TWSECode": "2330",
                    "GRETAICode": "6488",
                    "借券賣出當日餘額": "30",
                }
            ]
        return [{"SecuritiesCompanyCode": "6488", "Date": "1150805"}]

    mock_request.side_effect = response

    items = fetch_official_market_data("run-1", "6488.TWO", 10)

    assert len(items) == 10
    assert {item.payload["market"] for item in items} == {"tpex"}
    assert "foreign_ownership" in {item.payload["dataset"] for item in items}
    assert "securities_lending_balance" in {item.payload["dataset"] for item in items}
    assert all("www.tpex.org.tw" in item.url for item in items)


def test_fetch_official_market_data_skips_non_taiwan_symbol():
    items = fetch_official_market_data("run-1", "AAPL", 10)

    assert len(items) == 1
    assert items[0].title == "Connector skipped"


@patch("trading_debate.connectors.mops.request_text", return_value="")
@patch("trading_debate.connectors.mops.request_bytes", return_value=b"pdf")
@patch("trading_debate.connectors.mops.request_json")
def test_fetch_mops_documents_extracts_disclosed_pdf_text(
    mock_request, mock_bytes, mock_text
):
    mock_request.side_effect = [
        [
            {
                "公司代號": "2330",
                "主旨": "法人說明會",
                "發言日期": "1150805",
                "說明": "https://example.com/presentation.pdf",
            }
        ],
        [],
    ]
    fake_reader = SimpleNamespace(
        is_encrypted=False,
        pages=[SimpleNamespace(extract_text=lambda: "資本支出展望")],
    )
    with patch.dict(
        sys.modules, {"pypdf": SimpleNamespace(PdfReader=lambda _: fake_reader)}
    ):
        items = fetch_mops_documents("run-1", "2330.TW", 10)

    attachment = next(
        item for item in items if item.source == "MOPS Official Attachment"
    )
    assert attachment.payload["document"]["state"] == "available"
    assert attachment.payload["document"]["text"] == "資本支出展望"
    mock_bytes.assert_called_once_with("https://example.com/presentation.pdf")


@patch(
    "trading_debate.connectors.mops.request_text",
    return_value="<h1>合併現金流量表</h1>本資料由台積電公司提供 民國115年第1季",
)
@patch("trading_debate.connectors.mops.request_json", return_value=[])
def test_fetch_mops_documents_adds_official_cash_flow(mock_request, mock_text):
    items = fetch_mops_documents("run-1", "2330.TW", 10)

    cash_flow = next(
        item for item in items if item.source == "MOPS Official Financial Statements"
    )
    assert cash_flow.title == "Official Cash flow statement: 台積電"
    assert cash_flow.payload["period"] == "民國115年第1季"
    assert cash_flow.payload["form"] == "t164sb05"


def test_extract_pdf_text_marks_empty_document_without_inference():
    fake_reader = SimpleNamespace(
        is_encrypted=False,
        pages=[SimpleNamespace(extract_text=lambda: "")],
    )
    with patch.dict(
        sys.modules, {"pypdf": SimpleNamespace(PdfReader=lambda _: fake_reader)}
    ):
        result = _extract_pdf_text(b"pdf")
    assert result == {"state": "empty", "page_count": 1, "text": ""}
