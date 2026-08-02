"""TWSE/TPEX OpenAPI and MOPS official disclosure connector."""

from __future__ import annotations

import ssl
from collections.abc import Iterable
from typing import Any

from ..models import EvidenceItem
from ..symbols import taiwan_code
from ..utils import request_json

_UNVERIFIED_CTX = ssl._create_unverified_context()

_PROFILE_ENDPOINTS = [
    (
        "TWSE listed-company profile",
        "https://openapi.twse.com.tw/v1/opendata/t187ap03_L",
    ),
    (
        "TWSE listed-company profile",
        "https://openapi.twse.com.tw/v1/opendata/t187ap04_L",
    ),
    (
        "TPEX company profile",
        "https://www.tpex.org.tw/openapi/v1/mopsfin_t187ap03_O",
    ),
]

_DISCLOSURE_ENDPOINTS = [
    (
        "MOPS material information",
        "https://openapi.twse.com.tw/v1/opendata/t187ap04_L",
    ),
    (
        "TPEX material information",
        "https://www.tpex.org.tw/openapi/v1/mopsfin_t187ap04_O",
    ),
]

_MONTHLY_REVENUE_ENDPOINTS = [
    (
        "TWSE monthly revenue",
        "https://openapi.twse.com.tw/v1/opendata/t187ap05_L",
    ),
    (
        "TPEX monthly revenue",
        "https://www.tpex.org.tw/openapi/v1/mopsfin_t187ap05_O",
    ),
]

# Financial-industry endpoints are deliberately first because their line items
# differ materially from general-industry financial statements.
_STATEMENT_ENDPOINTS = {
    "Income statement": [
        (
            "MOPS income statement (financial holding)",
            "https://openapi.twse.com.tw/v1/opendata/t187ap06_L_fh",
        ),
        (
            "MOPS income statement (financial)",
            "https://openapi.twse.com.tw/v1/opendata/t187ap06_L_basi",
        ),
        (
            "MOPS income statement (securities)",
            "https://openapi.twse.com.tw/v1/opendata/t187ap06_L_bd",
        ),
        (
            "MOPS income statement (insurance)",
            "https://openapi.twse.com.tw/v1/opendata/t187ap06_L_ins",
        ),
        (
            "MOPS income statement (general)",
            "https://openapi.twse.com.tw/v1/opendata/t187ap06_L_ci",
        ),
    ],
    "Balance sheet": [
        (
            "MOPS balance sheet (financial holding)",
            "https://openapi.twse.com.tw/v1/opendata/t187ap07_L_fh",
        ),
        (
            "MOPS balance sheet (financial)",
            "https://openapi.twse.com.tw/v1/opendata/t187ap07_L_basi",
        ),
        (
            "MOPS balance sheet (securities)",
            "https://openapi.twse.com.tw/v1/opendata/t187ap07_L_bd",
        ),
        (
            "MOPS balance sheet (insurance)",
            "https://openapi.twse.com.tw/v1/opendata/t187ap07_L_ins",
        ),
        (
            "MOPS balance sheet (general)",
            "https://openapi.twse.com.tw/v1/opendata/t187ap07_L_ci",
        ),
    ],
}


def _status(run_id: str, state: str, detail: str) -> EvidenceItem:
    return EvidenceItem(
        run_id=run_id,
        source="TWSE/TPEX OpenAPI / MOPS",
        title=f"Connector {state}",
        payload={"state": state, "detail": detail},
    )


def _company_code(row: dict[str, Any]) -> str:
    for key in ("公司代號", "公司代號(股票代號)", "股票代號", "出表公司"):
        value = str(row.get(key, "")).strip()
        if value:
            return value.split()[0]
    return ""


def _matching_rows(
    records: Iterable[dict[str, Any]], code: str
) -> list[dict[str, Any]]:
    return [row for row in records if _company_code(row) == code]


def _fetch_endpoint(url: str) -> list[dict[str, Any]]:
    records = request_json(url, ssl_context=_UNVERIFIED_CTX)
    return records if isinstance(records, list) else []


def _items_from_endpoint_group(
    run_id: str,
    code: str,
    endpoints: list[tuple[str, str]],
    source: str,
    title_prefix: str,
    limit: int,
) -> list[EvidenceItem]:
    items: list[EvidenceItem] = []
    errors: list[str] = []
    for label, url in endpoints:
        try:
            rows = _matching_rows(_fetch_endpoint(url), code)
        except Exception as exc:
            errors.append(f"{label}: {exc}")
            continue
        for row in rows[-limit:] if limit else rows:
            title = (
                row.get("公司名稱")
                or row.get("公司簡稱")
                or row.get("公司代號")
                or code
            )
            evidence_title = (
                title_prefix
                if title_prefix == "Official listed-company disclosure profile"
                else f"{title_prefix}: {title}"
            )
            date = row.get("出表日期") or row.get("年月") or row.get("資料年月")
            items.append(
                EvidenceItem(
                    run_id=run_id,
                    source=source,
                    title=evidence_title,
                    payload={"endpoint": label, **row},
                    url=url,
                    published_at=str(date) if date else None,
                )
            )
    if items:
        return items
    if errors:
        return [_status(run_id, "error", "; ".join(errors))]
    return [_status(run_id, "empty", f"No {title_prefix.lower()} found for {code}.")]


def _fetch_statement(
    run_id: str,
    code: str,
    statement_name: str,
    endpoints: list[tuple[str, str]],
    limit: int,
) -> list[EvidenceItem]:
    """Fetch a MOPS statement from the first matching industry endpoint."""
    errors: list[str] = []
    for label, url in endpoints:
        try:
            rows = _matching_rows(_fetch_endpoint(url), code)
        except Exception as exc:
            errors.append(f"{label}: {exc}")
            continue
        if not rows:
            continue
        return [
            EvidenceItem(
                run_id=run_id,
                source="TWSE OpenAPI / MOPS",
                title=f"Official {statement_name}: {row.get('公司名稱', code)}",
                payload={"endpoint": label, **row},
                url=url,
                published_at=str(row.get("出表日期") or row.get("資料年月") or ""),
            )
            for row in rows[-limit:]
        ]
    if errors:
        return [_status(run_id, "error", "; ".join(errors))]
    return [
        _status(
            run_id, "empty", f"No official {statement_name.lower()} found for {code}."
        )
    ]


def fetch_twse_mops(
    run_id: str, symbol: str, limit: int = 0, *, company_name: str | None = None
) -> list[EvidenceItem]:
    code = taiwan_code(symbol)
    if not code:
        detail = "Official disclosures are only queried for Taiwan ticker codes."
        return [_status(run_id, "skipped", detail)]

    cap = limit or 10
    items: list[EvidenceItem] = []
    for endpoint_group, source, title_prefix in (
        (
            _PROFILE_ENDPOINTS,
            "TWSE OpenAPI / MOPS",
            "Official listed-company disclosure profile",
        ),
        (
            _DISCLOSURE_ENDPOINTS,
            "TWSE/TPEX Material Information",
            "Material information",
        ),
        (_MONTHLY_REVENUE_ENDPOINTS, "TWSE/TPEX Monthly Revenue", "Monthly revenue"),
    ):
        group_items = _items_from_endpoint_group(
            run_id, code, endpoint_group, source, title_prefix, cap
        )
        # Keep positive evidence granular, but avoid flooding reports with one empty
        # status for each unavailable official endpoint group.
        if group_items and group_items[0].title.startswith("Connector"):
            if not items:
                items.extend(group_items)
            continue
        items.extend(group_items)

    for statement_name, endpoints in _STATEMENT_ENDPOINTS.items():
        statement_items = _fetch_statement(run_id, code, statement_name, endpoints, cap)
        if statement_items and statement_items[0].title.startswith("Connector"):
            continue
        items.extend(statement_items)

    if not items:
        return [_status(run_id, "empty", f"No TWSE/TPEX records found for {code}.")]
    return items
