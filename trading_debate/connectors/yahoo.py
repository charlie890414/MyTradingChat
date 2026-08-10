"""Yahoo Finance connector: fundamentals, prices, news, and technicals."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import pandas as pd
import yfinance
from yfinance.utils import YfConfig

from ..models import EvidenceItem, YahooFetchResult
from ..symbols import normalize_symbol
from ..utils import is_recent_news
from .technicals import _series, compute_technicals, history_to_records, resample_ohlcv

_RETRY_TOTAL = 3
_FINANCIAL_PERIODS = 4


def _enable_retries() -> None:
    """Enable yfinance's built-in exponential-backoff retry loop.

    yfinance defaults to no retries; its data layer retries transient errors
    with ``sleep(2 ** attempt)`` when configured. We raise the budget while
    keeping its default browser-impersonating session (a plain requests
    session gets rate-limited by Yahoo).
    """
    YfConfig.network.retries = max(int(YfConfig.network.retries or 0), _RETRY_TOTAL)


def scalar(value: Any) -> Any:
    try:
        return value.item() if hasattr(value, "item") else value
    except ValueError:
        return str(value)


def _payload_value(value: Any) -> Any:
    """Convert numpy/pandas scalars and dates into JSON-friendly values."""
    if isinstance(value, pd.Timestamp):
        return value.isoformat()
    if hasattr(value, "item"):
        try:
            value = value.item()
        except ValueError:
            return str(value)
    if isinstance(value, float) and value != value:  # NaN
        return None
    return value


def _frame_payload(
    frame: pd.DataFrame | pd.Series | dict | None,
    *,
    periods: int | None = None,
) -> dict[str, Any] | None:
    """Compact a DataFrame/dict into a JSON-friendly extra payload."""
    if frame is None:
        return None
    if isinstance(frame, dict):
        if not frame:
            return None
        return {
            str(key): _payload_value(value)
            for key, value in frame.items()
            if _payload_value(value) is not None
        }
    if isinstance(frame, pd.Series):
        if frame.empty:
            return None
        return {
            str(index): _payload_value(value)
            for index, value in frame.items()
            if _payload_value(value) is not None
        }
    if frame.empty:
        return None
    records = frame.reset_index()
    if periods is not None and len(records) > periods:
        records = records.tail(periods)
    rows: list[dict[str, Any]] = []
    for record in records.to_dict("records"):
        row: dict[str, Any] = {}
        for key, value in record.items():
            converted = _payload_value(value)
            if converted is None:
                continue
            row[str(key)] = converted
        rows.append(row)
    return {"rows": rows}


def fetch_yahoo(
    run_id: str,
    symbol: str,
    news_limit: int,
    *,
    ticker: Any | None = None,
) -> YahooFetchResult:
    """Fetch fundamentals, price snapshot, and news for ``symbol``.

    ``ticker`` is injected for tests; in production we lazily import yfinance.
    """
    symbol = normalize_symbol(symbol)
    if ticker is not None:
        yf_ticker = ticker
    else:
        _enable_retries()
        yf_ticker = yfinance.Ticker(symbol)
    end = datetime.now(UTC).date()
    start = end - timedelta(days=365)
    info = yf_ticker.get_info()
    history = yf_ticker.history(start=start, end=end, interval="1d", auto_adjust=True)
    news = yf_ticker.get_news(count=news_limit, tab="news")
    fields = [
        "shortName",
        "longName",
        "currency",
        "exchange",
        "sector",
        "industry",
        "marketCap",
        "trailingPE",
        "forwardPE",
        "priceToBook",
        "dividendYield",
        "returnOnEquity",
        "revenueGrowth",
        "earningsGrowth",
        "totalRevenue",
        "freeCashflow",
        "debtToEquity",
        "currentPrice",
        "targetMeanPrice",
        "recommendationKey",
    ]
    fundamentals = {
        key: scalar(info.get(key)) for key in fields if info.get(key) is not None
    }
    closes = _series(history.get("Close"))
    price = {
        "as_of": str(history.index[-1].date()) if len(history) else None,
        "close": float(closes.iloc[-1]) if len(closes) else None,
        "return_1y": float(closes.iloc[-1] / closes.iloc[0] - 1)
        if len(closes) > 1
        else None,
        "high_1y": float(closes.max()) if len(closes) else None,
        "low_1y": float(closes.min()) if len(closes) else None,
    }
    technicals = compute_technicals(history)
    daily_history = history_to_records(history)
    weekly_history = history_to_records(resample_ohlcv(history, "W-FRI"))
    monthly_history = history_to_records(resample_ohlcv(history, "ME"))

    items: list[EvidenceItem] = [
        EvidenceItem(
            run_id=run_id,
            source="Yahoo Finance",
            title="Fundamentals snapshot",
            payload=fundamentals,
        ),
        EvidenceItem(
            run_id=run_id,
            source="Yahoo Finance",
            title="One-year price snapshot",
            payload=price,
            published_at=price["as_of"],
        ),
        EvidenceItem(
            run_id=run_id,
            source="Yahoo Finance",
            title="Technical indicators (from daily OHLCV)",
            payload=technicals,
            published_at=technicals.get("as_of"),
        ),
        EvidenceItem(
            run_id=run_id,
            source="Yahoo Finance",
            title="Daily OHLCV history",
            payload={
                "bars": len(daily_history),
                "price_adjustment": (
                    "Yahoo Finance auto_adjust=True; prices are adjusted for "
                    "splits and dividends."
                ),
                "records": daily_history,
            },
            published_at=price["as_of"],
        ),
        EvidenceItem(
            run_id=run_id,
            source="Yahoo Finance",
            title="Weekly adjusted OHLCV history",
            payload={
                "bars": len(weekly_history),
                "frequency": "W-FRI",
                "records": weekly_history,
            },
            published_at=price["as_of"],
        ),
        EvidenceItem(
            run_id=run_id,
            source="Yahoo Finance",
            title="Monthly adjusted OHLCV history",
            payload={
                "bars": len(monthly_history),
                "frequency": "ME",
                "records": monthly_history,
            },
            published_at=price["as_of"],
        ),
    ]

    items.extend(_analyst_items(run_id, symbol, yf_ticker))
    items.extend(_statement_items(run_id, symbol, yf_ticker))
    items.extend(_event_items(run_id, symbol, yf_ticker))
    items.extend(_ownership_items(run_id, symbol, yf_ticker))

    stored_news = 0
    for item in (news or [])[:news_limit]:
        content = item.get("content", item)
        title = (
            content.get("title") or item.get("title") or "Untitled Yahoo Finance item"
        )
        url = content.get("canonicalUrl", {}).get("url") or content.get(
            "clickThroughUrl", {}
        ).get("url")
        published = content.get("pubDate") or item.get("providerPublishTime")
        if not is_recent_news(published):
            continue
        items.append(
            EvidenceItem(
                run_id=run_id,
                source="Yahoo Finance News",
                title=title,
                payload=item,
                url=url,
                published_at=str(published) if published else None,
            )
        )
        stored_news += 1
    return YahooFetchResult(
        items=items,
        fundamentals=fundamentals,
        price=price,
        technicals=technicals,
        stored_news=stored_news,
    )


def _analyst_items(run_id: str, symbol: str, ticker: Any) -> list[EvidenceItem]:
    items: list[EvidenceItem] = []
    items.extend(_analyst_estimate_items(run_id, symbol, ticker))
    items.extend(_price_target_items(run_id, symbol, ticker))
    items.extend(_recommendation_items(run_id, symbol, ticker))
    return items


def _event_items(run_id: str, symbol: str, ticker: Any) -> list[EvidenceItem]:
    items: list[EvidenceItem] = []
    items.extend(_calendar_items(run_id, symbol, ticker))
    items.extend(_corporate_action_items(run_id, symbol, ticker))
    return items


def _analyst_estimate_items(
    run_id: str, symbol: str, ticker: Any
) -> list[EvidenceItem]:
    payload: dict[str, Any] = {"symbol": symbol}
    sources = (
        ("earnings_estimate", ticker.get_earnings_estimate),
        ("revenue_estimate", ticker.get_revenue_estimate),
        ("growth_estimates", ticker.get_growth_estimates),
        ("eps_trend", ticker.get_eps_trend),
        ("eps_revisions", ticker.get_eps_revisions),
    )
    for key, getter in sources:
        try:
            value = _frame_payload(getter())
        except Exception:
            continue
        if value is not None:
            payload[key] = value
    if len(payload) == 1:
        return []
    return [
        EvidenceItem(
            run_id=run_id,
            source="Yahoo Finance Analyst",
            title="Analyst estimates (EPS, revenue, growth; trend & revisions)",
            payload=payload,
        )
    ]


def _price_target_items(run_id: str, symbol: str, ticker: Any) -> list[EvidenceItem]:
    try:
        targets = ticker.get_analyst_price_targets()
    except Exception:
        return []
    payload = _frame_payload(targets)
    if payload is None:
        return []
    return [
        EvidenceItem(
            run_id=run_id,
            source="Yahoo Finance Analyst",
            title="Analyst price targets",
            payload={"symbol": symbol, "data": payload},
        )
    ]


def _recommendation_items(run_id: str, symbol: str, ticker: Any) -> list[EvidenceItem]:
    try:
        recommendations = _frame_payload(ticker.get_recommendations())
    except Exception:
        return []
    if recommendations is None:
        return []
    return [
        EvidenceItem(
            run_id=run_id,
            source="Yahoo Finance Analyst",
            title="Analyst recommendations",
            payload={"symbol": symbol, "data": recommendations},
        )
    ]


def _statement_items(run_id: str, symbol: str, ticker: Any) -> list[EvidenceItem]:
    statements = (
        ("Income statement", ticker.get_income_stmt),
        ("Balance sheet", ticker.get_balance_sheet),
        ("Cash flow statement", ticker.get_cash_flow),
    )
    items: list[EvidenceItem] = []
    for title, getter in statements:
        try:
            frame = getter(freq="quarterly")
        except Exception:
            continue
        payload = _frame_payload(frame, periods=_FINANCIAL_PERIODS)
        if payload is None:
            continue
        items.append(
            EvidenceItem(
                run_id=run_id,
                source="Yahoo Finance Financials",
                title=f"{title} (trailing {_FINANCIAL_PERIODS} quarters)",
                payload={"symbol": symbol, "data": payload},
            )
        )
    return items


def _calendar_items(run_id: str, symbol: str, ticker: Any) -> list[EvidenceItem]:
    payload: dict[str, Any] = {"symbol": symbol}
    try:
        calendar = _frame_payload(ticker.get_calendar())
    except Exception:
        calendar = None
    if calendar is not None:
        payload["calendar"] = calendar
    try:
        dates = _frame_payload(ticker.get_earnings_dates())
    except Exception:
        dates = None
    if dates is not None:
        payload["earnings_dates"] = dates
    if len(payload) == 1:
        return []
    return [
        EvidenceItem(
            run_id=run_id,
            source="Yahoo Finance",
            title="Earnings calendar & dates",
            payload=payload,
        )
    ]


def _corporate_action_items(
    run_id: str, symbol: str, ticker: Any
) -> list[EvidenceItem]:
    payload: dict[str, Any] = {"symbol": symbol}
    for key, getter in (
        ("dividends", ticker.get_dividends),
        ("splits", ticker.get_splits),
    ):
        try:
            value = _frame_payload(getter())
        except Exception:
            continue
        if value is not None:
            payload[key] = value
    if len(payload) == 1:
        return []
    return [
        EvidenceItem(
            run_id=run_id,
            source="Yahoo Finance",
            title="Dividends & splits history",
            payload=payload,
        )
    ]


def _ownership_items(run_id: str, symbol: str, ticker: Any) -> list[EvidenceItem]:
    items: list[EvidenceItem] = []
    try:
        holders = _frame_payload(ticker.get_institutional_holders())
    except Exception:
        holders = None
    if holders is not None:
        items.append(
            EvidenceItem(
                run_id=run_id,
                source="Yahoo Finance Ownership",
                title="Institutional holders",
                payload={"symbol": symbol, "data": holders},
            )
        )
    payload: dict[str, Any] = {"symbol": symbol}
    for key, getter in (
        ("purchases", ticker.get_insider_purchases),
        ("transactions", ticker.get_insider_transactions),
    ):
        try:
            value = _frame_payload(getter())
        except Exception:
            continue
        if value is not None:
            payload[key] = value
    if len(payload) > 1:
        items.append(
            EvidenceItem(
                run_id=run_id,
                source="Yahoo Finance Ownership",
                title="Insider purchases & transactions",
                payload=payload,
            )
        )
    return items
