"""MOPS announcement attachments and PDF-text evidence connector."""

from __future__ import annotations

import io
import re
from collections.abc import Iterable
from typing import Any
from urllib.parse import urlencode, urlsplit

from ..models import EvidenceItem
from ..symbols import taiwan_code
from ..utils import request_bytes, request_json, request_text

_DISCLOSURE_ENDPOINTS = (
    "https://openapi.twse.com.tw/v1/opendata/t187ap04_L",
    "https://www.tpex.org.tw/openapi/v1/mopsfin_t187ap04_O",
)
_MOPS_DISCLOSURE_PAGE = "https://mops.twse.com.tw/mops/web/t05st01"
_MOPS_CASH_FLOW_URL = "https://mopsov.twse.com.tw/mops/web/ajax_t164sb05"
_PDF_URL_RE = re.compile(r"https?://[^\s\"'<>]+?\.pdf(?:\?[^\s\"'<>]*)?", re.I)
_HTML_TAG_RE = re.compile(r"<[^>]+>")
_OFFICIAL_PDF_HOSTS = frozenset({"mops.twse.com.tw", "mopsov.twse.com.tw"})
_MAX_ATTACHMENTS_PER_ANNOUNCEMENT = 3
_MAX_PDF_BYTES = 8_000_000
_MAX_PDF_PAGES = 30
_MAX_PDF_TEXT_CHARS = 12_000


def _status(run_id: str, state: str, detail: str) -> EvidenceItem:
    return EvidenceItem(
        run_id=run_id,
        source="MOPS Official Documents",
        title=f"Connector {state}",
        payload={"state": state, "detail": detail},
    )


def _company_code(row: dict[str, Any]) -> str:
    for key in ("公司代號", "SecuritiesCompanyCode"):
        value = str(row.get(key, "")).strip()
        if value:
            return value.split()[0]
    return ""


def _pdf_urls(row: dict[str, Any]) -> list[str]:
    urls: list[str] = []
    for value in row.values():
        if not isinstance(value, str):
            continue
        for url in _PDF_URL_RE.findall(value):
            if url not in urls:
                urls.append(url)
    return urls


def _extract_pdf_text(content: bytes) -> dict[str, Any]:
    try:
        from pypdf import PdfReader
    except ImportError:
        return {"state": "unavailable", "detail": "pypdf is not installed."}
    try:
        reader = PdfReader(io.BytesIO(content))
        if reader.is_encrypted:
            return {"state": "encrypted", "page_count": len(reader.pages)}
        if len(reader.pages) > _MAX_PDF_PAGES:
            return {"state": "too_many_pages", "page_count": len(reader.pages)}
        pages = [page.extract_text() or "" for page in reader.pages]
    except Exception as exc:
        return {"state": "error", "detail": str(exc)}
    text = "\n\n".join(page for page in pages if page.strip())[:_MAX_PDF_TEXT_CHARS]
    return {
        "state": "available" if text else "empty",
        "page_count": len(pages),
        "text": text,
    }


def _is_official_pdf_url(url: str) -> bool:
    parsed = urlsplit(url)
    return parsed.scheme == "https" and parsed.hostname in _OFFICIAL_PDF_HOSTS


def _announcement_items(
    run_id: str, code: str, rows: Iterable[dict[str, Any]], limit: int
) -> list[EvidenceItem]:
    items: list[EvidenceItem] = []
    company_rows = [row for row in rows if _company_code(row) == code]
    for row in company_rows[-limit:]:
        title = str(row.get("主旨") or row.get("CompanyName") or code).strip()
        published_at = str(
            row.get("發言日期") or row.get("Date") or row.get("出表日期") or ""
        )
        base_payload = {"announcement": row, "mops_page": _MOPS_DISCLOSURE_PAGE}
        items.append(
            EvidenceItem(
                run_id=run_id,
                source="MOPS Official Announcement",
                title=f"MOPS announcement: {title}",
                payload=base_payload,
                url=_MOPS_DISCLOSURE_PAGE,
                published_at=published_at,
            )
        )
        for url in _pdf_urls(row)[:_MAX_ATTACHMENTS_PER_ANNOUNCEMENT]:
            if not _is_official_pdf_url(url):
                document = {
                    "state": "rejected_url",
                    "detail": "Attachment URL is not an official MOPS HTTPS host.",
                }
            else:
                try:
                    document = _extract_pdf_text(
                        request_bytes(url, max_bytes=_MAX_PDF_BYTES)
                    )
                except Exception as exc:
                    document = {"state": "download_error", "detail": str(exc)}
            items.append(
                EvidenceItem(
                    run_id=run_id,
                    source="MOPS Official Attachment",
                    title=f"MOPS attachment: {title}",
                    payload={"announcement": row, "document": document},
                    url=url,
                    published_at=published_at,
                )
            )
    return items


def _cash_flow_item(run_id: str, code: str) -> EvidenceItem | None:
    """Retrieve MOPS's latest consolidated cash-flow statement as source text."""
    form = {
        "step": "1",
        "firstin": "true",
        "off": "1",
        "keyword4": "",
        "code1": "",
        "TYPEK2": "",
        "checkbtn": "",
        "queryName": "co_id",
        "inpuType": "co_id",
        "TYPEK": "all",
        "isnew": "true",
        "co_id": code,
        "year": "",
        "season": "",
    }
    html = request_text(
        _MOPS_CASH_FLOW_URL,
        {"Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
        body=urlencode(form).encode(),
    )
    text = re.sub(r"\s+", " ", _HTML_TAG_RE.sub(" ", html)).strip()
    if not text or "現金流量表" not in text:
        return None
    title_match = re.search(r"本資料由(.+?)公司提供", text)
    company = title_match.group(1).strip() if title_match else code
    period_match = re.search(r"民國\d+年第[一二三四1-4]季", text)
    return EvidenceItem(
        run_id=run_id,
        source="MOPS Official Financial Statements",
        title=f"Official Cash flow statement: {company}",
        payload={
            "statement": "Cash flow statement",
            "form": "t164sb05",
            "text": text,
            "period": period_match.group(0) if period_match else None,
        },
        url=_MOPS_CASH_FLOW_URL,
    )


def fetch_mops_documents(
    run_id: str, symbol: str, limit: int, *, company_name: str | None = None
) -> list[EvidenceItem]:
    """Fetch MOPS announcement metadata and extract text from disclosed PDFs.

    MOPS OpenAPI announcements do not guarantee an attachment URL.  In that
    case the original disclosure is still retained with its MOPS search page.
    """
    del company_name
    code = taiwan_code(symbol)
    if not code:
        return [_status(run_id, "skipped", "MOPS documents are Taiwan-only.")]
    items: list[EvidenceItem] = []
    errors: list[str] = []
    for endpoint in _DISCLOSURE_ENDPOINTS:
        try:
            rows = request_json(endpoint)
        except Exception as exc:
            errors.append(f"{endpoint}: {exc}")
            continue
        if isinstance(rows, list):
            items.extend(_announcement_items(run_id, code, rows, limit or 10))
    try:
        cash_flow = _cash_flow_item(run_id, code)
    except Exception as exc:
        errors.append(f"MOPS cash flow: {exc}")
    else:
        if cash_flow:
            items.append(cash_flow)
    if items:
        return items
    if errors:
        return [_status(run_id, "error", "; ".join(errors))]
    return [_status(run_id, "empty", f"No MOPS announcements found for {code}.")]
