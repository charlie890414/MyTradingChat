"""Local evidence, history, and report tools for the agent trading-debate workflow."""

from __future__ import annotations

from .connectors import CONNECTORS, fetch_official_market_data, fetch_yahoo
from .connectors.technicals import compute_technicals, history_to_records
from .db import (
    assess_current_evidence,
    connect,
    connector_status,
    create_evidence_batch,
    evidence_reference,
    finish_evidence_batch,
    insert_evidence,
    insert_evidence_item,
    insert_evidence_items,
)
from .models import EvidenceItem, YahooFetchResult
from .symbols import (
    company_search_name,
    normalize_symbol,
    resolve_taiwan_yahoo_symbol,
    taiwan_code,
)
from .utils import (
    NEWS_MAX_AGE_DAYS,
    RequestError,
    as_json,
    date_range_days,
    is_recent_news,
    load_dotenv,
    request_json,
    utc_now,
)

__all__ = [
    "CONNECTORS",
    "EvidenceItem",
    "NEWS_MAX_AGE_DAYS",
    "RequestError",
    "YahooFetchResult",
    "as_json",
    "assess_current_evidence",
    "cmd_context",
    "cmd_fetch",
    "cmd_init",
    "cmd_purge",
    "cmd_record",
    "cmd_render",
    "cmd_runs",
    "cmd_search",
    "company_search_name",
    "compute_technicals",
    "connect",
    "connector_status",
    "create_evidence_batch",
    "evidence_reference",
    "date_range_days",
    "fetch_official_market_data",
    "fetch_yahoo",
    "finish_evidence_batch",
    "history_to_records",
    "is_recent_news",
    "insert_evidence",
    "insert_evidence_item",
    "insert_evidence_items",
    "load_dotenv",
    "normalize_symbol",
    "render_evidence",
    "request_json",
    "resolve_taiwan_yahoo_symbol",
    "taiwan_code",
    "utc_now",
    "serve",
]


def __getattr__(name: str):
    """Lazily expose CLI commands without importing the CLI during package load."""
    if name in {
        "cmd_context",
        "cmd_fetch",
        "cmd_init",
        "cmd_purge",
        "cmd_record",
        "cmd_runs",
        "cmd_search",
    }:
        from . import cli

        return getattr(cli, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


# Import render here to keep the original public API intact without a circular import.
from .render import cmd_render, render_evidence  # noqa: E402
from .web import serve  # noqa: E402
