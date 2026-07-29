"""Symbol normalization and Taiwan exchange resolution."""

from __future__ import annotations

import re
from typing import Any

import yfinance


def taiwan_code(symbol: str) -> str | None:
    match = re.fullmatch(r"(\d{4,6})(?:\.(?:TW|TWO))?", symbol.upper())
    return match.group(1) if match else None


def normalize_symbol(symbol: str) -> str:
    """Return a Yahoo-Finance-compatible symbol.

    Bare Taiwan numeric codes (e.g. ``3037``) are suffixed with ``.TW``;
    codes already ending in ``.TW`` or ``.TWO`` are left unchanged.
    US-style tickers are returned upper-cased.
    """
    code = taiwan_code(symbol)
    if code and not re.search(r"\.(?:TW|TWO)$", symbol, re.IGNORECASE):
        return f"{code}.TW"
    return symbol.upper()


def _ticker_has_data(ticker: Any) -> bool:
    """Return True if a yfinance Ticker looks like it resolved to a real security."""
    try:
        info = ticker.get_info()
    except Exception:  # pragma: no cover - defensive, yfinance raises on network errors
        return False
    if not info:
        return False
    # Yahoo returns a nearly-empty dict for invalid symbols
    # (often just trailingPegRatio).
    if set(info.keys()) <= {"trailingPegRatio"}:
        return False
    # A usable security usually has a name or a price.
    if info.get("longName") or info.get("shortName") or info.get("currentPrice"):
        return True
    # Some valid tickers only have price history without a full info profile.
    try:
        history = ticker.history(period="5d")
    except Exception:  # pragma: no cover
        return False
    return history is not None and not history.empty


def resolve_taiwan_yahoo_symbol(symbol: str) -> str:
    """Resolve a Taiwan numeric code to the Yahoo Finance suffix that has data.

    For a numeric code with or without a suffix (e.g. ``6841`` or ``6841.TW``),
    try ``.TW`` first; if Yahoo has no data, fall back to ``.TWO``. This covers
    both listed/OTC and some emerging board stocks that Yahoo indexes. If
    neither resolves, return the ``.TW`` form so the downstream failure is
    explicit. US-style tickers are returned unchanged.
    """
    code = taiwan_code(symbol)
    if not code:
        return symbol.upper()

    candidates = [f"{code}.TW", f"{code}.TWO"]
    for candidate in candidates:
        try:
            if _ticker_has_data(yfinance.Ticker(candidate)):
                return candidate
        except Exception:  # pragma: no cover - network/provider errors
            continue
    return candidates[0]
