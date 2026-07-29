"""Shared pytest fixtures and helpers for the trading_debate test suite."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

import trading_debate as td
from trading_debate.models import EvidenceItem, YahooFetchResult


def make_mock_ticker(has_data: bool):
    """Return a minimal yfinance Ticker mock for symbol resolution tests."""
    mock = MagicMock()
    if has_data:
        mock.get_info.return_value = {"longName": "Test Co", "currentPrice": 100.0}
    else:
        mock.get_info.return_value = {"trailingPegRatio": None}
    mock.history.return_value = MagicMock(empty=not has_data)
    return mock


def make_history(n: int = 250, start_price: float = 100.0, end_price: float = 150.0):
    """Generate a deterministic OHLCV DataFrame for technical indicator tests."""
    dates = pd.date_range(end=datetime(2026, 7, 28, tzinfo=UTC), periods=n, freq="D")
    base = [start_price + (end_price - start_price) * i / (n - 1) for i in range(n)]
    closes = pd.Series(
        [
            price + (1 if i % 2 == 0 else -1) * 0.5 * (1 + (i % 7) * 0.1)
            for i, price in enumerate(base)
        ],
        index=dates,
    )
    return pd.DataFrame(
        {
            "Open": closes - 0.5,
            "High": closes + 1.5,
            "Low": closes - 1.5,
            "Close": closes,
            "Volume": [1_000_000 + i * 1000 for i in range(n)],
        },
        index=dates,
    )


def make_yahoo_result(run_id: str, history, news=None) -> YahooFetchResult:
    """Build a YahooFetchResult matching what fetch_yahoo would produce."""
    info = {"shortName": "Apple Inc.", "currentPrice": 150.0}
    closes = pd.to_numeric(history.get("Close"), errors="coerce").dropna()
    price = {
        "as_of": str(history.index[-1].date()) if len(history) else None,
        "close": float(closes.iloc[-1]) if len(closes) else None,
        "return_1y": float(closes.iloc[-1] / closes.iloc[0] - 1)
        if len(closes) > 1
        else None,
        "high_1y": float(closes.max()) if len(closes) else None,
        "low_1y": float(closes.min()) if len(closes) else None,
    }
    technicals = td.compute_technicals(history)
    daily_history = td.history_to_records(history)
    items: list[EvidenceItem] = [
        EvidenceItem(
            run_id=run_id,
            source="Yahoo Finance",
            title="Fundamentals snapshot",
            payload=info,
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
            payload={"bars": len(daily_history), "records": daily_history},
            published_at=price["as_of"],
        ),
    ]
    for article in news or []:
        items.append(
            EvidenceItem(
                run_id=run_id,
                source="Yahoo Finance News",
                title=article.get("title", "News"),
                payload=article,
            )
        )
    return YahooFetchResult(
        items=items,
        fundamentals=info,
        price=price,
        technicals=technicals,
        stored_news=len(news or []),
    )


@pytest.fixture
def empty_connectors():
    """Run cmd_fetch with an empty CONNECTORS dict to skip external APIs."""
    with patch("trading_debate.cli.CONNECTORS", {}) as mock_connectors:
        yield mock_connectors
