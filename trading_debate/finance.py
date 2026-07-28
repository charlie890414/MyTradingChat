"""Evidence fetching: yfinance fundamentals, prices, news, and external connectors."""

from __future__ import annotations

import base64
import os
import re
from datetime import UTC, datetime, timedelta
from typing import Any

import yfinance  # noqa: F401  exposed at module level so tests can patch trading_debate.finance.yfinance.Ticker

from .db import connector_status, insert_evidence
from .utils import request_json


def taiwan_code(symbol: str) -> str | None:
    match = re.fullmatch(r"(\d{4,6})(?:\.(?:TW|TWO))?", symbol.upper())
    return match.group(1) if match else None


def scalar(value: Any) -> Any:
    try:
        return value.item() if hasattr(value, "item") else value
    except ValueError:
        return str(value)


def fetch_alpha_vantage(con: Any, run_id: str, symbol: str, limit: int) -> int:
    key = os.getenv("ALPHA_VANTAGE_API_KEY")
    if not key:
        connector_status(
            con,
            run_id,
            "Alpha Vantage",
            "skipped",
            "Set ALPHA_VANTAGE_API_KEY to enable NEWS_SENTIMENT.",
        )
        return 0
    data = request_json(
        "https://www.alphavantage.co/query",
        {
            "function": "NEWS_SENTIMENT",
            "tickers": symbol,
            "limit": limit,
            "apikey": key,
        },
    )
    if "Error Message" in data or "Information" in data:
        raise RuntimeError(data.get("Error Message") or data.get("Information"))
    for article in data.get("feed", []):
        insert_evidence(
            con,
            run_id,
            "Alpha Vantage News & Sentiment",
            article.get("title", "Untitled article"),
            article,
            url=article.get("url"),
            published_at=article.get("time_published"),
        )
    return len(data.get("feed", []))


def fetch_finnhub(con: Any, run_id: str, symbol: str, limit: int) -> int:
    key = os.getenv("FINNHUB_API_KEY")
    if not key:
        connector_status(
            con,
            run_id,
            "Finnhub",
            "skipped",
            "Set FINNHUB_API_KEY to enable company news.",
        )
        return 0
    end = datetime.now(UTC).date()
    start = end - timedelta(days=365)
    items = request_json(
        "https://finnhub.io/api/v1/company-news",
        {
            "symbol": symbol,
            "from": start.isoformat(),
            "to": end.isoformat(),
            "token": key,
        },
    )
    if isinstance(items, dict) and items.get("error"):
        raise RuntimeError(items["error"])
    for article in (items or [])[:limit]:
        insert_evidence(
            con,
            run_id,
            "Finnhub Company News",
            article.get("headline", "Untitled article"),
            article,
            url=article.get("url"),
            published_at=str(article.get("datetime") or ""),
        )
    return len((items or [])[:limit])


def fetch_finmind(con: Any, run_id: str, symbol: str, limit: int) -> int:
    code = taiwan_code(symbol)
    if not code:
        connector_status(
            con,
            run_id,
            "FinMind",
            "skipped",
            "FinMind TaiwanStockNews is only queried for Taiwan ticker codes.",
        )
        return 0
    end = datetime.now(UTC).date()
    data = request_json(
        "https://api.finmindtrade.com/api/v4/data",
        {
            "dataset": "TaiwanStockNews",
            "data_id": code,
            "start_date": (end - timedelta(days=365)).isoformat(),
            "end_date": end.isoformat(),
            "token": os.getenv("FINMIND_TOKEN"),
        },
    )
    if data.get("status") not in (200, "200"):
        raise RuntimeError(data.get("msg") or data.get("message") or str(data))
    items = data.get("data", [])
    for article in items[-limit:]:
        insert_evidence(
            con,
            run_id,
            "FinMind TaiwanStockNews",
            article.get("title") or article.get("headline") or "Taiwan stock news",
            article,
            url=article.get("link") or article.get("url"),
            published_at=str(article.get("date") or ""),
        )
    return len(items[-limit:])


def fetch_twse_mops(con: Any, run_id: str, symbol: str, limit: int = 0) -> int:
    code = taiwan_code(symbol)
    if not code:
        connector_status(
            con,
            run_id,
            "TWSE OpenAPI / MOPS",
            "skipped",
            "Official disclosures are only queried for Taiwan ticker codes.",
        )
        return 0
    records = request_json("https://openapi.twse.com.tw/v1/opendata/t187ap04_L")
    profile = next(
        (item for item in records if str(item.get("公司代號", "")).strip() == code),
        None,
    )
    if not profile:
        connector_status(
            con,
            run_id,
            "TWSE OpenAPI / MOPS",
            "empty",
            f"No listed-company profile found for {code}.",
        )
        return 0
    insert_evidence(
        con,
        run_id,
        "TWSE OpenAPI / MOPS",
        "Official listed-company disclosure profile",
        profile,
        url="https://openapi.twse.com.tw/v1/opendata/t187ap04_L",
    )
    return 1


def fetch_reddit_summary(con: Any, run_id: str, symbol: str, limit: int) -> int:
    client_id, secret = os.getenv("REDDIT_CLIENT_ID"), os.getenv("REDDIT_CLIENT_SECRET")
    if not client_id or not secret:
        connector_status(
            con,
            run_id,
            "Reddit",
            "skipped",
            "Set REDDIT_CLIENT_ID and REDDIT_CLIENT_SECRET for official OAuth access.",
        )
        return 0
    token_data = request_json(
        "https://www.reddit.com/api/v1/access_token",
        headers={
            "Authorization": "Basic "
            + base64.b64encode(f"{client_id}:{secret}".encode()).decode(),
            "Content-Type": "application/x-www-form-urlencoded",
        },
        method="POST",
        body=b"grant_type=client_credentials",
    )
    token = token_data.get("access_token")
    if not token:
        raise RuntimeError(
            token_data.get("error") or "Reddit OAuth token was not returned"
        )
    listing = request_json(
        "https://oauth.reddit.com/search",
        {"q": symbol, "sort": "new", "limit": limit, "type": "link"},
        headers={"Authorization": f"Bearer {token}"},
    )
    posts = listing.get("data", {}).get("children", [])
    aggregate = {
        "query": symbol,
        "post_count": len(posts),
        "score_total": sum(item.get("data", {}).get("score", 0) for item in posts),
        "comment_total": sum(
            item.get("data", {}).get("num_comments", 0) for item in posts
        ),
        "sample_urls": [
            "https://reddit.com" + item.get("data", {}).get("permalink", "")
            for item in posts
        ],
    }
    insert_evidence(
        con,
        run_id,
        "Reddit public-discussion proxy",
        "OAuth search aggregate (no post bodies retained)",
        aggregate,
    )
    return len(posts)


def fetch_yahoo(
    con: Any,
    run_id: str,
    symbol: str,
    news_limit: int,
    *,
    ticker: Any | None = None,
) -> dict[str, Any]:
    """Fetch fundamentals, price snapshot, and news for ``symbol``.

    ``ticker`` is injected for tests; in production we lazily import yfinance.
    """
    import yfinance as yf

    ticker = ticker if ticker is not None else yf.Ticker(symbol)
    end = datetime.now(UTC).date()
    start = end - timedelta(days=365)
    info = ticker.get_info()
    history = ticker.history(start=start, end=end, auto_adjust=False)
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
    closes = history["Close"].dropna() if "Close" in history else []
    price = {
        "as_of": str(history.index[-1].date()) if len(history) else None,
        "close": float(closes.iloc[-1]) if len(closes) else None,
        "return_1y": float(closes.iloc[-1] / closes.iloc[0] - 1)
        if len(closes) > 1
        else None,
        "high_1y": float(closes.max()) if len(closes) else None,
        "low_1y": float(closes.min()) if len(closes) else None,
    }
    con.execute("DELETE FROM evidence WHERE run_id = ?", (run_id,))
    insert_evidence(con, run_id, "Yahoo Finance", "Fundamentals snapshot", fundamentals)
    insert_evidence(
        con,
        run_id,
        "Yahoo Finance",
        "One-year price snapshot",
        price,
        published_at=price["as_of"],
    )
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
        insert_evidence(
            con,
            run_id,
            "Yahoo Finance News",
            title,
            item,
            url=url,
            published_at=str(published) if published else None,
        )
        stored_news += 1
    return {
        "fundamentals": fundamentals,
        "price": price,
        "stored_news": stored_news,
        "ticker": ticker,
    }


CONNECTORS: dict[str, Any] = {
    "Alpha Vantage": fetch_alpha_vantage,
    "Finnhub": fetch_finnhub,
    "FinMind": fetch_finmind,
    "TWSE OpenAPI / MOPS": fetch_twse_mops,
    "Reddit": fetch_reddit_summary,
}
