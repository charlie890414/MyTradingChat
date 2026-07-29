"""Alpha Vantage News & Sentiment connector."""

from __future__ import annotations

import os

from ..models import EvidenceItem
from ..symbols import taiwan_code
from ..utils import request_json


def fetch_alpha_vantage(run_id: str, symbol: str, limit: int) -> list[EvidenceItem]:
    if taiwan_code(symbol):
        return [
            EvidenceItem(
                run_id=run_id,
                source="Alpha Vantage",
                title="Connector skipped",
                payload={
                    "state": "skipped",
                    "detail": "Alpha Vantage NEWS_SENTIMENT only supports US tickers.",
                },
            )
        ]
    key = os.getenv("ALPHA_VANTAGE_API_KEY")
    if not key:
        return [
            EvidenceItem(
                run_id=run_id,
                source="Alpha Vantage",
                title="Connector skipped",
                payload={
                    "state": "skipped",
                    "detail": "Set ALPHA_VANTAGE_API_KEY to enable NEWS_SENTIMENT.",
                },
            )
        ]
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
    items: list[EvidenceItem] = []
    for article in data.get("feed", []):
        items.append(
            EvidenceItem(
                run_id=run_id,
                source="Alpha Vantage News & Sentiment",
                title=article.get("title", "Untitled article"),
                payload=article,
                url=article.get("url"),
                published_at=article.get("time_published"),
            )
        )
    return items
