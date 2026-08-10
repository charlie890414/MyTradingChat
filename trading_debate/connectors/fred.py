"""FRED macroeconomic evidence connector."""

from __future__ import annotations

import os
from typing import Any

from ..models import EvidenceItem
from ..utils import request_json

_OBSERVATIONS_URL = "https://api.stlouisfed.org/fred/series/observations"
_SERIES = {
    "FEDFUNDS": "Federal Funds Rate",
    "DGS2": "2-Year Treasury Constant Maturity Rate",
    "DGS10": "10-Year Treasury Constant Maturity Rate",
    "T10Y2Y": "10-Year Minus 2-Year Treasury Spread",
    "BAMLC0A0CM": "ICE BofA US Corporate Index Option-Adjusted Spread",
    "VIXCLS": "CBOE Volatility Index: VIX",
    "CPIAUCSL": "Consumer Price Index for All Urban Consumers",
    "UNRATE": "Unemployment Rate",
    "DTWEXBGS": "Trade Weighted US Dollar Index: Broad",
}


def _status(
    run_id: str, state: str, detail: str, *, series_id: str | None = None
) -> EvidenceItem:
    title = f"Connector {state}"
    if series_id:
        title = f"{title}: {series_id}"
    return EvidenceItem(
        run_id=run_id,
        source="FRED",
        title=title,
        payload={"state": state, "detail": detail, "series_id": series_id},
    )


def _number(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _snapshot(
    series_id: str, observations: list[dict[str, Any]]
) -> dict[str, Any] | None:
    valid = [row for row in observations if row.get("value") not in (None, ".")]
    valid.sort(key=lambda row: str(row.get("date") or ""), reverse=True)
    if not valid:
        return None
    latest = valid[0]
    previous = valid[1] if len(valid) > 1 else None
    latest_value = _number(latest.get("value"))
    previous_value = _number(previous.get("value")) if previous else None
    return {
        "series_id": series_id,
        "latest": {"date": latest.get("date"), "value": latest_value},
        "previous": (
            {"date": previous.get("date"), "value": previous_value}
            if previous
            else None
        ),
        "change": (
            latest_value - previous_value
            if latest_value is not None and previous_value is not None
            else None
        ),
    }


def fetch_fred(
    run_id: str, symbol: str, limit: int, *, company_name: str | None = None
) -> list[EvidenceItem]:
    """Fetch a compact, current macroeconomic backdrop from FRED."""
    del symbol, limit, company_name
    api_key = os.getenv("FRED_API_KEY")
    if not api_key:
        return [_status(run_id, "skipped", "Set FRED_API_KEY to enable FRED.")]

    items: list[EvidenceItem] = []
    for series_id, name in _SERIES.items():
        try:
            payload = request_json(
                _OBSERVATIONS_URL,
                {
                    "series_id": series_id,
                    "api_key": api_key,
                    "file_type": "json",
                    "sort_order": "desc",
                    "limit": 10,
                },
            )
            if not isinstance(payload, dict) or payload.get("error_code"):
                detail = (
                    payload.get("error_message", "Unexpected FRED response.")
                    if isinstance(payload, dict)
                    else "Unexpected FRED response."
                )
                raise RuntimeError(detail)
            snapshot = _snapshot(series_id, payload.get("observations", []))
            if snapshot is None:
                items.append(
                    _status(
                        run_id,
                        "empty",
                        "No numeric observations returned.",
                        series_id=series_id,
                    )
                )
                continue
            items.append(
                EvidenceItem(
                    run_id=run_id,
                    source="FRED",
                    title=f"Macroeconomic series: {name}",
                    payload=snapshot,
                    url=(
                        "https://fred.stlouisfed.org/graph/fredgraph.csv"
                        f"?id={series_id}"
                    ),
                    published_at=str(snapshot["latest"]["date"] or ""),
                )
            )
        except Exception as exc:
            items.append(_status(run_id, "error", str(exc), series_id=series_id))
    return items
