"""Official Taiwan exchange market-data connector."""

from __future__ import annotations

from typing import Any

from ..models import EvidenceItem
from ..symbols import taiwan_code
from ..utils import request_json

_TWSE_VALUATION_URL = "https://openapi.twse.com.tw/v1/exchangeReport/BWIBBU_ALL"


def _status(run_id: str, state: str, detail: str) -> EvidenceItem:
    return EvidenceItem(
        run_id=run_id,
        source="TWSE Official Valuation Data",
        title=f"Connector {state}",
        payload={"state": state, "detail": detail},
    )


def _twse_valuation(code: str) -> dict[str, Any] | None:
    payload = request_json(_TWSE_VALUATION_URL)
    if isinstance(payload, list):
        for row in payload:
            if isinstance(row, dict) and str(row.get("Code", "")).strip() == code:
                return row
        return None

    # Retain parsing support for the legacy website response while callers
    # transition to the OpenAPI's object-based payload.
    if not isinstance(payload, dict) or payload.get("stat") != "OK":
        return None
    fields = payload.get("fields", [])
    for row in payload.get("data", []):
        if isinstance(row, list) and row and str(row[0]).strip() == code:
            return dict(zip(fields, row, strict=False))
    return None


def fetch_official_valuation_data(
    run_id: str, symbol: str, limit: int, *, company_name: str | None = None
) -> list[EvidenceItem]:
    """Return the official TWSE valuation snapshot without price history."""
    del limit, company_name
    code = taiwan_code(symbol)
    if not code:
        return [_status(run_id, "skipped", "Official valuation data is Taiwan-only.")]
    try:
        valuation = _twse_valuation(code)
        if valuation:
            return [
                EvidenceItem(
                    run_id=run_id,
                    source="TWSE Official Valuation Data",
                    title="Official valuation snapshot",
                    payload={"dataset": "BWIBBU_ALL", "record": valuation},
                    url=_TWSE_VALUATION_URL,
                    published_at=str(
                        valuation.get("Date") or valuation.get("日期") or ""
                    ),
                )
            ]
    except Exception as exc:
        return [_status(run_id, "error", str(exc))]
    return [_status(run_id, "empty", f"No official valuation record found for {code}.")]
