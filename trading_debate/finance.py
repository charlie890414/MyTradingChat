"""Compatibility facade exposing finance utilities and connectors."""

from __future__ import annotations

import yfinance  # noqa: F401  exposed at module level so tests can patch

from .connectors import CONNECTORS, fetch_official_market_data, fetch_yahoo
from .connectors.technicals import compute_technicals, history_to_records
from .symbols import (
    normalize_symbol,
    resolve_taiwan_yahoo_symbol,
    taiwan_code,
)

__all__ = [
    "CONNECTORS",
    "compute_technicals",
    "fetch_official_market_data",
    "fetch_yahoo",
    "history_to_records",
    "normalize_symbol",
    "resolve_taiwan_yahoo_symbol",
    "taiwan_code",
    "yfinance",
]
