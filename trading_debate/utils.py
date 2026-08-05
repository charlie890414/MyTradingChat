"""Shared helpers for the trading-debate package."""

from __future__ import annotations

import json
import ssl
import time
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from dotenv import load_dotenv

__all__ = [
    "NEWS_MAX_AGE_DAYS",
    "RequestError",
    "as_json",
    "date_range_days",
    "is_recent_news",
    "load_dotenv",
    "request_json",
    "request_bytes",
    "request_text",
    "utc_now",
]


class RequestError(RuntimeError):
    """Raised when a JSON HTTP request fails after all retries."""


_USER_AGENT = "MyTradingChat/0.1"
NEWS_MAX_AGE_DAYS = 30


def utc_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat()


def date_range_days(days: int = 365) -> tuple[str, str]:
    """Return ISO start/end dates for a window ending today."""
    end = datetime.now(UTC).date()
    start = end - timedelta(days=days)
    return start.isoformat(), end.isoformat()


def is_recent_news(
    published_at: str | int | float | None,
    *,
    now: datetime | None = None,
) -> bool:
    """Return whether a news item has a publication time within 30 days."""
    if published_at is None or published_at == "":
        return False
    try:
        if isinstance(published_at, int | float):
            published = datetime.fromtimestamp(published_at, UTC)
        else:
            published = datetime.fromisoformat(str(published_at).replace("Z", "+00:00"))
            if published.tzinfo is None:
                published = published.replace(tzinfo=UTC)
    except (OverflowError, TypeError, ValueError):
        return False
    reference_time = now or datetime.now(UTC)
    return published >= reference_time - timedelta(days=NEWS_MAX_AGE_DAYS)


def as_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, default=str, sort_keys=True)


def request_json(
    url: str,
    params: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
    method: str = "GET",
    body: bytes | None = None,
    *,
    timeout: float = 20.0,
    max_retries: int = 3,
    backoff: float = 1.0,
    ssl_context: ssl.SSLContext | None = None,
) -> Any:
    if params:
        query = urlencode(
            {key: value for key, value in params.items() if value is not None}
        )
        url = f"{url}?{query}"
    request = Request(
        url,
        data=body,
        method=method,
        headers={"User-Agent": _USER_AGENT, **(headers or {})},
    )
    last_exc: Exception | None = None
    for attempt in range(max_retries):
        try:
            with urlopen(request, timeout=timeout, context=ssl_context) as response:  # nosec B310: fixed HTTPS provider URLs only
                return json.loads(response.read().decode("utf-8"))
        except (
            HTTPError,
            URLError,
            TimeoutError,
            OSError,
            json.JSONDecodeError,
        ) as exc:
            last_exc = exc
            if attempt < max_retries - 1:
                time.sleep(backoff * (2**attempt))
    raise RequestError(f"Failed to fetch {url}: {last_exc}") from last_exc


def request_text(
    url: str,
    headers: dict[str, str] | None = None,
    method: str = "GET",
    body: bytes | None = None,
    *,
    timeout: float = 20.0,
    max_retries: int = 3,
    backoff: float = 1.0,
) -> str:
    """Fetch text from a fixed trusted HTTPS endpoint with retry handling."""
    request = Request(
        url,
        data=body,
        method=method,
        headers={"User-Agent": _USER_AGENT, **(headers or {})},
    )
    last_exc: Exception | None = None
    for attempt in range(max_retries):
        try:
            with urlopen(request, timeout=timeout) as response:  # nosec B310: SEC URL
                return response.read().decode("utf-8")
        except (HTTPError, URLError, TimeoutError, OSError, UnicodeDecodeError) as exc:
            last_exc = exc
            if attempt < max_retries - 1:
                time.sleep(backoff * (2**attempt))
    raise RequestError(f"Failed to fetch {url}: {last_exc}") from last_exc


def request_bytes(
    url: str,
    headers: dict[str, str] | None = None,
    *,
    timeout: float = 20.0,
    max_retries: int = 3,
    backoff: float = 1.0,
) -> bytes:
    """Fetch a document from a fixed trusted HTTPS endpoint with retries."""
    request = Request(url, headers={"User-Agent": _USER_AGENT, **(headers or {})})
    last_exc: Exception | None = None
    for attempt in range(max_retries):
        try:
            with urlopen(request, timeout=timeout) as response:  # nosec B310: fixed URLs
                return response.read()
        except (HTTPError, URLError, TimeoutError, OSError) as exc:
            last_exc = exc
            if attempt < max_retries - 1:
                time.sleep(backoff * (2**attempt))
    raise RequestError(f"Failed to fetch {url}: {last_exc}") from last_exc
