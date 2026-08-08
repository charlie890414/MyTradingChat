"""Shared helpers for the trading-debate package."""

from __future__ import annotations

import ipaddress
import json
import math
import re
import socket
import ssl
import time
from datetime import UTC, date, datetime, timedelta
from html.parser import HTMLParser
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener, urlopen

from dotenv import load_dotenv

__all__ = [
    "NEWS_MAX_AGE_DAYS",
    "RequestError",
    "as_json",
    "canonical_evidence_key",
    "date_range_days",
    "fetch_article_text",
    "is_news_source",
    "is_relevant_news",
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
NEWS_MAX_AGE_DAYS = 7
_NEWS_SOURCES = frozenset(
    {
        "Yahoo Finance News",
        "Google News RSS",
        "Bing News RSS",
        "Finnhub Company News",
        "FinMind TaiwanStockNews",
    }
)
_LEGAL_NAME_WORDS = frozenset(
    {
        "inc",
        "incorporated",
        "corporation",
        "corp",
        "co",
        "company",
        "limited",
        "ltd",
        "plc",
        "llc",
        "holdings",
        "group",
    }
)
_TRACKING_PARAMETERS = frozenset({"ref", "source", "src", "oc"})
_ARTICLE_MAX_BYTES = 250_000
_ARTICLE_MAX_CHARS = 12_000
_IGNORED_HTML_TAGS = frozenset(
    {"head", "script", "style", "noscript", "svg", "template"}
)


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
    """Return whether a news item has a publication time within 7 days."""
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


def is_news_source(source: str) -> bool:
    """Return whether a source contains article-level news evidence."""
    return source in _NEWS_SOURCES


def _normalize_text(value: str) -> str:
    return " ".join(re.findall(r"[\w\u4e00-\u9fff]+", value.casefold()))


def _company_aliases(symbol: str, company_name: str | None) -> set[str]:
    aliases = {symbol.casefold(), symbol.split(".", 1)[0].casefold()}
    if not company_name:
        return aliases

    normalized = _normalize_text(company_name)
    if normalized:
        aliases.add(normalized)
    words = normalized.split()
    root_words = [word for word in words if word not in _LEGAL_NAME_WORDS]
    if root_words:
        aliases.add(" ".join(root_words))
        if all(word.isascii() for word in root_words) and len(root_words) > 1:
            aliases.add("".join(word[0] for word in root_words))
    return {alias for alias in aliases if len(alias.replace(" ", "")) >= 3}


def _payload_text(payload: Any) -> str:
    if isinstance(payload, dict):
        values = payload.values()
    elif isinstance(payload, list):
        values = payload
    else:
        return str(payload)
    return " ".join(_payload_text(value) for value in values)


def is_relevant_news(
    *,
    symbol: str,
    company_name: str | None,
    title: str,
    payload: Any,
) -> bool:
    """Return whether article text directly identifies the researched company."""
    article_text = _normalize_text(f"{title} {_payload_text(payload)}")
    return bool(article_text) and any(
        alias in article_text for alias in _company_aliases(symbol, company_name)
    )


def _canonical_url(url: str) -> str:
    parsed = urlsplit(url)
    query = [
        (key, value)
        for key, value in parse_qsl(parsed.query, keep_blank_values=True)
        if not key.casefold().startswith("utm_")
        and key.casefold() not in _TRACKING_PARAMETERS
    ]
    return urlunsplit(
        (
            parsed.scheme.casefold(),
            parsed.netloc.casefold(),
            parsed.path,
            urlencode(query),
            "",
        )
    )


def canonical_evidence_key(
    source: str, title: str, url: str | None, published_at: str | None
) -> str:
    """Return a stable key, sharing syndicated news across news sources."""
    if not is_news_source(source):
        return f"source:{source}|{url or ''}|{published_at or ''}|{title}"
    normalized_title = _normalize_text(title)
    published_date = (published_at or "")[:10]
    if normalized_title and published_date:
        return f"news:title:{normalized_title}|{published_date}"
    if url:
        return f"news:url:{_canonical_url(url)}"
    return f"news:source:{source}|{normalized_title}|{published_at or ''}"


def _is_public_article_url(url: str, resolver: Any = socket.getaddrinfo) -> bool:
    parsed = urlsplit(url)
    try:
        port = parsed.port
    except ValueError:
        return False
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or port not in {None, 80, 443}
    ):
        return False
    try:
        addresses = resolver(parsed.hostname, None, type=socket.SOCK_STREAM)
    except (OSError, ValueError):
        return False
    return bool(addresses) and all(
        ipaddress.ip_address(address[4][0]).is_global for address in addresses
    )


class _SafeArticleRedirectHandler(HTTPRedirectHandler):
    def __init__(self, resolver: Any) -> None:
        super().__init__()
        self._resolver = resolver

    def redirect_request(  # type: ignore[override]
        self, req: Request, fp: Any, code: int, msg: str, headers: Any, newurl: str
    ) -> Request | None:
        if not _is_public_article_url(newurl, self._resolver):
            raise HTTPError(newurl, code, "Unsafe article redirect", headers, fp)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


class _ArticleTextParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._ignored_depth = 0
        self.parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.casefold() in _IGNORED_HTML_TAGS:
            self._ignored_depth += 1

    def handle_endtag(self, tag: str) -> None:
        if tag.casefold() in _IGNORED_HTML_TAGS and self._ignored_depth:
            self._ignored_depth -= 1

    def handle_data(self, data: str) -> None:
        if not self._ignored_depth:
            self.parts.append(data)


def fetch_article_text_result(
    url: str,
    *,
    timeout: float = 5.0,
    max_bytes: int = _ARTICLE_MAX_BYTES,
    max_chars: int = _ARTICLE_MAX_CHARS,
    resolver: Any = socket.getaddrinfo,
    opener: Any | None = None,
) -> tuple[str | None, dict[str, str]]:
    """Fetch article text and return a machine-readable outcome."""
    if not _is_public_article_url(url, resolver):
        return None, {"state": "failed", "reason": "unsafe_url"}
    request = Request(url, headers={"User-Agent": _USER_AGENT, "Accept": "text/html"})
    article_opener = opener or build_opener(_SafeArticleRedirectHandler(resolver))
    try:
        with article_opener.open(request, timeout=timeout) as response:
            content_type = str(response.headers.get("Content-Type", "")).casefold()
            if "text/html" not in content_type:
                return None, {
                    "state": "failed",
                    "reason": "non_html_response",
                    "content_type": content_type or "missing",
                }
            content_length = response.headers.get("Content-Length")
            if content_length and int(content_length) > max_bytes:
                return None, {
                    "state": "failed",
                    "reason": "content_too_large",
                }
            content = response.read(max_bytes + 1)
            if len(content) > max_bytes:
                return None, {"state": "failed", "reason": "content_too_large"}
            charset = response.headers.get_content_charset() or "utf-8"
    except HTTPError as exc:
        return None, {
            "state": "failed",
            "reason": "http_error",
            "status_code": str(exc.code),
        }
    except (OSError, UnicodeError, ValueError) as exc:
        return None, {
            "state": "failed",
            "reason": "transport_or_decode_error",
            "detail": str(exc)[:200],
        }
    parser = _ArticleTextParser()
    try:
        parser.feed(content.decode(charset, errors="replace"))
        parser.close()
    except (UnicodeError, ValueError) as exc:
        return None, {
            "state": "failed",
            "reason": "html_parse_error",
            "detail": str(exc)[:200],
        }
    text = re.sub(r"\s+", " ", " ".join(parser.parts)).strip()
    if not text:
        return None, {"state": "failed", "reason": "empty_article_body"}
    return text[:max_chars], {"state": "available"}


def fetch_article_text(
    url: str,
    *,
    timeout: float = 5.0,
    max_bytes: int = _ARTICLE_MAX_BYTES,
    max_chars: int = _ARTICLE_MAX_CHARS,
    resolver: Any = socket.getaddrinfo,
    opener: Any | None = None,
) -> str | None:
    """Fetch bounded, script-free article text from a public HTTP(S) URL."""
    text, _ = fetch_article_text_result(
        url,
        timeout=timeout,
        max_bytes=max_bytes,
        max_chars=max_chars,
        resolver=resolver,
        opener=opener,
    )
    return text


def as_json(value: Any) -> str:
    """Serialize only standards-compliant JSON for persisted and CLI data."""
    return json.dumps(
        _json_safe(value), ensure_ascii=False, sort_keys=True, allow_nan=False
    )


_SENSITIVE_QUERY_KEYS = frozenset({"api_key", "apikey", "key", "secret", "token"})


def redact_url(url: str) -> str:
    """Return a safe URL suitable for diagnostics without query credentials."""
    parsed = urlsplit(url)
    query = parse_qsl(parsed.query, keep_blank_values=True)
    redacted = [
        (key, "REDACTED" if key.casefold() in _SENSITIVE_QUERY_KEYS else value)
        for key, value in query
    ]
    return urlunsplit(parsed._replace(query=urlencode(redacted)))


def _json_safe(value: Any) -> Any:
    """Normalize provider values without silently stringifying unknown objects."""
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if hasattr(value, "item"):
        return _json_safe(value.item())
    return value


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
    if max_retries < 1:
        raise ValueError("max_retries must be at least 1")
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
                return _json_safe(json.loads(response.read().decode("utf-8")))
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
    raise RequestError(f"Failed to fetch {redact_url(url)}: {last_exc}") from last_exc


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
    if max_retries < 1:
        raise ValueError("max_retries must be at least 1")
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
    raise RequestError(f"Failed to fetch {redact_url(url)}: {last_exc}") from last_exc


def request_bytes(
    url: str,
    headers: dict[str, str] | None = None,
    *,
    timeout: float = 20.0,
    max_retries: int = 3,
    backoff: float = 1.0,
) -> bytes:
    """Fetch a document from a fixed trusted HTTPS endpoint with retries."""
    if max_retries < 1:
        raise ValueError("max_retries must be at least 1")
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
    raise RequestError(f"Failed to fetch {redact_url(url)}: {last_exc}") from last_exc
