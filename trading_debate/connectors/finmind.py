"""FinMind Taiwan stock news connector."""

from __future__ import annotations

import os

from ..models import EvidenceItem
from ..symbols import taiwan_code
from ..utils import date_range_days, request_json


def fetch_finmind(run_id: str, symbol: str, limit: int) -> list[EvidenceItem]:
    code = taiwan_code(symbol)
    if not code:
        detail = "FinMind TaiwanStockNews is only queried for Taiwan ticker codes."
        return [
            EvidenceItem(
                run_id=run_id,
                source="FinMind",
                title="Connector skipped",
                payload={"state": "skipped", "detail": detail},
            )
        ]
    start, _end = date_range_days(365)
    headers = {}
    token = os.getenv("FINMIND_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    data = request_json(
        "https://api.finmindtrade.com/api/v4/data",
        {
            "dataset": "TaiwanStockNews",
            "data_id": code,
            "start_date": start,
        },
        headers=headers,
    )
    if data.get("status") not in (200, "200"):
        raise RuntimeError(data.get("msg") or data.get("message") or str(data))
    items = data.get("data", [])
    result: list[EvidenceItem] = []
    for article in items[-limit:]:
        title = article.get("title") or article.get("headline") or "Taiwan stock news"
        result.append(
            EvidenceItem(
                run_id=run_id,
                source="FinMind TaiwanStockNews",
                title=title,
                payload=article,
                url=article.get("link") or article.get("url"),
                published_at=str(article.get("date") or ""),
            )
        )
    return result
