"""Evidence fetching: yfinance fundamentals, prices, news, and external connectors."""

from __future__ import annotations

import base64
import os
import re
from datetime import UTC, datetime, timedelta
from typing import Any

import numpy as np
import pandas as pd
import yfinance  # noqa: F401  exposed at module level so tests can patch trading_debate.finance.yfinance.Ticker

from .db import connector_status, insert_evidence
from .utils import request_json


def taiwan_code(symbol: str) -> str | None:
    match = re.fullmatch(r"(\d{4,6})(?:\.(?:TW|TWO))?", symbol.upper())
    return match.group(1) if match else None


def normalize_symbol(symbol: str) -> str:
    """Return a Yahoo-Finance-compatible symbol.

    Bare Taiwan numeric codes (e.g. ``3037``) are suffixed with ``.TW``;
    codes already ending in ``.TW`` or ``.TWO`` are left unchanged.
    US-style tickers are returned upper-cased.
    """
    code = taiwan_code(symbol)
    if code and not re.search(r"\.(?:TW|TWO)$", symbol, re.IGNORECASE):
        return f"{code}.TW"
    return symbol.upper()


def _ticker_has_data(ticker: Any) -> bool:
    """Return True if a yfinance Ticker looks like it resolved to a real security."""
    try:
        info = ticker.get_info()
    except Exception:  # pragma: no cover - defensive, yfinance raises on network errors
        return False
    if not info:
        return False
    # Yahoo returns a nearly-empty dict for invalid symbols (often just trailingPegRatio).
    if set(info.keys()) <= {"trailingPegRatio"}:
        return False
    # A usable security usually has a name or a price.
    if info.get("longName") or info.get("shortName") or info.get("currentPrice"):
        return True
    # Some valid tickers only have price history without a full info profile.
    try:
        history = ticker.history(period="5d")
    except Exception:  # pragma: no cover
        return False
    return history is not None and not history.empty


def resolve_taiwan_yahoo_symbol(symbol: str) -> str:
    """Resolve a Taiwan numeric code to the Yahoo Finance suffix that has data.

    For a numeric code with or without a suffix (e.g. ``6841`` or ``6841.TW``),
    try ``.TW`` first; if Yahoo has no data, fall back to ``.TWO``. This covers
    both listed/OTC and some emerging board stocks that Yahoo indexes. If neither
    resolves, return the ``.TW`` form so the downstream failure is explicit.
    US-style tickers are returned unchanged.
    """
    code = taiwan_code(symbol)
    if not code:
        return symbol.upper()

    import yfinance as yf

    candidates = [f"{code}.TW", f"{code}.TWO"]
    for candidate in candidates:
        try:
            if _ticker_has_data(yf.Ticker(candidate)):
                return candidate
        except Exception:  # pragma: no cover - network/provider errors
            continue
    return candidates[0]


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


def _series(series: pd.Series | None) -> pd.Series:
    if series is None:
        return pd.Series(dtype=float)
    return pd.to_numeric(series, errors="coerce").dropna()


def _ema(series: pd.Series, span: int) -> pd.Series:
    return series.ewm(span=span, adjust=False).mean()


def _rsi(closes: pd.Series, period: int = 14) -> float | None:
    if len(closes) <= period:
        return None
    delta = closes.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1 / period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / period, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    rsi = 100 - 100 / (1 + rs)
    return float(rsi.iloc[-1])


def compute_technicals(history: pd.DataFrame) -> dict[str, Any]:
    """Derive common technical indicators from a daily OHLCV frame.

    The frame is the raw output of ``yfinance.Ticker.history(...)`` and must
    contain ``Open``, ``High``, ``Low``, ``Close`` and ``Volume`` columns.
    """
    if history is None or history.empty:
        return {"available": False, "reason": "no daily OHLCV returned"}

    closes = _series(history.get("Close"))
    highs = _series(history.get("High"))
    lows = _series(history.get("Low"))
    volumes = _series(history.get("Volume"))

    if closes.empty:
        return {"available": False, "reason": "Close column empty"}

    ema12 = _ema(closes, 12)
    ema26 = _ema(closes, 26)
    macd_line = ema12 - ema26
    macd_signal = _ema(macd_line, 9)
    macd_hist = macd_line - macd_signal

    sma20 = closes.rolling(20).mean()
    std20 = closes.rolling(20).std()

    indicators: dict[str, Any] = {
        "available": True,
        "bars": int(len(closes)),
        "as_of": str(closes.index[-1].date()),
        "close": float(closes.iloc[-1]),
        "ma_50": float(closes.tail(50).mean()) if len(closes) >= 50 else None,
        "ma_200": float(closes.tail(200).mean()) if len(closes) >= 200 else None,
        "ema_20": float(closes.ewm(span=20, adjust=False).mean().iloc[-1]),
        "rsi_14": _rsi(closes, 14),
        "macd": {
            "line": float(macd_line.iloc[-1]) if len(macd_line) else None,
            "signal": float(macd_signal.iloc[-1]) if len(macd_signal) else None,
            "histogram": float(macd_hist.iloc[-1]) if len(macd_hist) else None,
        },
        "bollinger_20_2": {
            "middle": float(sma20.iloc[-1]) if len(sma20) else None,
            "upper": float((sma20 + 2 * std20).iloc[-1]) if len(sma20) else None,
            "lower": float((sma20 - 2 * std20).iloc[-1]) if len(sma20) else None,
        },
        "high_52w": float(highs.tail(252).max()) if len(highs) else None,
        "low_52w": float(lows.tail(252).min()) if len(lows) else None,
        "avg_volume_20d": (
            float(volumes.tail(20).mean()) if len(volumes) >= 20 else None
        ),
        "volume_trend_20d_vs_60d": (
            float(volumes.tail(20).mean() / volumes.tail(60).mean())
            if len(volumes) >= 60
            else None
        ),
        "kdj_k": None,
        "kdj_d": None,
        "kdj_j": None,
        "volume_price_structure": {
            "up_days_20d": int(((closes.diff().tail(20)) > 0).sum()),
            "down_days_20d": int(((closes.diff().tail(20)) < 0).sum()),
            "avg_range_pct_20d": (
                float(((highs - lows) / closes).tail(20).mean())
                if len(closes) >= 20 and (highs > 0).all()
                else None
            ),
        },
    }

    if len(highs) >= 9 and len(lows) >= 9:
        low_n = lows.rolling(9).min()
        high_n = highs.rolling(9).max()
        rsv = ((closes - low_n) / (high_n - low_n).replace(0, np.nan)) * 100
        k = rsv.ewm(alpha=1 / 3, adjust=False).mean()
        d = k.ewm(alpha=1 / 3, adjust=False).mean()
        j = 3 * k - 2 * d
        indicators["kdj_k"] = float(k.iloc[-1])
        indicators["kdj_d"] = float(d.iloc[-1])
        indicators["kdj_j"] = float(j.iloc[-1])

    support_resistance = _support_resistance(closes, highs, lows)
    indicators["support_resistance"] = support_resistance
    return indicators


def _support_resistance(
    closes: pd.Series, highs: pd.Series, lows: pd.Series, window: int = 20
) -> dict[str, Any]:
    if len(closes) < window * 2:
        return {"support": None, "resistance": None}
    recent_highs = highs.tail(window).max()
    recent_lows = lows.tail(window).min()
    pivots = closes.rolling(window).mean().dropna()
    if pivots.empty:
        return {"support": None, "resistance": None}
    return {
        "support": float(recent_lows),
        "resistance": float(recent_highs),
        "pivot_avg": float(pivots.iloc[-1]),
    }


def history_to_records(history: pd.DataFrame) -> list[dict[str, Any]]:
    """Convert the OHLCV frame into a JSON-friendly list of daily bars."""
    if history is None or history.empty:
        return []
    frame = history.reset_index()
    date_col = frame.columns[0]
    records = []
    for _, row in frame.iterrows():
        record: dict[str, Any] = {"date": str(row[date_col].date())}
        for col in ("Open", "High", "Low", "Close", "Volume"):
            if col in frame.columns:
                value = row[col]
                record[col.lower()] = None if pd.isna(value) else float(value)
        records.append(record)
    return records


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
    insert_evidence(
        con,
        run_id,
        "Yahoo Finance",
        "Technical indicators (from daily OHLCV)",
        technicals,
        published_at=technicals.get("as_of"),
    )
    insert_evidence(
        con,
        run_id,
        "Yahoo Finance",
        "Daily OHLCV history",
        {"bars": len(daily_history), "records": daily_history},
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
        "technicals": technicals,
        "ticker": ticker,
    }


CONNECTORS: dict[str, Any] = {
    "Alpha Vantage": fetch_alpha_vantage,
    "Finnhub": fetch_finnhub,
    "FinMind": fetch_finmind,
    "TWSE OpenAPI / MOPS": fetch_twse_mops,
    "Reddit": fetch_reddit_summary,
}
