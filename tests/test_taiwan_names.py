"""Tests for Taiwan Chinese company name resolution."""

from __future__ import annotations

from unittest.mock import patch

from trading_debate.taiwan_names import fetch_taiwan_company_name


@patch("trading_debate.taiwan_names.request_json")
def test_fetch_taiwan_company_name_returns_chinese_name(mock_request):
    mock_request.side_effect = [
        [{"公司代號": "3037", "公司名稱": "欣興電子股份有限公司"}],
        [],
        [],
    ]
    assert fetch_taiwan_company_name("3037.TW") == "欣興電子股份有限公司"


@patch("trading_debate.taiwan_names.request_json")
def test_fetch_taiwan_company_name_falls_back_to_tpex(mock_request):
    mock_request.side_effect = [
        [{"公司代號": "6841", "公司名稱": "台新藥股份有限公司"}],
    ]
    assert fetch_taiwan_company_name("6841.TWO") == "台新藥股份有限公司"


@patch("trading_debate.taiwan_names.request_json")
def test_fetch_taiwan_company_name_returns_none_when_not_found(mock_request):
    mock_request.side_effect = [[], [], []]
    assert fetch_taiwan_company_name("9999.TW") is None


def test_fetch_taiwan_company_name_returns_none_for_us_ticker():
    assert fetch_taiwan_company_name("AAPL") is None


@patch("trading_debate.taiwan_names.request_json")
def test_fetch_taiwan_company_name_uses_company_short_name(mock_request):
    mock_request.side_effect = [
        [{"公司代號": "2330", "公司簡稱": "台積電"}],
        [],
        [],
    ]
    assert fetch_taiwan_company_name("2330.TW") == "台積電"
