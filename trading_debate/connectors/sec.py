"""SEC EDGAR official filings and company facts connector."""

from __future__ import annotations

import os
from typing import Any
from xml.etree import ElementTree

from ..models import EvidenceItem
from ..symbols import taiwan_code
from ..utils import request_json, request_text

_COMPANY_TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
_SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik}.json"
_COMPANY_FACTS_URL = "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json"

_FACTS = {
    "Revenue": ["RevenueFromContractWithCustomerExcludingAssessedTax", "Revenues"],
    "Gross profit": ["GrossProfit"],
    "Operating income": ["OperatingIncomeLoss"],
    "Net income": ["NetIncomeLoss"],
    "EPS diluted": ["EarningsPerShareDiluted"],
    "Operating cash flow": ["NetCashProvidedByUsedInOperatingActivities"],
    "Capital expenditures": [
        "PaymentsToAcquirePropertyPlantAndEquipment",
        "PaymentsToAcquireProductiveAssets",
    ],
    "Assets": ["Assets"],
    "Liabilities": ["Liabilities"],
    "Equity": ["StockholdersEquity"],
    "Debt": [
        "LongTermDebtAndFinanceLeaseObligationsCurrentAndNoncurrent",
        "LongTermDebt",
    ],
}


def _headers() -> dict[str, str]:
    agent = os.getenv("SEC_USER_AGENT") or "MyTradingChat/0.1 contact@example.com"
    return {"User-Agent": agent}


def _status(run_id: str, state: str, detail: str) -> EvidenceItem:
    return EvidenceItem(
        run_id=run_id,
        source="SEC EDGAR",
        title=f"Connector {state}",
        payload={"state": state, "detail": detail},
    )


def _resolve_cik(symbol: str) -> tuple[str, dict[str, Any]] | None:
    tickers = request_json(_COMPANY_TICKERS_URL, headers=_headers())
    for company in tickers.values():
        if str(company.get("ticker", "")).upper() == symbol.upper():
            cik = str(company.get("cik_str", "")).zfill(10)
            return cik, company
    return None


def _recent_filings(
    submissions: dict[str, Any], forms: set[str], limit: int
) -> list[dict[str, Any]]:
    recent = submissions.get("filings", {}).get("recent", {})
    rows: list[dict[str, Any]] = []
    for index, form in enumerate(recent.get("form", []) or []):
        if form not in forms:
            continue
        accession = (recent.get("accessionNumber", []) or [None])[index]
        primary = (recent.get("primaryDocument", []) or [None])[index]
        cik = str(submissions.get("cik", "")).lstrip("0")
        url = None
        if accession and primary and cik:
            url = (
                "https://www.sec.gov/Archives/edgar/data/"
                f"{cik}/{str(accession).replace('-', '')}/{primary}"
            )
        rows.append(
            {
                "form": form,
                "accessionNumber": accession,
                "filingDate": (recent.get("filingDate", []) or [None])[index],
                "reportDate": (recent.get("reportDate", []) or [None])[index],
                "primaryDocument": primary,
                "url": url,
            }
        )
        if len(rows) >= limit:
            break
    return rows


def _latest_fact(facts: dict[str, Any], tags: list[str]) -> dict[str, Any] | None:
    us_gaap = facts.get("facts", {}).get("us-gaap", {})
    for tag in tags:
        units = us_gaap.get(tag, {}).get("units", {})
        candidates = []
        for unit, rows in units.items():
            for row in rows:
                if row.get("val") is None or row.get("form") not in {"10-K", "10-Q"}:
                    continue
                candidates.append({"tag": tag, "unit": unit, **row})
        if candidates:
            return sorted(
                candidates,
                key=lambda row: (
                    str(row.get("end") or ""),
                    str(row.get("filed") or ""),
                ),
                reverse=True,
            )[0]
    return None


def _financial_snapshot(facts: dict[str, Any]) -> dict[str, Any]:
    snapshot: dict[str, Any] = {}
    for label, tags in _FACTS.items():
        fact = _latest_fact(facts, tags)
        if fact:
            snapshot[label] = fact
    ocf = snapshot.get("Operating cash flow", {}).get("val")
    capex = snapshot.get("Capital expenditures", {}).get("val")
    if isinstance(ocf, int | float) and isinstance(capex, int | float):
        snapshot["Free cash flow"] = {
            "val": ocf - abs(capex),
            "unit": snapshot["Operating cash flow"].get("unit"),
            "derived_from": ["Operating cash flow", "Capital expenditures"],
        }
    return snapshot


def _xml_value(element: ElementTree.Element, path: str) -> str | None:
    value = element.findtext(path)
    return value.strip() if value else None


def _form4_transactions(xml_text: str) -> list[dict[str, Any]]:
    """Extract non-derivative Form 4 transactions from the SEC XML document."""
    root = ElementTree.fromstring(xml_text)
    owner = _xml_value(root, ".//reportingOwner/reportingOwnerId/rptOwnerName")
    transactions: list[dict[str, Any]] = []
    for transaction in root.findall(".//nonDerivativeTransaction"):
        acquired_disposed = _xml_value(
            transaction, "transactionAmounts/transactionAcquiredDisposedCode/value"
        )
        shares = _xml_value(transaction, "transactionAmounts/transactionShares/value")
        price = _xml_value(
            transaction, "transactionAmounts/transactionPricePerShare/value"
        )
        row = {
            "owner": owner,
            "security_title": _xml_value(transaction, "securityTitle/value"),
            "transaction_date": _xml_value(transaction, "transactionDate/value"),
            "transaction_code": _xml_value(
                transaction, "transactionCoding/transactionCode"
            ),
            "acquired_disposed": acquired_disposed,
            "shares": shares,
            "price_per_share": price,
            "shares_owned_after": _xml_value(
                transaction,
                "postTransactionAmounts/sharesOwnedFollowingTransaction/value",
            ),
            "ownership_type": _xml_value(
                transaction, "ownershipNature/directOrIndirectOwnership/value"
            ),
        }
        if any(row.values()):
            transactions.append(row)
    return transactions


def fetch_sec(
    run_id: str, symbol: str, limit: int, *, company_name: str | None = None
) -> list[EvidenceItem]:
    if taiwan_code(symbol):
        return [_status(run_id, "skipped", "SEC EDGAR only supports US tickers.")]

    try:
        resolved = _resolve_cik(symbol)
    except Exception as exc:
        return [_status(run_id, "error", f"Failed to resolve CIK for {symbol}: {exc}")]
    if not resolved:
        return [_status(run_id, "empty", f"No SEC CIK found for {symbol}.")]

    cik, company = resolved
    items = [
        EvidenceItem(
            run_id=run_id,
            source="SEC EDGAR",
            title="CIK mapping",
            payload={"cik": cik, **company},
            url=_COMPANY_TICKERS_URL,
        )
    ]

    try:
        facts = request_json(_COMPANY_FACTS_URL.format(cik=cik), headers=_headers())
        snapshot = _financial_snapshot(facts)
        if snapshot:
            items.append(
                EvidenceItem(
                    run_id=run_id,
                    source="SEC EDGAR Company Facts",
                    title="Official financial facts snapshot",
                    payload=snapshot,
                    url=_COMPANY_FACTS_URL.format(cik=cik),
                )
            )
        else:
            items.append(
                _status(run_id, "empty", f"No company facts found for {symbol}.")
            )
    except Exception as exc:
        items.append(
            _status(run_id, "error", f"Company facts failed for {symbol}: {exc}")
        )

    try:
        submissions = request_json(_SUBMISSIONS_URL.format(cik=cik), headers=_headers())
        filing_rows = _recent_filings(submissions, {"10-K", "10-Q", "8-K"}, limit)
        if filing_rows:
            items.append(
                EvidenceItem(
                    run_id=run_id,
                    source="SEC EDGAR Submissions",
                    title="Recent 10-K/10-Q/8-K filings",
                    payload={"cik": cik, "filings": filing_rows},
                    url=_SUBMISSIONS_URL.format(cik=cik),
                    published_at=filing_rows[0].get("filingDate"),
                )
            )
        form4_rows = _recent_filings(submissions, {"4"}, limit)
        if form4_rows:
            transactions: list[dict[str, Any]] = []
            fetch_errors: list[str] = []
            for filing in form4_rows:
                url = filing.get("url")
                if not url:
                    continue
                try:
                    transactions.extend(
                        _form4_transactions(request_text(url, _headers()))
                    )
                except Exception as exc:
                    fetch_errors.append(f"{filing.get('accessionNumber')}: {exc}")
            items.append(
                EvidenceItem(
                    run_id=run_id,
                    source="SEC EDGAR Form 4",
                    title="Recent insider transactions",
                    payload={
                        "cik": cik,
                        "filings": form4_rows,
                        "transactions": transactions,
                        "transaction_fetch_errors": fetch_errors,
                    },
                    url=_SUBMISSIONS_URL.format(cik=cik),
                    published_at=form4_rows[0].get("filingDate"),
                )
            )
    except Exception as exc:
        items.append(
            _status(run_id, "error", f"Submissions failed for {symbol}: {exc}")
        )

    return items
