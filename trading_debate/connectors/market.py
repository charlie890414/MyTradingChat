"""Official Taiwan exchange market-data connector."""

from __future__ import annotations

from typing import Any

from ..models import EvidenceItem
from ..symbols import taiwan_code
from ..utils import request_json

_TWSE_VALUATION_URL = "https://openapi.twse.com.tw/v1/exchangeReport/BWIBBU_ALL"

_MARKET_DATASETS = {
    "twse": (
        (
            "valuation",
            "Official valuation snapshot",
            _TWSE_VALUATION_URL,
        ),
        (
            "profitability",
            "Official profitability analysis",
            "https://openapi.twse.com.tw/v1/opendata/t187ap17_L",
        ),
        (
            "dividend",
            "Official dividend distribution",
            "https://openapi.twse.com.tw/v1/opendata/t187ap45_L",
        ),
        (
            "ex_right",
            "Official ex-right and ex-dividend forecast",
            "https://openapi.twse.com.tw/v1/exchangeReport/TWT48U_ALL",
        ),
        (
            "margin",
            "Official margin purchase and short sale balance",
            "https://openapi.twse.com.tw/v1/exchangeReport/MI_MARGN",
        ),
        (
            "securities_lending",
            "Official securities lending availability",
            "https://openapi.twse.com.tw/v1/SBL/TWT96U",
        ),
    ),
    "tpex": (
        (
            "valuation",
            "Official valuation snapshot",
            "https://www.tpex.org.tw/openapi/v1/tpex_mainboard_peratio_analysis",
        ),
        (
            "profitability",
            "Official profitability analysis",
            "https://www.tpex.org.tw/openapi/v1/mopsfin_187ap17_O",
        ),
        (
            "dividend",
            "Official dividend distribution",
            "https://www.tpex.org.tw/openapi/v1/mopsfin_t187ap39_O",
        ),
        (
            "ex_right_forecast",
            "Official ex-right and ex-dividend forecast",
            "https://www.tpex.org.tw/openapi/v1/tpex_exright_prepost",
        ),
        (
            "ex_right_result",
            "Official ex-right and ex-dividend result",
            "https://www.tpex.org.tw/openapi/v1/tpex_exright_daily",
        ),
        (
            "institutional",
            "Official institutional investor trading",
            "https://www.tpex.org.tw/openapi/v1/tpex_3insti_daily_trading",
        ),
        (
            "foreign_ownership",
            "Official foreign ownership ratio",
            "https://www.tpex.org.tw/openapi/v1/tpex_3insti_qfii",
        ),
        (
            "margin",
            "Official margin purchase and short sale balance",
            "https://www.tpex.org.tw/openapi/v1/tpex_mainboard_margin_balance",
        ),
        (
            "securities_lending_balance",
            "Official securities lending short-sale balance",
            "https://www.tpex.org.tw/openapi/v1/tpex_margin_sbl",
        ),
        (
            "securities_lending_trading",
            "Official securities lending short-sale trading",
            "https://www.tpex.org.tw/openapi/v1/tpex_short_sell",
        ),
    ),
}


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


def _market_for_symbol(symbol: str) -> str:
    return "tpex" if symbol.upper().endswith(".TWO") else "twse"


def _company_code(row: dict[str, Any], market: str) -> str:
    exchange_keys = (
        ("GRETAICode", "TWSECode") if market == "tpex" else ("TWSECode", "GRETAICode")
    )
    keys = (
        "Code",
        "SecuritiesCompanyCode",
        "公司代號",
        "公司代號(股票代號)",
        "股票代號",
        "證券代號",
        *exchange_keys,
    )
    for key in keys:
        value = str(row.get(key, "")).strip()
        if value:
            return value.split()[0]
    return ""


def _published_at(row: dict[str, Any]) -> str | None:
    for key in ("Date", "日期", "出表日期", "年度", "發放日期"):
        value = row.get(key)
        if value:
            return str(value)
    return None


def _market_status(run_id: str, state: str, detail: str) -> EvidenceItem:
    return EvidenceItem(
        run_id=run_id,
        source="TWSE/TPEX Official Market Data",
        title=f"Connector {state}",
        payload={"state": state, "detail": detail},
    )


def fetch_official_market_data(
    run_id: str, symbol: str, limit: int, *, company_name: str | None = None
) -> list[EvidenceItem]:
    """Fetch official Taiwan market, ownership, dividend, and valuation evidence."""
    del limit, company_name
    code = taiwan_code(symbol)
    if not code:
        return [
            _market_status(run_id, "skipped", "Official market data is Taiwan-only.")
        ]

    market = _market_for_symbol(symbol)
    items: list[EvidenceItem] = []
    errors: list[str] = []
    for dataset, title, url in _MARKET_DATASETS[market]:
        try:
            payload = request_json(url)
        except Exception as exc:
            errors.append(f"{dataset}: {exc}")
            continue
        if not isinstance(payload, list):
            errors.append(f"{dataset}: unexpected response format")
            continue
        for row in payload:
            if not isinstance(row, dict) or _company_code(row, market) != code:
                continue
            items.append(
                EvidenceItem(
                    run_id=run_id,
                    source="TWSE/TPEX Official Market Data",
                    title=title,
                    payload={"dataset": dataset, "market": market, "record": row},
                    url=url,
                    published_at=_published_at(row),
                )
            )
    if items:
        return items
    if errors:
        return [_market_status(run_id, "error", "; ".join(errors))]
    return [
        _market_status(run_id, "empty", f"No official market records found for {code}.")
    ]


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
