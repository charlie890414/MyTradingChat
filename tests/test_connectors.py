"""Tests for external evidence connectors."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pandas as pd

from trading_debate.connectors.bing_news import fetch_bing_news
from trading_debate.connectors.finmind import fetch_finmind
from trading_debate.connectors.finnhub import fetch_finnhub
from trading_debate.connectors.google_news import fetch_google_news
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
        {"content": {"title": "News 1", "pubDate": "2026-01-01"}}
    ]

    result = fetch_yahoo("run-1", "AAPL", 10, ticker=mock_ticker)
    assert result.stored_news == 1
    assert result.price["close"] is not None
    assert len(result.items) >= 4
    assert any(item.source == "Yahoo Finance News" for item in result.items)
    daily = next(item for item in result.items if item.title == "Daily OHLCV history")
    assert daily.payload["price_adjustment"]
    assert any(item.title == "Weekly adjusted OHLCV history" for item in result.items)
    assert any(item.title == "Monthly adjusted OHLCV history" for item in result.items)


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
def test_fetch_google_news_uses_company_name_for_taiwan_symbol(mock_feedparser):
    mock_feedparser.parse.return_value = type(
        "Feed",
        (),
        {
            "entries": [
                {
                    "title": "Unimicron expands capacity",
                    "link": "https://example.com/1",
                    "published": "Mon, 28 Jul 2026 10:00:00 GMT",
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
def test_fetch_bing_news_uses_company_name_for_taiwan_symbol(mock_feedparser):
    mock_feedparser.parse.return_value = type(
        "Feed",
        (),
        {
            "entries": [
                {
                    "title": "Unimicron raises guidance",
                    "link": "https://example.com/1",
                    "published": "Mon, 28 Jul 2026 14:00:00 GMT",
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
    mock_request.side_effect = [
        [
            {
                "headline": "Finnhub article",
                "url": "https://example.com",
                "datetime": 1704067200,
            }
        ],
        {"metric": {"grossMarginTTM": 0.5}},
        [{"period": "2026-01-01", "actual": 1.2, "estimate": 1.1}],
        [{"period": "2026-01-01", "buy": 10, "hold": 2, "sell": 1}],
        {"targetMean": 200.0, "targetHigh": 220.0, "targetLow": 180.0},
        {"data": [{"period": "2026-03-31", "epsAvg": 1.3}]},
        {"data": [{"period": "2026-03-31", "revenueAvg": 100.0}]},
        {"data": [{"endDate": "2026-01-01", "report": {}}]},
    ]
    items = fetch_finnhub("run-1", "AAPL", 10)
    assert any(item.source == "Finnhub Company News" for item in items)
    assert any(item.source == "Finnhub Basic Financials" for item in items)
    assert any(item.source == "Finnhub Earnings" for item in items)
    assert any(item.source == "Finnhub Recommendation Trends" for item in items)
    assert any(item.source == "Finnhub Price Targets" for item in items)
    assert any(item.source == "Finnhub EPS Estimates" for item in items)
    assert any(item.source == "Finnhub Revenue Estimates" for item in items)
    assert any(item.source == "Finnhub Financials As Reported" for item in items)


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
    mock_request.side_effect = [
        {
            "status": 200,
            "data": [
                {
                    "title": "Taiwan news",
                    "link": "https://example.com",
                    "date": "2026-01-01",
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
def test_fetch_twse_mops_returns_profile_for_taiwan_code(mock_request):
    mock_request.return_value = [
        {"公司代號": "2330", "公司名稱": "TSMC", "產業別": "半導體"}
    ]
    items = fetch_twse_mops("run-1", "2330.TW", 0)
    assert any(item.source == "TWSE OpenAPI / MOPS" for item in items)
    assert any(item.title.startswith("Official Income statement") for item in items)
    assert any(item.title.startswith("Official Balance sheet") for item in items)


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
