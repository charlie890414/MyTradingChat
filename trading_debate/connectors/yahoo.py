"""Yahoo Finance connector: fundamentals, prices, news, and technicals."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import yfinance

from ..models import EvidenceItem, YahooFetchResult
from ..symbols import normalize_symbol
from ..utils import is_recent_news
from .technicals import _series, compute_technicals, history_to_records, resample_ohlcv


def scalar(value: Any) -> Any:
    try:
        return value.item() if hasattr(value, "item") else value
    except ValueError:
        return str(value)


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
    ticker = ticker if ticker is not None else yfinance.Ticker(symbol)
    end = datetime.now(UTC).date()
    start = end - timedelta(days=365)
    info = ticker.get_info()
    history = ticker.history(start=start, end=end, interval="1d", auto_adjust=True)
    news = ticker.get_news(count=news_limit, tab="news")
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
    stored_news = 0
    for item in news or []:
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
