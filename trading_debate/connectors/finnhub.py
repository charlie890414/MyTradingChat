"""Finnhub company news, financials, and earnings connector."""

from __future__ import annotations

import os
from typing import Any

from ..models import EvidenceItem
from ..symbols import taiwan_code
from ..utils import date_range_days, request_json


def _status(run_id: str, state: str, detail: str) -> EvidenceItem:
    return EvidenceItem(
        run_id=run_id,
        source="Finnhub",
        title=f"Connector {state}",
        payload={"state": state, "detail": detail},
    )


def _request_finnhub(endpoint: str, params: dict[str, Any]) -> Any:
    return request_json(f"https://finnhub.io/api/v1/{endpoint}", params)


def fetch_finnhub(
    run_id: str, symbol: str, limit: int, *, company_name: str | None = None
) -> list[EvidenceItem]:
    if taiwan_code(symbol):
        return [_status(run_id, "skipped", "Finnhub only supports US tickers here.")]
    key = os.getenv("FINNHUB_API_KEY")
    if not key:
        return [_status(run_id, "skipped", "Set FINNHUB_API_KEY to enable Finnhub.")]

    result: list[EvidenceItem] = []
    start, end = date_range_days(365)

    try:
        news = _request_finnhub(
            "company-news",
            {"symbol": symbol, "from": start, "to": end, "token": key},
        )
        if isinstance(news, dict) and news.get("error"):
            raise RuntimeError(news["error"])
        for article in (news or [])[:limit]:
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
    except Exception as exc:
        result.append(_status(run_id, "error", f"Company news failed: {exc}"))

    for metric in ("all",):
        try:
            financials = _request_finnhub(
                "stock/metric",
                {"symbol": symbol, "metric": metric, "token": key},
            )
            if isinstance(financials, dict) and financials.get("error"):
                raise RuntimeError(financials["error"])
            result.append(
                EvidenceItem(
                    run_id=run_id,
                    source="Finnhub Basic Financials",
                    title="Basic financial metrics",
                    payload=financials,
                )
            )
        except Exception as exc:
            result.append(_status(run_id, "error", f"Basic financials failed: {exc}"))

    try:
        earnings = _request_finnhub("stock/earnings", {"symbol": symbol, "token": key})
        if isinstance(earnings, dict) and earnings.get("error"):
            raise RuntimeError(earnings["error"])
        rows = (earnings or [])[:limit]
        if rows:
            result.append(
                EvidenceItem(
                    run_id=run_id,
                    source="Finnhub Earnings",
                    title="Historical earnings surprises",
                    payload={"symbol": symbol, "earnings": rows},
                    published_at=str(rows[0].get("period") or ""),
                )
            )
    except Exception as exc:
        result.append(_status(run_id, "error", f"Earnings failed: {exc}"))

    try:
        reported = _request_finnhub(
            "stock/financials-reported",
            {"symbol": symbol, "freq": "quarterly", "token": key},
        )
        if isinstance(reported, dict) and reported.get("error"):
            raise RuntimeError(reported["error"])
        reports = (reported or {}).get("data", [])[:limit]
        if reports:
            result.append(
                EvidenceItem(
                    run_id=run_id,
                    source="Finnhub Financials As Reported",
                    title="Quarterly financials as reported",
                    payload={"symbol": symbol, "reports": reports},
                    published_at=str(reports[0].get("endDate") or ""),
                )
            )
    except Exception as exc:
        result.append(_status(run_id, "error", f"Financials as reported failed: {exc}"))

    return result
