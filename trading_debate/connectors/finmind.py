"""FinMind Taiwan market-data connector."""

from __future__ import annotations

import os
from typing import Any

from ..models import EvidenceItem
from ..symbols import taiwan_code
from ..utils import date_range_days, is_recent_news, request_json

_DATASETS = {
    "TaiwanStockNews": {
        "source": "FinMind TaiwanStockNews",
        "title": "Taiwan stock news",
        "days": 0,
        "single_day": True,
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
    "TaiwanStockInstitutionalInvestorsBuySell": {
        "source": "FinMind TaiwanStockInstitutionalInvestorsBuySell",
        "title": "Institutional investors buy/sell",
        "days": 90,
    },
    "TaiwanStockMarginPurchaseShortSale": {
        "source": "FinMind MarginPurchaseShortSale",
        "title": "Margin purchase and short sale",
        "days": 90,
    },
    "TaiwanStockPER": {
        "source": "FinMind TaiwanStockPER",
        "title": "Valuation history",
        "days": 730,
        "compact": True,
    },
    "TaiwanStockShareholding": {
        "source": "FinMind TaiwanStockShareholding",
        "title": "Foreign ownership",
        "days": 365,
        "compact": True,
    },
    "TaiwanStockHoldingSharesPer": {
        "source": "FinMind TaiwanStockHoldingSharesPer",
        "title": "Shareholding distribution",
        "days": 365,
        "compact": True,
    },
    "TaiwanStockSecuritiesLending": {
        "source": "FinMind TaiwanStockSecuritiesLending",
        "title": "Securities lending",
        "days": 90,
        "compact": True,
    },
    "TaiwanDailyShortSaleBalances": {
        "source": "FinMind TaiwanDailyShortSaleBalances",
        "title": "Short sale balances",
        "days": 90,
        "compact": True,
    },
    "TaiwanStockDividend": {
        "source": "FinMind TaiwanStockDividend",
        "title": "Dividend policy",
        "days": 1460,
        "compact": True,
    },
    "TaiwanStockDividendResult": {
        "source": "FinMind TaiwanStockDividendResult",
        "title": "Dividend results",
        "days": 1460,
        "compact": True,
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
    params: dict[str, Any] = {
        "dataset": dataset,
        "data_id": code,
        "start_date": start,
    }
    if not config.get("single_day"):
        params["end_date"] = end
    return request_json(
        "https://api.finmindtrade.com/api/v4/data",
        params,
        headers=headers,
    )


def _latest_period_rows(
    rows: list[dict[str, Any]],
) -> tuple[str | None, list[dict[str, Any]]]:
    """Return every row in the newest reporting period, not just the final row."""
    dates = [str(row.get("date", "")) for row in rows if row.get("date")]
    if not dates:
        return None, []
    latest_date = max(dates)
    return latest_date, [row for row in rows if str(row.get("date", "")) == latest_date]


def _number(value: Any) -> float | None:
    """Return a numeric value when a FinMind field can be safely aggregated."""
    if isinstance(value, bool):
        return None
    if isinstance(value, int | float):
        return float(value)
    return None


def _institutional_trend(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Summarize the latest five trading days without inferring a signal."""
    dates = sorted({str(row.get("date")) for row in rows if row.get("date")})[-5:]
    by_investor: dict[str, dict[str, float]] = {}
    for row in rows:
        if str(row.get("date")) not in dates:
            continue
        name = str(row.get("name") or "Unknown investor")
        summary = by_investor.setdefault(name, {"buy": 0.0, "sell": 0.0})
        summary["buy"] += _number(row.get("buy")) or 0.0
        summary["sell"] += _number(row.get("sell")) or 0.0
    investors = [
        {"name": name, **values, "net_buy_sell": values["buy"] - values["sell"]}
        for name, values in sorted(by_investor.items())
    ]
    return {"trading_dates": dates, "investors": investors}


def _margin_trend(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Expose recent margin fields and changes without assuming their meaning."""
    recent_rows = sorted(rows, key=lambda row: str(row.get("date") or ""))[-5:]
    if len(recent_rows) < 2:
        return {"recent_rows": recent_rows, "field_changes": {}}
    first, latest = recent_rows[0], recent_rows[-1]
    changes: dict[str, float] = {}
    for key, latest_value in latest.items():
        first_value = _number(first.get(key))
        latest_number = _number(latest_value)
        if first_value is not None and latest_number is not None:
            changes[key] = latest_number - first_value
    return {
        "trading_dates": [str(row.get("date") or "") for row in recent_rows],
        "recent_rows": recent_rows,
        "field_changes": changes,
    }


def _summary_item(
    run_id: str,
    dataset: str,
    config: dict[str, Any],
    rows: list[dict[str, Any]],
) -> EvidenceItem | None:
    """Create compact, directly citable snapshots for key Taiwan datasets."""
    if dataset not in {
        "TaiwanStockFinancialStatements",
        "TaiwanStockBalanceSheet",
        "TaiwanStockCashFlowsStatement",
        "TaiwanStockInstitutionalInvestorsBuySell",
        "TaiwanStockMarginPurchaseShortSale",
    } and not config.get("compact"):
        return None

    latest_date, latest_rows = _latest_period_rows(rows)
    if not latest_rows:
        return None
    payload: dict[str, Any] = {
        "dataset": dataset,
        "latest_date": latest_date,
        "latest_period_rows": latest_rows,
        "available_rows": len(rows),
    }
    if config.get("compact"):
        payload["recent_dates"] = sorted(
            {str(row.get("date")) for row in rows if row.get("date")}
        )[-20:]
    if dataset in {
        "TaiwanStockInstitutionalInvestorsBuySell",
        "TaiwanStockMarginPurchaseShortSale",
    }:
        payload["recent_dates"] = sorted({str(row.get("date")) for row in rows})[-20:]
    if dataset == "TaiwanStockInstitutionalInvestorsBuySell":
        payload["five_day_trend"] = _institutional_trend(rows)
    if dataset == "TaiwanStockMarginPurchaseShortSale":
        payload["five_day_trend"] = _margin_trend(rows)

    titles = {
        "TaiwanStockFinancialStatements": "Latest consolidated income statement",
        "TaiwanStockBalanceSheet": "Latest consolidated balance sheet",
        "TaiwanStockCashFlowsStatement": "Latest consolidated cash flow statement",
        "TaiwanStockInstitutionalInvestorsBuySell": (
            "Latest institutional investor buy/sell"
        ),
        "TaiwanStockMarginPurchaseShortSale": "Latest margin purchase and short sale",
    }
    return EvidenceItem(
        run_id=run_id,
        source=str(config["source"]),
        title=titles.get(dataset, f"Latest {config['title']} snapshot"),
        payload=payload,
        published_at=latest_date,
    )


def fetch_finmind(
    run_id: str, symbol: str, limit: int, *, company_name: str | None = None
) -> list[EvidenceItem]:
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

        summary = _summary_item(run_id, dataset, config, rows)
        if summary:
            result.append(summary)
        if config.get("compact"):
            continue

        source = str(config["source"])
        for row in rows[-limit:]:
            title = (
                row.get("title")
                or row.get("headline")
                or f"{config['title']} for {code}"
            )
            published_at = str(row.get("date") or row.get("revenue_year_month") or "")
            if dataset == "TaiwanStockNews" and not is_recent_news(published_at):
                continue
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
