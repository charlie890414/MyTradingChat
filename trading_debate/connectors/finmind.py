"""FinMind Taiwan market-data connector."""

from __future__ import annotations

import os
from typing import Any

from ..models import EvidenceItem
from ..symbols import taiwan_code
from ..utils import date_range_days, request_json

_DATASETS = {
    "TaiwanStockNews": {
        "source": "FinMind TaiwanStockNews",
        "title": "Taiwan stock news",
        "days": 365,
    },
    "TaiwanStockMonthRevenue": {
        "source": "FinMind TaiwanStockMonthRevenue",
        "title": "Monthly revenue",
        "days": 730,
    },
    "TaiwanStockFinancialStatements": {
        "source": "FinMind TaiwanStockFinancialStatements",
        "title": "Financial statements",
        "days": 1460,
    },
    "TaiwanStockBalanceSheet": {
        "source": "FinMind TaiwanStockBalanceSheet",
        "title": "Balance sheet",
        "days": 1460,
    },
    "TaiwanStockCashFlowsStatement": {
        "source": "FinMind TaiwanStockCashFlows",
        "title": "Cash flow statement",
        "days": 1460,
    },
    "InstitutionalInvestorsBuySell": {
        "source": "FinMind InstitutionalInvestorsBuySell",
        "title": "Institutional investors buy/sell",
        "days": 90,
    },
    "TaiwanStockMarginPurchaseShortSale": {
        "source": "FinMind MarginPurchaseShortSale",
        "title": "Margin purchase and short sale",
        "days": 90,
    },
}


def _status(run_id: str, state: str, detail: str) -> EvidenceItem:
    return EvidenceItem(
        run_id=run_id,
        source="FinMind",
        title=f"Connector {state}",
        payload={"state": state, "detail": detail},
    )


def _fetch_dataset(
    dataset: str, code: str, headers: dict[str, str], limit: int
) -> dict[str, Any]:
    config = _DATASETS[dataset]
    start, end = date_range_days(int(config["days"]))
    return request_json(
        "https://api.finmindtrade.com/api/v4/data",
        {
            "dataset": dataset,
            "data_id": code,
            "start_date": start,
            "end_date": end,
        },
        headers=headers,
    )


def fetch_finmind(run_id: str, symbol: str, limit: int) -> list[EvidenceItem]:
    code = taiwan_code(symbol)
    if not code:
        detail = "FinMind TaiwanStockNews is only queried for Taiwan ticker codes."
        return [_status(run_id, "skipped", detail)]
    headers = {}
    token = os.getenv("FINMIND_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"

    result: list[EvidenceItem] = []
    for dataset, config in _DATASETS.items():
        try:
            data = _fetch_dataset(dataset, code, headers, limit)
        except Exception as exc:
            result.append(
                _status(run_id, "error", f"{dataset} failed for {code}: {exc}")
            )
            continue

        if data.get("status") not in (200, "200"):
            result.append(
                _status(
                    run_id,
                    "error",
                    data.get("msg")
                    or data.get("message")
                    or f"{dataset} failed: {data}",
                )
            )
            continue

        rows = data.get("data", []) or []
        if not rows:
            result.append(_status(run_id, "empty", f"{dataset} returned no rows."))
            continue

        source = str(config["source"])
        for row in rows[-limit:]:
            title = (
                row.get("title")
                or row.get("headline")
                or f"{config['title']} for {code}"
            )
            published_at = str(row.get("date") or row.get("revenue_year_month") or "")
            result.append(
                EvidenceItem(
                    run_id=run_id,
                    source=source,
                    title=title,
                    payload=row,
                    url=row.get("link") or row.get("url"),
                    published_at=published_at,
                )
            )

    if not result:
        result.append(
            _status(run_id, "empty", f"No FinMind datasets returned rows for {code}.")
        )
    return result
