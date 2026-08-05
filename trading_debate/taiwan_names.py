"""Resolve Taiwan numeric stock codes to Chinese company names."""

from __future__ import annotations

import ssl
from typing import Any

from .symbols import taiwan_code
from .utils import request_json

_UNVERIFIED_CTX = ssl._create_unverified_context()

_PROFILE_ENDPOINTS = [
    "https://openapi.twse.com.tw/v1/opendata/t187ap03_L",
    "https://www.tpex.org.tw/openapi/v1/mopsfin_t187ap03_O",
]


def _company_code(row: dict[str, Any]) -> str:
    for key in ("公司代號", "公司代號(股票代號)", "股票代號", "出表公司"):
        value = str(row.get(key, "")).strip()
        if value:
            return value.split()[0]
    return ""


def fetch_taiwan_company_name(symbol: str) -> str | None:
    """Return the Chinese company name for a Taiwan code, or None.

    Queries TWSE/TPEX listed-company profile endpoints and returns the
    ``公司名稱`` field when a matching code is found.
    """
    code = taiwan_code(symbol)
    if not code:
        return None

    for url in _PROFILE_ENDPOINTS:
        try:
            records = request_json(url, ssl_context=_UNVERIFIED_CTX)
        except Exception:  # pragma: no cover - network/provider errors
            continue
        if not isinstance(records, list):
            continue
        for row in records:
            if _company_code(row) == code:
                name = row.get("公司名稱") or row.get("公司簡稱")
                if name:
                    return str(name).strip()
    return None
