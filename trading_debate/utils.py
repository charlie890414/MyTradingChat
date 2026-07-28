"""Shared helpers for the trading-debate package."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from dotenv import load_dotenv

__all__ = ["as_json", "load_dotenv", "request_json", "utc_now"]


def utc_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat()


def as_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, default=str, sort_keys=True)


def request_json(
    url: str,
    params: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
    method: str = "GET",
    body: bytes | None = None,
) -> Any:
    if params:
        url = f"{url}?{urlencode({key: value for key, value in params.items() if value is not None})}"
    request = Request(
        url,
        data=body,
        method=method,
        headers={"User-Agent": "MyTradingChat/0.1", **(headers or {})},
    )
    with urlopen(request, timeout=20) as response:  # nosec B310: fixed HTTPS provider URLs only
        return json.loads(response.read().decode("utf-8"))
