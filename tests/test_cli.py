"""Tests for the trading-debate CLI commands."""

from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

import trading_debate as td
from trading_debate.cli import _MAX_WORKERS

from .conftest import make_history, make_mock_ticker, make_yahoo_result


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


def test_cmd_fetch_valid_run(tmp_path: Path, capsys, empty_connectors):
    db_path = tmp_path / "test.db"
    con = td.connect(db_path)
    con.execute(
        "INSERT INTO runs(id, symbol, question, debate_rounds, created_at, status) "
        "VALUES (?, ?, ?, ?, ?, ?)",
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

    with patch(
        "trading_debate.connectors.yahoo.yfinance.Ticker", return_value=mock_ticker
    ):
        td.cmd_fetch(args)
    captured = capsys.readouterr()
    parsed = json.loads(captured.out.strip())
    assert parsed["run_id"] == "run-1"
    assert parsed["price"]["close"] == 150.0
    assert parsed["technicals"]["available"] is True


def test_cmd_fetch_updates_symbol_on_resolution(
    tmp_path: Path, capsys, empty_connectors
):
    db_path = tmp_path / "test.db"
    con = td.connect(db_path)
    con.execute(
        "INSERT INTO runs(id, symbol, question, debate_rounds, created_at, status) "
        "VALUES (?, ?, ?, ?, ?, ?)",
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

    tw_ticker = make_mock_ticker(has_data=False)
    two_ticker = MagicMock()
    two_ticker.get_info.return_value = {
        "longName": "OTC Test",
        "currentPrice": 100.0,
    }
    two_ticker.history.return_value = mock_history
    two_ticker.get_news.return_value = []

    def ticker_for(symbol):
        if symbol.endswith(".TWO"):
            return two_ticker
        if symbol.endswith(".TW"):
            return tw_ticker
        raise ValueError(symbol)

    args = MagicMock()
    args.db = db_path
    args.run_id = "run-1"
    args.news_limit = 10

    with patch("trading_debate.symbols.yfinance.Ticker", side_effect=ticker_for):
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


def test_cmd_fetch_price_calculation(tmp_path: Path, capsys, empty_connectors):
    db_path = tmp_path / "test.db"
    con = td.connect(db_path)
    con.execute(
        "INSERT INTO runs(id, symbol, question, debate_rounds, created_at, status) "
        "VALUES (?, ?, ?, ?, ?, ?)",
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

    with patch(
        "trading_debate.connectors.yahoo.yfinance.Ticker", return_value=mock_ticker
    ):
        td.cmd_fetch(args)
    captured = capsys.readouterr()
    parsed = json.loads(captured.out.strip())
    price = parsed["price"]
    assert price["close"] == 100.0
    assert price["return_1y"] == pytest.approx(100.0 / 180.0 - 1)
    assert price["high_1y"] == 180.0
    assert price["low_1y"] == 100.0


def test_cmd_fetch_persists_technicals_and_ohlcv(
    tmp_path: Path, capsys, empty_connectors
):
    db_path = tmp_path / "test.db"
    con = td.connect(db_path)
    con.execute(
        "INSERT INTO runs(id, symbol, question, debate_rounds, created_at, status) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        ("run-1", "AAPL", "Test", 3, td.utc_now(), "active"),
    )
    con.commit()
    con.close()

    history = make_history(60)
    mock_ticker = MagicMock()
    mock_ticker.get_info.return_value = {"currentPrice": 150.0}
    mock_ticker.history.return_value = history
    mock_ticker.get_news.return_value = []

    args = MagicMock()
    args.db = db_path
    args.run_id = "run-1"
    args.news_limit = 10

    with patch(
        "trading_debate.connectors.yahoo.yfinance.Ticker", return_value=mock_ticker
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


def test_cmd_fetch_technicals_output_includes_all_indicators(
    tmp_path: Path, capsys, empty_connectors
):
    history = make_history(250)
    db_path = tmp_path / "test.db"
    con = td.connect(db_path)
    con.execute(
        "INSERT INTO runs(id, symbol, question, debate_rounds, created_at, status) "
        "VALUES (?, ?, ?, ?, ?, ?)",
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

    with patch(
        "trading_debate.connectors.yahoo.yfinance.Ticker", return_value=mock_ticker
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


def test_cmd_fetch_skips_technicals_when_no_daily_data(
    tmp_path: Path, capsys, empty_connectors
):
    db_path = tmp_path / "test.db"
    con = td.connect(db_path)
    con.execute(
        "INSERT INTO runs(id, symbol, question, debate_rounds, created_at, status) "
        "VALUES (?, ?, ?, ?, ?, ?)",
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

    with patch(
        "trading_debate.connectors.yahoo.yfinance.Ticker", return_value=mock_ticker
    ):
        td.cmd_fetch(args)
    captured = capsys.readouterr()
    parsed = json.loads(captured.out.strip())
    assert parsed["technicals"]["available"] is False


def test_yahoo_history_uses_explicit_dates(tmp_path: Path, capsys, empty_connectors):
    db_path = tmp_path / "test.db"
    con = td.connect(db_path)
    con.execute(
        "INSERT INTO runs(id, symbol, question, debate_rounds, created_at, status) "
        "VALUES (?, ?, ?, ?, ?, ?)",
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

    with patch(
        "trading_debate.connectors.yahoo.yfinance.Ticker", return_value=mock_ticker
    ):
        td.cmd_fetch(args)
    mock_ticker.history.assert_called_once()
    call_kwargs = mock_ticker.history.call_args.kwargs
    assert "start" in call_kwargs
    assert "end" in call_kwargs
    assert call_kwargs.get("period") is None


def test_yahoo_history_does_not_use_period_arg(
    tmp_path: Path, capsys, empty_connectors
):
    """Confirm the fix: ticker.history is called with start/end, not period='1y'."""
    db_path = tmp_path / "test.db"
    con = td.connect(db_path)
    con.execute(
        "INSERT INTO runs(id, symbol, question, debate_rounds, created_at, status) "
        "VALUES (?, ?, ?, ?, ?, ?)",
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

    with patch(
        "trading_debate.connectors.yahoo.yfinance.Ticker", return_value=mock_ticker
    ):
        td.cmd_fetch(args)
    mock_ticker.history.assert_called_once()
    _, kwargs = mock_ticker.history.call_args
    assert "start" in kwargs
    assert "end" in kwargs
    assert kwargs.get("period") is None


def test_cmd_fetch_records_connector_errors(tmp_path: Path, capsys):
    db_path = tmp_path / "test.db"
    con = td.connect(db_path)
    con.execute(
        "INSERT INTO runs(id, symbol, question, debate_rounds, created_at, status) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        ("run-1", "AAPL", "Test", 3, td.utc_now(), "active"),
    )
    con.commit()
    con.close()

    def failing_connector(run_id, symbol, limit):
        raise RuntimeError("provider down")

    result = make_yahoo_result(
        "run-1",
        make_history(5),
        news=[{"title": "Yahoo news"}],
    )
    with patch("trading_debate.cli.fetch_yahoo", return_value=result):
        with patch("trading_debate.cli.CONNECTORS", {"Bad Source": failing_connector}):
            args = MagicMock()
            args.db = db_path
            args.run_id = "run-1"
            args.news_limit = 10
            td.cmd_fetch(args)

    captured = capsys.readouterr()
    parsed = json.loads(captured.out.strip())
    assert parsed["connector_errors"] == {"Bad Source": "provider down"}

    con = sqlite3.connect(db_path)
    con.row_factory = sqlite3.Row
    status_titles = [
        row["title"]
        for row in con.execute(
            "SELECT title FROM evidence WHERE run_id = ? AND source = ?",
            ("run-1", "Bad Source"),
        ).fetchall()
    ]
    assert "Connector error" in status_titles
    con.close()


def test_cmd_fetch_yahoo_failure(tmp_path: Path, capsys):
    db_path = tmp_path / "test.db"
    con = td.connect(db_path)
    con.execute(
        "INSERT INTO runs(id, symbol, question, debate_rounds, created_at, status) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        ("run-1", "AAPL", "Test", 3, td.utc_now(), "active"),
    )
    con.commit()
    con.close()

    with patch(
        "trading_debate.cli.fetch_yahoo",
        side_effect=RuntimeError("yahoo unavailable"),
    ):
        with patch("trading_debate.cli.CONNECTORS", {}):
            args = MagicMock()
            args.db = db_path
            args.run_id = "run-1"
            args.news_limit = 10
            td.cmd_fetch(args)

    captured = capsys.readouterr()
    parsed = json.loads(captured.out.strip())
    assert parsed["yahoo_error"] == "yahoo unavailable"
    assert parsed["price"] is None
    assert parsed["technicals"] is None


def test_cmd_context(tmp_path: Path, capsys):
    db_path = tmp_path / "test.db"
    con = td.connect(db_path)
    con.execute(
        "INSERT INTO runs(id, symbol, question, debate_rounds, created_at, status) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        ("run-1", "AAPL", "Test", 3, td.utc_now(), "active"),
    )
    con.execute(
        "INSERT INTO evidence(run_id, source, title, url, published_at, payload_json, fetched_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
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
        "INSERT INTO runs(id, symbol, question, debate_rounds, created_at, status) "
        "VALUES (?, ?, ?, ?, ?, ?)",
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
        "INSERT INTO runs(id, symbol, question, debate_rounds, created_at, status) "
        "VALUES (?, ?, ?, ?, ?, ?)",
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


def test_cmd_render(tmp_path: Path, capsys):
    db_path = tmp_path / "test.db"
    con = td.connect(db_path)
    con.execute(
        "INSERT INTO runs(id, symbol, question, debate_rounds, created_at, status) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        ("run-1", "AAPL", "Test", 3, td.utc_now(), "active"),
    )
    con.execute(
        "INSERT INTO evidence(run_id, source, title, url, published_at, payload_json, fetched_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
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
        "INSERT INTO contributions(run_id, stage, actor, round_no, content, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?)",
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
        "INSERT INTO runs(id, symbol, question, debate_rounds, created_at, status) "
        "VALUES (?, ?, ?, ?, ?, ?)",
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


def test_max_workers_is_limited():
    assert _MAX_WORKERS <= 4
