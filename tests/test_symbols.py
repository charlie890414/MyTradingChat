"""Tests for symbol normalization and Taiwan exchange resolution."""

from __future__ import annotations

from unittest.mock import patch

import pytest

import trading_debate as td

from .conftest import make_mock_ticker


@pytest.mark.parametrize(
    "symbol,expected",
    [
        ("1234.TW", "1234"),
        ("12345.TWO", "12345"),
        ("1234", "1234"),
        ("6789.TW", "6789"),
        ("AAPL", None),
    ],
)
def test_taiwan_code(symbol, expected):
    assert td.taiwan_code(symbol) == expected


@pytest.mark.parametrize(
    "symbol,expected",
    [
        ("3037", "3037.TW"),
        ("3037.tw", "3037.TW"),
        ("3037.TW", "3037.TW"),
        ("12345.TWO", "12345.TWO"),
        ("AAPL", "AAPL"),
        ("aapl", "AAPL"),
    ],
)
def test_normalize_symbol(symbol, expected):
    assert td.normalize_symbol(symbol) == expected


def test_resolve_taiwan_yahoo_symbol_keeps_us_ticker():
    assert td.resolve_taiwan_yahoo_symbol("AAPL") == "AAPL"


@patch("trading_debate.symbols.yfinance.Ticker")
def test_resolve_taiwan_yahoo_symbol_prefers_tw_when_data_exists(mock_ticker):
    mock_ticker.return_value = make_mock_ticker(has_data=True)
    assert td.resolve_taiwan_yahoo_symbol("3037") == "3037.TW"


@patch("trading_debate.symbols.yfinance.Ticker")
def test_resolve_taiwan_yahoo_symbol_prefers_tw_for_suffixed_symbol(mock_ticker):
    mock_ticker.return_value = make_mock_ticker(has_data=True)
    assert td.resolve_taiwan_yahoo_symbol("3037.TW") == "3037.TW"


@patch("trading_debate.symbols.yfinance.Ticker")
def test_resolve_taiwan_yahoo_symbol_falls_back_to_two(mock_ticker):
    tw_ticker = make_mock_ticker(has_data=False)
    two_ticker = make_mock_ticker(has_data=True)
    mock_ticker.side_effect = [tw_ticker, two_ticker]
    assert td.resolve_taiwan_yahoo_symbol("6841") == "6841.TWO"


@patch("trading_debate.symbols.yfinance.Ticker")
def test_resolve_taiwan_yahoo_symbol_retries_two_for_suffixed_tw(mock_ticker):
    tw_ticker = make_mock_ticker(has_data=False)
    two_ticker = make_mock_ticker(has_data=True)
    mock_ticker.side_effect = [tw_ticker, two_ticker]
    assert td.resolve_taiwan_yahoo_symbol("6841.TW") == "6841.TWO"


@patch("trading_debate.symbols.yfinance.Ticker")
def test_resolve_taiwan_yahoo_symbol_defaults_to_tw_when_neither_resolves(
    mock_ticker,
):
    mock_ticker.return_value = make_mock_ticker(has_data=False)
    assert td.resolve_taiwan_yahoo_symbol("9999") == "9999.TW"


@pytest.mark.parametrize(
    "symbol,info,chinese_name,expected",
    [
        ("AAPL", None, None, "AAPL"),
        ("aapl", {"longName": "Apple Inc."}, None, "Apple Inc."),
        (
            "BE",
            {"longName": "Bloom Energy Corporation"},
            None,
            "Bloom Energy Corporation",
        ),
        ("3037.TW", None, None, "3037.TW"),
        (
            "3037.TW",
            {"longName": "Unimicron Technology Corp."},
            None,
            "Unimicron Technology Corp.",
        ),
        ("3037.TW", {"shortName": "UNIMICRON"}, None, "UNIMICRON"),
        (
            "3037.TW",
            {"shortName": "UNIMICRON", "longName": "Unimicron Technology Corp."},
            None,
            "Unimicron Technology Corp.",
        ),
        ("3037.TW", {"longName": "Unimicron Technology Corp."}, "欣興電子", "欣興電子"),
    ],
)
def test_company_search_name(symbol, info, chinese_name, expected):
    assert td.company_search_name(symbol, info, chinese_name=chinese_name) == expected
