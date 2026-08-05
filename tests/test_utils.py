"""Tests for shared utility helpers."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from unittest.mock import MagicMock, patch

import pytest

import trading_debate as td


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


def test_date_range_days():
    start, end = td.date_range_days(365)
    end_date = datetime.fromisoformat(end)
    start_date = datetime.fromisoformat(start)
    assert (end_date.date() - start_date.date()).days == 365


def test_is_recent_news_requires_a_timestamp_within_30_days():
    now = datetime(2026, 8, 6, tzinfo=UTC)

    assert td.is_recent_news("2026-07-07T00:00:00+00:00", now=now)
    assert not td.is_recent_news("2026-07-06T23:59:59+00:00", now=now)
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
