"""Resolve Taiwan numeric stock codes to Chinese company names."""

from __future__ import annotations

from typing import Any

from .symbols import taiwan_code
from .utils import request_json

_PROFILE_ENDPOINTS = {
    "twse": "https://openapi.twse.com.tw/v1/opendata/t187ap03_L",
    "tpex": "https://www.tpex.org.tw/openapi/v1/mopsfin_t187ap03_O",
}


def _company_code(row: dict[str, Any]) -> str:
    for key in ("公司代號", "公司代號(股票代號)", "股票代號", "出表公司"):
        value = str(row.get(key, "")).strip()
        if value:
            return value.split()[0]
    return ""


def fetch_taiwan_company_profile(symbol: str) -> tuple[str, dict[str, Any], str] | None:
    """Return the matched official profile and endpoint for a Taiwan symbol.

    Explicit exchange suffixes select one provider only. Unsuffixed numeric
    codes retain the historical TWSE-then-TPEX lookup behaviour.
    """
    code = taiwan_code(symbol)
    if not code:
        return None

    markets = ("tpex",) if symbol.upper().endswith(".TWO") else ("twse",)
    if "." not in symbol:
        markets = ("twse", "tpex")
    for market in markets:
        url = _PROFILE_ENDPOINTS[market]
        try:
            records = request_json(url)
        except Exception:  # pragma: no cover - network/provider errors
            continue
        if not isinstance(records, list):
            continue
        for row in records:
            if _company_code(row) == code:
                name = row.get("公司名稱") or row.get("公司簡稱")
                if name:
                    return str(name).strip(), row, url
    return None


def fetch_taiwan_company_name(symbol: str) -> str | None:
    """Return the Chinese company name for a Taiwan code, or None."""
    profile = fetch_taiwan_company_profile(symbol)
    return profile[0] if profile else None
