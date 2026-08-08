"""Tests for shared utility helpers."""

from __future__ import annotations

import json
from datetime import UTC, date, datetime
from unittest.mock import MagicMock, patch

import pytest

import trading_debate as td
from trading_debate.utils import (
    fetch_article_text,
    fetch_article_text_result,
    is_relevant_news,
)


def test_is_relevant_news_requires_direct_company_reference():
    assert is_relevant_news(
        symbol="AVGO",
        company_name="Broadcom Inc.",
        title="Broadcom expands custom chip capacity",
        payload={"summary": "AVGO demand remains strong."},
    )


def test_is_relevant_news_supports_non_latin_company_names():
    assert is_relevant_news(
        symbol="AAPL",
        company_name="アップル",
        title="アップル、新製品を発表",
        payload={"summary": "日本語のニュース本文です。"},
    )


def test_fetch_article_text_cleans_html_and_rejects_private_hosts():
    class Response:
        class Headers(dict):
            def get_content_charset(self):
                return "utf-8"

        headers = Headers({"Content-Type": "text/html; charset=utf-8"})

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def read(self, size):
            return "<html><head><title>Ignore</title></head><body><nav>Menu</nav><article>Broadcom wins <b>custom-chip</b> order. 日本語の補足。</article><footer>Recommended</footer><script>alert('ignore')</script></body></html>".encode()

    class Opener:
        def open(self, request, timeout):
            return Response()

    def public_resolver(*args, **kwargs):
        return [(None, None, None, None, ("93.184.216.34", 0))]

    def private_resolver(*args, **kwargs):
        return [(None, None, None, None, ("127.0.0.1", 0))]

    text = fetch_article_text(
        "https://example.com/article",
        resolver=public_resolver,
        opener=Opener(),
    )
    assert text == "Broadcom wins custom-chip order. 日本語の補足。"
    assert (
        fetch_article_text(
            "http://localhost/article",
            resolver=private_resolver,
            opener=Opener(),
        )
        is None
    )
    assert not is_relevant_news(
        symbol="AVGO",
        company_name="Broadcom Inc.",
        title="Qualcomm handset revenue contracts",
        payload={"summary": "AMD and Nvidia also reported results."},
    )


@pytest.mark.parametrize(
    ("content_length", "expected_state"),
    [(300_000, "available"), (1_000_001, "failed")],
)
def test_fetch_article_text_allows_responses_up_to_one_megabyte(
    content_length, expected_state
):
    class Response:
        class Headers(dict):
            def get_content_charset(self):
                return "utf-8"

        headers = Headers(
            {"Content-Type": "text/html", "Content-Length": str(content_length)}
        )

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def read(self, size):
            return b"<article>Relevant article body.</article>"

    class Opener:
        def open(self, request, timeout):
            return Response()

    def public_resolver(*args, **kwargs):
        return [(None, None, None, None, ("93.184.216.34", 0))]

    text, status = fetch_article_text_result(
        "https://example.com/article",
        resolver=public_resolver,
        opener=Opener(),
    )

    assert status["state"] == expected_state
    if expected_state == "available":
        assert text == "Relevant article body."
    else:
        assert text is None
        assert status["reason"] == "content_too_large"


def test_utc_now_format():
    result = td.utc_now()
    parsed = datetime.fromisoformat(result)
    assert parsed.tzinfo == UTC
    assert "T" in result
    assert ":" in result


def test_as_json():
    data = {"key": "value", "num": 42, "bool": True, "none": None}
    result = td.as_json(data)
    parsed = json.loads(result)
    assert parsed == data


def test_as_json_sorted():
    result = td.as_json({"z": 1, "a": 2})
    parsed = json.loads(result)
    assert list(parsed.keys()) == ["a", "z"]


def test_as_json_normalizes_non_finite_numbers():
    assert json.loads(td.as_json({"value": float("nan")})) == {"value": None}


@pytest.mark.parametrize("value", [date(2026, 8, 9), datetime(2026, 8, 9, 12, 0)])
def test_as_json_serializes_date_and_datetime(value):
    parsed = json.loads(td.as_json({"when": value}))
    assert parsed == {
        "when": "2026-08-09T12:00:00" if isinstance(value, datetime) else "2026-08-09"
    }


def test_request_errors_redact_sensitive_query_values():
    with patch("trading_debate.utils.urlopen", side_effect=ConnectionResetError):
        with pytest.raises(td.RequestError) as exc_info:
            td.request_json(
                "https://example.com/api",
                {"token": "private-token", "query": "public"},
                max_retries=1,
            )
    assert "private-token" not in str(exc_info.value)
    assert "token=REDACTED" in str(exc_info.value)


def test_date_range_days():
    start, end = td.date_range_days(365)
    end_date = datetime.fromisoformat(end)
    start_date = datetime.fromisoformat(start)
    assert (end_date.date() - start_date.date()).days == 365


def test_is_recent_news_requires_a_timestamp_within_7_days():
    now = datetime(2026, 8, 6, tzinfo=UTC)

    assert td.is_recent_news("2026-07-30T00:00:00+00:00", now=now)
    assert not td.is_recent_news("2026-07-29T23:59:59+00:00", now=now)
    assert not td.is_recent_news(None, now=now)


def test_request_json_builds_url_with_params():
    mock_response = MagicMock()
    mock_response.read.return_value = b'{"status": "ok"}'
    mock_response.__enter__ = MagicMock(return_value=mock_response)
    mock_response.__exit__ = MagicMock(return_value=False)

    with patch(
        "trading_debate.utils.urlopen", return_value=mock_response
    ) as mock_urlopen:
        result = td.request_json("https://example.com/api", {"key": "value"})
    mock_urlopen.assert_called_once()
    assert result == {"status": "ok"}


def test_request_json_without_params():
    mock_response = MagicMock()
    mock_response.read.return_value = b'{"status": "ok"}'
    mock_response.__enter__ = MagicMock(return_value=mock_response)
    mock_response.__exit__ = MagicMock(return_value=False)

    with patch("trading_debate.utils.urlopen", return_value=mock_response):
        result = td.request_json("https://example.com/api")
    assert result == {"status": "ok"}


def test_request_json_retries_on_failure():
    ok_response = MagicMock()
    ok_response.read.return_value = b'{"status": "ok"}'
    ok_response.__enter__ = MagicMock(return_value=ok_response)
    ok_response.__exit__ = MagicMock(return_value=False)

    with patch(
        "trading_debate.utils.urlopen",
        side_effect=[ConnectionResetError, ok_response],
    ) as mock_urlopen:
        result = td.request_json("https://example.com/api")
    assert result == {"status": "ok"}
    assert mock_urlopen.call_count == 2


def test_request_json_raises_request_error_after_retries():
    with patch(
        "trading_debate.utils.urlopen",
        side_effect=ConnectionResetError,
    ) as mock_urlopen:
        with pytest.raises(td.RequestError):
            td.request_json("https://example.com/api", max_retries=2)
    assert mock_urlopen.call_count == 2
