"""Unit tests for trading_debate package."""

from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

import trading_debate as td


def test_utc_now_format():
    result = td.utc_now()
    parsed = datetime.fromisoformat(result)
    assert parsed.tzinfo == UTC
    assert "T" in result
    assert ":" in result


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


def _make_mock_ticker(has_data: bool):
    mock = MagicMock()
    if has_data:
        mock.get_info.return_value = {"longName": "Test Co", "currentPrice": 100.0}
    else:
        mock.get_info.return_value = {"trailingPegRatio": None}
    mock.history.return_value = MagicMock(empty=not has_data)
    return mock


def test_resolve_taiwan_yahoo_symbol_keeps_us_ticker():
    assert td.resolve_taiwan_yahoo_symbol("AAPL") == "AAPL"


@patch("trading_debate.finance.yfinance.Ticker")
def test_resolve_taiwan_yahoo_symbol_prefers_tw_when_data_exists(mock_ticker):
    mock_ticker.return_value = _make_mock_ticker(has_data=True)
    assert td.resolve_taiwan_yahoo_symbol("3037") == "3037.TW"


@patch("trading_debate.finance.yfinance.Ticker")
def test_resolve_taiwan_yahoo_symbol_prefers_tw_for_suffixed_symbol(mock_ticker):
    mock_ticker.return_value = _make_mock_ticker(has_data=True)
    assert td.resolve_taiwan_yahoo_symbol("3037.TW") == "3037.TW"


@patch("trading_debate.finance.yfinance.Ticker")
def test_resolve_taiwan_yahoo_symbol_falls_back_to_two(mock_ticker):
    tw_ticker = _make_mock_ticker(has_data=False)
    two_ticker = _make_mock_ticker(has_data=True)
    mock_ticker.side_effect = [tw_ticker, two_ticker]
    assert td.resolve_taiwan_yahoo_symbol("6841") == "6841.TWO"


@patch("trading_debate.finance.yfinance.Ticker")
def test_resolve_taiwan_yahoo_symbol_retries_two_for_suffixed_tw(mock_ticker):
    tw_ticker = _make_mock_ticker(has_data=False)
    two_ticker = _make_mock_ticker(has_data=True)
    mock_ticker.side_effect = [tw_ticker, two_ticker]
    assert td.resolve_taiwan_yahoo_symbol("6841.TW") == "6841.TWO"


@patch("trading_debate.finance.yfinance.Ticker")
def test_resolve_taiwan_yahoo_symbol_defaults_to_tw_when_neither_resolves(mock_ticker):
    mock_ticker.return_value = _make_mock_ticker(has_data=False)
    assert td.resolve_taiwan_yahoo_symbol("9999") == "9999.TW"


def test_as_json():
    data = {"key": "value", "num": 42, "bool": True, "none": None}
    result = td.as_json(data)
    parsed = json.loads(result)
    assert parsed == data


def test_as_json_sorted():
    result = td.as_json({"z": 1, "a": 2})
    parsed = json.loads(result)
    assert list(parsed.keys()) == ["a", "z"]


def test_connect(tmp_path: Path):
    db_path = tmp_path / "test.db"
    con = td.connect(db_path)
    assert isinstance(con, sqlite3.Connection)
    tables = con.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
    table_names = [row[0] for row in tables]
    assert "runs" in table_names
    assert "evidence" in table_names
    assert "contributions" in table_names
    con.close()


def test_connect_creates_directories(tmp_path: Path):
    db_path = tmp_path / "nested" / "dir" / "test.db"
    con = td.connect(db_path)
    assert db_path.parent.exists()
    con.close()


def test_connect_foreign_keys(tmp_path: Path):
    db_path = tmp_path / "test.db"
    con = td.connect(db_path)
    foreign_keys = con.execute("PRAGMA foreign_keys").fetchone()[0]
    assert foreign_keys == 1
    con.close()


def test_insert_evidence(tmp_path: Path):
    db_path = tmp_path / "test.db"
    con = td.connect(db_path)
    con.execute(
        "INSERT INTO runs(id, symbol, question, debate_rounds, created_at, status) VALUES (?, ?, ?, ?, ?, ?)",
        ("run-1", "AAPL", "Test question", 3, td.utc_now(), "active"),
    )
    td.insert_evidence(
        con,
        "run-1",
        "TestSource",
        "Test Title",
        {"key": "value"},
        url="https://example.com",
        published_at="2026-01-01T00:00:00+00:00",
    )
    con.commit()
    con.row_factory = sqlite3.Row
    rows = con.execute("SELECT * FROM evidence WHERE run_id = ?", ("run-1",)).fetchall()
    assert len(rows) == 1
    assert rows[0]["source"] == "TestSource"
    assert rows[0]["title"] == "Test Title"
    assert rows[0]["url"] == "https://example.com"
    payload = json.loads(rows[0]["payload_json"])
    assert payload == {"key": "value"}
    con.close()


def test_connector_status(tmp_path: Path):
    db_path = tmp_path / "test.db"
    con = td.connect(db_path)
    con.execute(
        "INSERT INTO runs(id, symbol, question, debate_rounds, created_at, status) VALUES (?, ?, ?, ?, ?, ?)",
        ("run-1", "AAPL", "Test", 3, td.utc_now(), "active"),
    )
    td.connector_status(con, "run-1", "Finnhub", "skipped", "Set FINNHUB_API_KEY")
    con.commit()
    con.row_factory = sqlite3.Row
    rows = con.execute("SELECT * FROM evidence WHERE run_id = ?", ("run-1",)).fetchall()
    assert len(rows) == 1
    assert rows[0]["source"] == "Finnhub"
    assert "skipped" in rows[0]["title"]
    payload = json.loads(rows[0]["payload_json"])
    assert payload["state"] == "skipped"
    assert payload["detail"] == "Set FINNHUB_API_KEY"
    con.close()


def test_cmd_init(tmp_path: Path):
    db_path = tmp_path / "test.db"
    args = MagicMock()
    args.db = db_path
    args.symbol = "AAPL"
    args.question = "Analyze AAPL"
    args.rounds = 3
    with patch("trading_debate.utils.as_json") as mock_json:
        mock_json.return_value = "{}"
        td.cmd_init(args)
    con = sqlite3.connect(db_path)
    con.row_factory = sqlite3.Row
    runs = con.execute("SELECT * FROM runs").fetchall()
    assert len(runs) == 1
    assert runs[0]["symbol"] == "AAPL"
    assert runs[0]["question"] == "Analyze AAPL"
    assert runs[0]["debate_rounds"] == 3
    assert runs[0]["status"] == "active"
    con.close()


def test_cmd_init_default_rounds(tmp_path: Path):
    db_path = tmp_path / "test.db"
    args = MagicMock()
    args.db = db_path
    args.symbol = "2330.TW"
    args.question = "Test"
    args.rounds = 3
    with patch("trading_debate.utils.as_json") as mock_json:
        mock_json.return_value = "{}"
        td.cmd_init(args)
    con = sqlite3.connect(db_path)
    con.row_factory = sqlite3.Row
    runs = con.execute("SELECT * FROM runs").fetchall()
    assert len(runs) == 1
    assert runs[0]["symbol"] == "2330.TW"
    con.close()


def test_cmd_init_normalizes_taiwan_code(tmp_path: Path):
    db_path = tmp_path / "test.db"
    args = MagicMock()
    args.db = db_path
    args.symbol = "3037"
    args.question = "Analyze Unimicron"
    args.rounds = 3
    with patch("trading_debate.utils.as_json") as mock_json:
        mock_json.return_value = "{}"
        td.cmd_init(args)
    con = sqlite3.connect(db_path)
    con.row_factory = sqlite3.Row
    runs = con.execute("SELECT * FROM runs").fetchall()
    assert len(runs) == 1
    assert runs[0]["symbol"] == "3037.TW"
    con.close()


def test_cmd_fetch_unknown_run(tmp_path: Path):
    args = MagicMock()
    args.db = tmp_path / "test.db"
    args.run_id = "nonexistent"
    with pytest.raises(SystemExit, match="Unknown run id"):
        td.cmd_fetch(args)


def test_cmd_fetch_valid_run(tmp_path: Path, capsys):
    import pandas as pd

    db_path = tmp_path / "test.db"
    con = td.connect(db_path)
    con.execute(
        "INSERT INTO runs(id, symbol, question, debate_rounds, created_at, status) VALUES (?, ?, ?, ?, ?, ?)",
        ("run-1", "AAPL", "Test", 3, td.utc_now(), "active"),
    )
    con.commit()
    con.close()

    idx = pd.DatetimeIndex([datetime(2025, 7, 28, tzinfo=UTC)])
    mock_history = pd.DataFrame(
        {
            "Open": [150.0],
            "High": [151.0],
            "Low": [149.0],
            "Close": [150.0],
            "Volume": [1000.0],
        },
        index=idx,
    )

    mock_ticker = MagicMock()
    mock_ticker.get_info.return_value = {
        "shortName": "Apple Inc.",
        "currentPrice": 150.0,
    }
    mock_ticker.history.return_value = mock_history
    mock_ticker.get_news.return_value = []

    args = MagicMock()
    args.db = db_path
    args.run_id = "run-1"
    args.news_limit = 10

    with patch("trading_debate.finance.yfinance.Ticker", return_value=mock_ticker):
        with patch("trading_debate.finance.fetch_alpha_vantage", return_value=0):
            with patch("trading_debate.finance.fetch_finnhub", return_value=0):
                with patch("trading_debate.finance.fetch_finmind", return_value=0):
                    with patch(
                        "trading_debate.finance.fetch_twse_mops", return_value=0
                    ):
                        with patch(
                            "trading_debate.finance.fetch_reddit_summary",
                            return_value=0,
                        ):
                            td.cmd_fetch(args)
    captured = capsys.readouterr()
    parsed = json.loads(captured.out.strip())
    assert parsed["run_id"] == "run-1"
    assert parsed["price"]["close"] == 150.0
    assert parsed["technicals"]["available"] is True


def test_cmd_fetch_updates_symbol_on_resolution(tmp_path: Path, capsys):
    import pandas as pd

    db_path = tmp_path / "test.db"
    con = td.connect(db_path)
    con.execute(
        "INSERT INTO runs(id, symbol, question, debate_rounds, created_at, status) VALUES (?, ?, ?, ?, ?, ?)",
        ("run-1", "6841", "Test", 3, td.utc_now(), "active"),
    )
    con.commit()
    con.close()

    idx = pd.DatetimeIndex([datetime(2025, 7, 28, tzinfo=UTC)])
    mock_history = pd.DataFrame(
        {
            "Open": [100.0],
            "High": [101.0],
            "Low": [99.0],
            "Close": [100.0],
            "Volume": [1000.0],
        },
        index=idx,
    )

    tw_ticker = MagicMock()
    tw_ticker.get_info.return_value = {"trailingPegRatio": None}
    tw_ticker.history.return_value = pd.DataFrame()
    two_ticker = MagicMock()
    two_ticker.get_info.return_value = {
        "longName": "OTC Test",
        "currentPrice": 100.0,
    }
    two_ticker.history.return_value = mock_history
    two_ticker.get_news.return_value = []

    args = MagicMock()
    args.db = db_path
    args.run_id = "run-1"
    args.news_limit = 10

    with patch("trading_debate.finance.yfinance.Ticker") as mock_ticker:
        mock_ticker.side_effect = [tw_ticker, two_ticker, two_ticker]
        with patch("trading_debate.finance.fetch_alpha_vantage", return_value=0):
            with patch("trading_debate.finance.fetch_finnhub", return_value=0):
                with patch("trading_debate.finance.fetch_finmind", return_value=0):
                    with patch(
                        "trading_debate.finance.fetch_twse_mops", return_value=0
                    ):
                        with patch(
                            "trading_debate.finance.fetch_reddit_summary",
                            return_value=0,
                        ):
                            td.cmd_fetch(args)
    captured = capsys.readouterr()
    parsed = json.loads(captured.out.strip())
    assert parsed["run_id"] == "run-1"
    assert parsed["price"]["close"] == 100.0

    con = sqlite3.connect(db_path)
    con.row_factory = sqlite3.Row
    run = con.execute("SELECT symbol FROM runs WHERE id = ?", ("run-1",)).fetchone()
    assert run["symbol"] == "6841.TWO"
    con.close()


def test_cmd_fetch_price_calculation(tmp_path: Path, capsys):
    import pandas as pd

    db_path = tmp_path / "test.db"
    con = td.connect(db_path)
    con.execute(
        "INSERT INTO runs(id, symbol, question, debate_rounds, created_at, status) VALUES (?, ?, ?, ?, ?, ?)",
        ("run-1", "AAPL", "Test", 3, td.utc_now(), "active"),
    )
    con.commit()
    con.close()

    idx = pd.DatetimeIndex(
        [datetime(2025, 7, 28, tzinfo=UTC), datetime(2025, 1, 1, tzinfo=UTC)]
    )
    mock_history = pd.DataFrame({"Close": [180.0, 100.0]}, index=idx)

    mock_ticker = MagicMock()
    mock_ticker.get_info.return_value = {"currentPrice": 180.0}
    mock_ticker.history.return_value = mock_history
    mock_ticker.get_news.return_value = []

    args = MagicMock()
    args.db = db_path
    args.run_id = "run-1"
    args.news_limit = 10

    with patch("trading_debate.finance.yfinance.Ticker", return_value=mock_ticker):
        with patch("trading_debate.finance.fetch_alpha_vantage", return_value=0):
            with patch("trading_debate.finance.fetch_finnhub", return_value=0):
                with patch("trading_debate.finance.fetch_finmind", return_value=0):
                    with patch(
                        "trading_debate.finance.fetch_twse_mops", return_value=0
                    ):
                        with patch(
                            "trading_debate.finance.fetch_reddit_summary",
                            return_value=0,
                        ):
                            td.cmd_fetch(args)
    captured = capsys.readouterr()
    parsed = json.loads(captured.out.strip())
    price = parsed["price"]
    assert price["close"] == 100.0
    assert price["return_1y"] == pytest.approx(100.0 / 180.0 - 1)
    assert price["high_1y"] == 180.0
    assert price["low_1y"] == 100.0


def test_cmd_context(tmp_path: Path, capsys):
    db_path = tmp_path / "test.db"
    con = td.connect(db_path)
    con.execute(
        "INSERT INTO runs(id, symbol, question, debate_rounds, created_at, status) VALUES (?, ?, ?, ?, ?, ?)",
        ("run-1", "AAPL", "Test", 3, td.utc_now(), "active"),
    )
    con.execute(
        "INSERT INTO evidence(run_id, source, title, url, published_at, payload_json, fetched_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (
            "run-1",
            "Yahoo Finance",
            "Test headline",
            "https://example.com",
            None,
            '{"key": "val"}',
            td.utc_now(),
        ),
    )
    con.commit()
    con.close()

    args = MagicMock()
    args.db = db_path
    args.run_id = "run-1"
    td.cmd_context(args)
    captured = capsys.readouterr()
    parsed = json.loads(captured.out.strip())
    assert parsed["run"]["symbol"] == "AAPL"
    assert len(parsed["evidence"]) == 1
    assert parsed["evidence"][0]["source"] == "Yahoo Finance"


def test_cmd_search(tmp_path: Path, capsys):
    db_path = tmp_path / "test.db"
    con = td.connect(db_path)
    con.execute(
        "INSERT INTO runs(id, symbol, question, debate_rounds, created_at, status) VALUES (?, ?, ?, ?, ?, ?)",
        ("run-1", "NVDA", "Analyze NVDA", 3, td.utc_now(), "active"),
    )
    con.commit()
    con.close()

    args = MagicMock()
    args.db = db_path
    args.query = "NVDA"
    args.limit = 10
    td.cmd_search(args)
    captured = capsys.readouterr()
    parsed = json.loads(captured.out.strip())
    assert len(parsed) == 1
    assert parsed[0]["symbol"] == "NVDA"


def test_cmd_search_no_results(tmp_path: Path, capsys):
    db_path = tmp_path / "test.db"
    con = td.connect(db_path)
    con.execute(
        "INSERT INTO runs(id, symbol, question, debate_rounds, created_at, status) VALUES (?, ?, ?, ?, ?, ?)",
        ("run-1", "AAPL", "Test", 3, td.utc_now(), "active"),
    )
    con.commit()
    con.close()

    args = MagicMock()
    args.db = db_path
    args.query = "XYZ"
    args.limit = 10
    td.cmd_search(args)
    captured = capsys.readouterr()
    parsed = json.loads(captured.out.strip())
    assert len(parsed) == 0


def test_date_range_is_exactly_365_days():
    end = datetime.now(UTC).date()
    start = end - timedelta(days=365)
    delta = end - start
    assert delta.days == 365


def test_start_date_iso_format():
    end = datetime.now(UTC).date()
    start = end - timedelta(days=365)
    assert "-" in start.isoformat()
    assert len(start.isoformat()) == 10


def test_connector_status_records_error(tmp_path: Path):
    db_path = tmp_path / "test.db"
    con = td.connect(db_path)
    con.execute(
        "INSERT INTO runs(id, symbol, question, debate_rounds, created_at, status) VALUES (?, ?, ?, ?, ?, ?)",
        ("run-1", "TPEI", "Test", 3, td.utc_now(), "active"),
    )
    td.connector_status(con, "run-1", "Finnhub", "error", "Rate limited")
    con.commit()
    con.row_factory = sqlite3.Row
    rows = con.execute("SELECT * FROM evidence WHERE run_id = ?", ("run-1",)).fetchall()
    assert len(rows) == 1
    payload = json.loads(rows[0]["payload_json"])
    assert payload["state"] == "error"
    assert payload["detail"] == "Rate limited"
    con.close()


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


def test_yahoo_history_uses_explicit_dates(tmp_path: Path, capsys):
    import pandas as pd

    db_path = tmp_path / "test.db"
    con = td.connect(db_path)
    con.execute(
        "INSERT INTO runs(id, symbol, question, debate_rounds, created_at, status) VALUES (?, ?, ?, ?, ?, ?)",
        ("run-1", "MSFT", "Test", 3, td.utc_now(), "active"),
    )
    con.commit()
    con.close()

    idx = pd.DatetimeIndex([datetime(2025, 7, 28, tzinfo=UTC)])
    mock_history = pd.DataFrame(
        {
            "Open": [100.0],
            "High": [101.0],
            "Low": [99.0],
            "Close": [100.0],
            "Volume": [1000.0],
        },
        index=idx,
    )

    mock_ticker = MagicMock()
    mock_ticker.get_info.return_value = {"currentPrice": 100.0}
    mock_ticker.history.return_value = mock_history
    mock_ticker.get_news.return_value = []

    args = MagicMock()
    args.db = db_path
    args.run_id = "run-1"
    args.news_limit = 10

    with patch("trading_debate.finance.yfinance.Ticker", return_value=mock_ticker):
        with patch("trading_debate.finance.fetch_alpha_vantage", return_value=0):
            with patch("trading_debate.finance.fetch_finnhub", return_value=0):
                with patch("trading_debate.finance.fetch_finmind", return_value=0):
                    with patch(
                        "trading_debate.finance.fetch_twse_mops", return_value=0
                    ):
                        with patch(
                            "trading_debate.finance.fetch_reddit_summary",
                            return_value=0,
                        ):
                            td.cmd_fetch(args)
    mock_ticker.history.assert_called_once()
    call_kwargs = mock_ticker.history.call_args.kwargs
    assert "start" in call_kwargs
    assert "end" in call_kwargs
    assert call_kwargs.get("period") is None


def test_cmd_render(tmp_path: Path, capsys):
    db_path = tmp_path / "test.db"
    con = td.connect(db_path)
    con.execute(
        "INSERT INTO runs(id, symbol, question, debate_rounds, created_at, status) VALUES (?, ?, ?, ?, ?, ?)",
        ("run-1", "AAPL", "Test", 3, td.utc_now(), "active"),
    )
    con.execute(
        "INSERT INTO evidence(run_id, source, title, url, published_at, payload_json, fetched_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (
            "run-1",
            "Yahoo Finance",
            "Fundamentals",
            None,
            None,
            '{"price": 150}',
            td.utc_now(),
        ),
    )
    con.execute(
        "INSERT INTO contributions(run_id, stage, actor, round_no, content, created_at) VALUES (?, ?, ?, ?, ?, ?)",
        (
            "run-1",
            "analysis",
            "Fundamentals Analyst",
            1,
            "Analysis content",
            td.utc_now(),
        ),
    )
    con.commit()
    con.close()

    args = MagicMock()
    args.db = db_path
    args.run_id = "run-1"
    args.reports = tmp_path / "reports"

    td.cmd_render(args)
    captured = capsys.readouterr()
    parsed = json.loads(captured.out.strip())
    assert parsed["run_id"] == "run-1"
    report_path = Path(parsed["report_path"])
    assert report_path.exists()
    content = report_path.read_text(encoding="utf-8")
    assert "AAPL" in content
    assert "Fundamentals Analyst" in content
    assert "Analysis content" in content


def test_render_evidence_empty():
    assert td.render_evidence([]) == "No evidence captured."


def test_render_evidence_with_rows(tmp_path: Path):
    db_path = tmp_path / "test.db"
    con = td.connect(db_path)
    con.execute(
        "INSERT INTO runs(id, symbol, question, debate_rounds, created_at, status) VALUES (?, ?, ?, ?, ?, ?)",
        ("run-1", "AAPL", "Test", 3, td.utc_now(), "active"),
    )
    con.execute(
        "INSERT INTO evidence(run_id, source, title, url, published_at, payload_json, fetched_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (
            "run-1",
            "Yahoo Finance",
            "Headline",
            "https://example.com",
            None,
            '{"key": "val"}',
            td.utc_now(),
        ),
    )
    con.row_factory = sqlite3.Row
    rows = con.execute("SELECT * FROM evidence WHERE run_id = ?", ("run-1",)).fetchall()
    result = td.render_evidence(rows)
    assert "Yahoo Finance" in result
    assert "Headline" in result
    assert "https://example.com" in result
    con.close()


def test_cmd_record_unknown_run(tmp_path: Path, capsys):
    args = MagicMock()
    args.db = tmp_path / "test.db"
    args.run_id = "nonexistent"
    args.content_file = None
    args.content = "Some content"
    args.stage = "analysis"
    args.actor = "Test Analyst"
    args.round = None
    with pytest.raises(SystemExit, match="Unknown run id"):
        td.cmd_record(args)


def test_cmd_record_valid(tmp_path: Path, capsys):
    db_path = tmp_path / "test.db"
    con = td.connect(db_path)
    con.execute(
        "INSERT INTO runs(id, symbol, question, debate_rounds, created_at, status) VALUES (?, ?, ?, ?, ?, ?)",
        ("run-1", "AAPL", "Test", 3, td.utc_now(), "active"),
    )
    con.commit()
    con.close()

    args = MagicMock()
    args.db = db_path
    args.run_id = "run-1"
    args.content_file = None
    args.content = "Analysis content"
    args.stage = "analysis"
    args.actor = "Fundamentals Analyst"
    args.round = None
    td.cmd_record(args)
    captured = capsys.readouterr()
    parsed = json.loads(captured.out.strip())
    assert parsed["recorded"] is True
    assert parsed["stage"] == "analysis"


def test_yahoo_history_does_not_use_period_arg(tmp_path: Path, capsys):
    """Confirm the fix: ticker.history is called with start/end, not period='1y'."""
    import pandas as pd

    db_path = tmp_path / "test.db"
    con = td.connect(db_path)
    con.execute(
        "INSERT INTO runs(id, symbol, question, debate_rounds, created_at, status) VALUES (?, ?, ?, ?, ?, ?)",
        ("run-1", "MSFT", "Test", 3, td.utc_now(), "active"),
    )
    con.commit()
    con.close()

    idx = pd.DatetimeIndex([datetime(2025, 7, 28, tzinfo=UTC)])
    mock_history = pd.DataFrame(
        {
            "Open": [100.0],
            "High": [101.0],
            "Low": [99.0],
            "Close": [100.0],
            "Volume": [1000.0],
        },
        index=idx,
    )

    mock_ticker = MagicMock()
    mock_ticker.get_info.return_value = {"currentPrice": 100.0}
    mock_ticker.history.return_value = mock_history
    mock_ticker.get_news.return_value = []

    args = MagicMock()
    args.db = db_path
    args.run_id = "run-1"
    args.news_limit = 10

    with patch("trading_debate.finance.yfinance.Ticker", return_value=mock_ticker):
        with patch("trading_debate.finance.fetch_alpha_vantage", return_value=0):
            with patch("trading_debate.finance.fetch_finnhub", return_value=0):
                with patch("trading_debate.finance.fetch_finmind", return_value=0):
                    with patch(
                        "trading_debate.finance.fetch_twse_mops", return_value=0
                    ):
                        with patch(
                            "trading_debate.finance.fetch_reddit_summary",
                            return_value=0,
                        ):
                            td.cmd_fetch(args)
    mock_ticker.history.assert_called_once()
    _, kwargs = mock_ticker.history.call_args
    assert "start" in kwargs
    assert "end" in kwargs
    assert kwargs.get("period") is None


def _make_history(n: int = 250, start_price: float = 100.0, end_price: float = 150.0):
    import pandas as pd

    dates = pd.date_range(end=datetime(2026, 7, 28, tzinfo=UTC), periods=n, freq="D")
    base = [start_price + (end_price - start_price) * i / (n - 1) for i in range(n)]
    closes = pd.Series(
        [
            price + (1 if i % 2 == 0 else -1) * 0.5 * (1 + (i % 7) * 0.1)
            for i, price in enumerate(base)
        ],
        index=dates,
    )
    df = pd.DataFrame(
        {
            "Open": closes - 0.5,
            "High": closes + 1.5,
            "Low": closes - 1.5,
            "Close": closes,
            "Volume": [1_000_000 + i * 1000 for i in range(n)],
        },
        index=dates,
    )
    return df


def test_compute_technicals_returns_full_indicator_set():
    history = _make_history(250)
    indicators = td.compute_technicals(history)
    assert indicators["available"] is True
    assert indicators["bars"] == 250
    assert indicators["ma_50"] is not None
    assert indicators["ma_200"] is not None
    assert indicators["rsi_14"] is not None
    assert 0 <= indicators["rsi_14"] <= 100
    assert indicators["macd"]["line"] is not None
    assert indicators["macd"]["signal"] is not None
    assert indicators["macd"]["histogram"] is not None
    bb = indicators["bollinger_20_2"]
    assert bb["middle"] is not None
    assert bb["upper"] > bb["middle"] > bb["lower"]
    assert indicators["kdj_k"] is not None
    assert indicators["kdj_d"] is not None
    assert indicators["kdj_j"] is not None
    assert indicators["high_52w"] is not None
    assert indicators["low_52w"] is not None
    assert indicators["avg_volume_20d"] is not None
    assert indicators["volume_trend_20d_vs_60d"] is not None
    sr = indicators["support_resistance"]
    assert sr["support"] is not None
    assert sr["resistance"] is not None


def test_compute_technicals_handles_short_history():
    history = _make_history(5)
    indicators = td.compute_technicals(history)
    assert indicators["available"] is True
    assert indicators["ma_50"] is None
    assert indicators["ma_200"] is None
    assert indicators["kdj_k"] is None


def test_compute_technicals_handles_empty_history():
    import pandas as pd

    empty = pd.DataFrame()
    indicators = td.compute_technicals(empty)
    assert indicators["available"] is False


def test_history_to_records_round_trips():
    history = _make_history(3)
    records = td.history_to_records(history)
    assert len(records) == 3
    for record in records:
        assert "date" in record
        for col in ("open", "high", "low", "close", "volume"):
            assert col in record


def test_cmd_fetch_persists_technicals_and_ohlcv(tmp_path: Path, capsys):

    db_path = tmp_path / "test.db"
    con = td.connect(db_path)
    con.execute(
        "INSERT INTO runs(id, symbol, question, debate_rounds, created_at, status) VALUES (?, ?, ?, ?, ?, ?)",
        ("run-1", "AAPL", "Test", 3, td.utc_now(), "active"),
    )
    con.commit()
    con.close()

    history = _make_history(60)
    mock_ticker = MagicMock()
    mock_ticker.get_info.return_value = {"currentPrice": 150.0}
    mock_ticker.history.return_value = history
    mock_ticker.get_news.return_value = []

    args = MagicMock()
    args.db = db_path
    args.run_id = "run-1"
    args.news_limit = 10

    with patch("trading_debate.finance.yfinance.Ticker", return_value=mock_ticker):
        with patch("trading_debate.finance.fetch_alpha_vantage", return_value=0):
            with patch("trading_debate.finance.fetch_finnhub", return_value=0):
                with patch("trading_debate.finance.fetch_finmind", return_value=0):
                    with patch(
                        "trading_debate.finance.fetch_twse_mops", return_value=0
                    ):
                        with patch(
                            "trading_debate.finance.fetch_reddit_summary",
                            return_value=0,
                        ):
                            td.cmd_fetch(args)

    con = sqlite3.connect(db_path)
    con.row_factory = sqlite3.Row
    titles = [
        row["title"]
        for row in con.execute(
            "SELECT title FROM evidence WHERE run_id = ? ORDER BY id", ("run-1",)
        ).fetchall()
    ]
    assert "Technical indicators (from daily OHLCV)" in titles
    assert "Daily OHLCV history" in titles
    payload_row = con.execute(
        "SELECT payload_json FROM evidence WHERE run_id = ? AND title = ?",
        ("run-1", "Daily OHLCV history"),
    ).fetchone()
    payload = json.loads(payload_row["payload_json"])
    assert payload["bars"] == 60
    assert len(payload["records"]) == 60
    first = payload["records"][0]
    for col in ("open", "high", "low", "close", "volume"):
        assert col in first
    con.close()


def test_cmd_fetch_technicals_output_includes_all_indicators(tmp_path: Path, capsys):
    history = _make_history(250)
    db_path = tmp_path / "test.db"
    con = td.connect(db_path)
    con.execute(
        "INSERT INTO runs(id, symbol, question, debate_rounds, created_at, status) VALUES (?, ?, ?, ?, ?, ?)",
        ("run-1", "AAPL", "Test", 3, td.utc_now(), "active"),
    )
    con.commit()
    con.close()

    mock_ticker = MagicMock()
    mock_ticker.get_info.return_value = {"currentPrice": 150.0}
    mock_ticker.history.return_value = history
    mock_ticker.get_news.return_value = []

    args = MagicMock()
    args.db = db_path
    args.run_id = "run-1"
    args.news_limit = 10

    with patch("trading_debate.finance.yfinance.Ticker", return_value=mock_ticker):
        with patch("trading_debate.finance.fetch_alpha_vantage", return_value=0):
            with patch("trading_debate.finance.fetch_finnhub", return_value=0):
                with patch("trading_debate.finance.fetch_finmind", return_value=0):
                    with patch(
                        "trading_debate.finance.fetch_twse_mops", return_value=0
                    ):
                        with patch(
                            "trading_debate.finance.fetch_reddit_summary",
                            return_value=0,
                        ):
                            td.cmd_fetch(args)
    captured = capsys.readouterr()
    parsed = json.loads(captured.out.strip())
    techs = parsed["technicals"]
    assert techs["available"] is True
    assert techs["ma_50"] is not None
    assert techs["ma_200"] is not None
    assert techs["rsi_14"] is not None
    assert techs["macd"]["line"] is not None
    assert techs["bollinger_20_2"]["middle"] is not None
    assert techs["kdj_k"] is not None
    assert techs["high_52w"] is not None
    assert techs["low_52w"] is not None
    assert techs["support_resistance"]["support"] is not None
    assert techs["support_resistance"]["resistance"] is not None
    assert techs["avg_volume_20d"] is not None
    assert techs["volume_trend_20d_vs_60d"] is not None


def test_cmd_fetch_skips_technicals_when_no_daily_data(tmp_path: Path, capsys):
    import pandas as pd

    db_path = tmp_path / "test.db"
    con = td.connect(db_path)
    con.execute(
        "INSERT INTO runs(id, symbol, question, debate_rounds, created_at, status) VALUES (?, ?, ?, ?, ?, ?)",
        ("run-1", "AAPL", "Test", 3, td.utc_now(), "active"),
    )
    con.commit()
    con.close()

    empty_history = pd.DataFrame()
    mock_ticker = MagicMock()
    mock_ticker.get_info.return_value = {"currentPrice": 100.0}
    mock_ticker.history.return_value = empty_history
    mock_ticker.get_news.return_value = []

    args = MagicMock()
    args.db = db_path
    args.run_id = "run-1"
    args.news_limit = 10

    with patch("trading_debate.finance.yfinance.Ticker", return_value=mock_ticker):
        with patch("trading_debate.finance.fetch_alpha_vantage", return_value=0):
            with patch("trading_debate.finance.fetch_finnhub", return_value=0):
                with patch("trading_debate.finance.fetch_finmind", return_value=0):
                    with patch(
                        "trading_debate.finance.fetch_twse_mops", return_value=0
                    ):
                        with patch(
                            "trading_debate.finance.fetch_reddit_summary",
                            return_value=0,
                        ):
                            td.cmd_fetch(args)
    captured = capsys.readouterr()
    parsed = json.loads(captured.out.strip())
    assert parsed["technicals"]["available"] is False
