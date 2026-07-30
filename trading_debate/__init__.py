"""Local evidence, history, and report tools for the agent trading-debate workflow."""

from __future__ import annotations

from .cli import (
    cmd_context,
    cmd_fetch,
    cmd_init,
    cmd_record,
    cmd_search,
)
from .connectors import CONNECTORS, fetch_yahoo
from .connectors.technicals import compute_technicals, history_to_records
from .db import (
    connect,
    connector_status,
    insert_evidence,
    insert_evidence_item,
    insert_evidence_items,
)
from .models import EvidenceItem, YahooFetchResult
from .symbols import normalize_symbol, resolve_taiwan_yahoo_symbol, taiwan_code
from .utils import (
    RequestError,
    as_json,
    date_range_days,
    load_dotenv,
    request_json,
    utc_now,
)

__all__ = [
    "CONNECTORS",
    "EvidenceItem",
    "RequestError",
    "YahooFetchResult",
    "as_json",
    "cmd_context",
    "cmd_fetch",
    "cmd_init",
    "cmd_record",
    "cmd_render",
    "cmd_search",
    "compute_technicals",
    "connect",
    "connector_status",
    "date_range_days",
    "fetch_yahoo",
    "history_to_records",
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
]

# Import render here to keep the original public API intact without a circular import.
from .render import cmd_render, render_evidence  # noqa: E402
