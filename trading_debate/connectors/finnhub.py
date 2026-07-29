"""Finnhub company news connector."""

from __future__ import annotations

import os

from ..models import EvidenceItem
from ..symbols import taiwan_code
from ..utils import date_range_days, request_json


def fetch_finnhub(run_id: str, symbol: str, limit: int) -> list[EvidenceItem]:
    if taiwan_code(symbol):
        return [
            EvidenceItem(
                run_id=run_id,
                source="Finnhub",
                title="Connector skipped",
                payload={
                    "state": "skipped",
                    "detail": "Finnhub company news only supports US tickers.",
                },
            )
        ]
    key = os.getenv("FINNHUB_API_KEY")
    if not key:
        return [
            EvidenceItem(
                run_id=run_id,
                source="Finnhub",
                title="Connector skipped",
                payload={
                    "state": "skipped",
                    "detail": "Set FINNHUB_API_KEY to enable company news.",
                },
            )
        ]
    start, end = date_range_days(365)
    items = request_json(
        "https://finnhub.io/api/v1/company-news",
        {
            "symbol": symbol,
            "from": start,
            "to": end,
            "token": key,
        },
    )
    if isinstance(items, dict) and items.get("error"):
        raise RuntimeError(items["error"])
    result: list[EvidenceItem] = []
    for article in (items or [])[:limit]:
        result.append(
            EvidenceItem(
                run_id=run_id,
                source="Finnhub Company News",
                title=article.get("headline", "Untitled article"),
                payload=article,
                url=article.get("url"),
                published_at=str(article.get("datetime") or ""),
            )
        )
    return result
