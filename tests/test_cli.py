"""Tests for the trading-debate CLI commands."""

from __future__ import annotations

import json
import sqlite3
import sys
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

import trading_debate as td
from trading_debate.cli import (
    _MAX_WORKERS,
    _enrich_news_with_article_text,
    _filter_relevant_news,
)
from trading_debate.models import EvidenceItem

from .conftest import make_history, make_mock_ticker, make_yahoo_result


def _create_record_run(db_path: Path, *, rounds: int = 1) -> None:
    with td.connect(db_path) as con:
        con.execute(
            "INSERT INTO runs(id, symbol, question, debate_rounds, created_at, status) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            ("run-1", "AAPL", "Test", rounds, td.utc_now(), "active"),
        )
        con.execute(
            "INSERT INTO evidence(run_id, source, title, url, published_at, payload_json, fetched_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                "run-1",
                "Yahoo Finance",
                "Price evidence",
                None,
                None,
                "{}",
                td.utc_now(),
            ),
        )


def _record_args(db_path: Path, **overrides: object) -> MagicMock:
    args = MagicMock()
    args.db = db_path
    args.run_id = "run-1"
    args.content_file = None
    args.content_stdin = False
    args.content = "content"
    args.stage = "analysis"
    args.actor = "Fundamentals Analyst"
    args.round = None
    args.force = False
    args.verdict = None
    args.confidence = None
    args.abstain = False
    args.replace = False
    for key, value in overrides.items():
        setattr(args, key, value)
    if not isinstance(getattr(args, "summary_json", None), str):
        actor = str(args.actor).lower()
        actor = {
            "fundamentals analyst": "fundamentals",
            "technical analyst": "technical",
            "news analyst": "news",
            "sentiment analyst": "sentiment",
            "news content": "news_content",
            "bull researcher": "bull",
            "bear researcher": "bear",
            "investment committee": "committee",
        }.get(actor, actor)
        payload = {
            "actor": actor,
            "confidence": "medium",
            "evidence_ids": ["EVID-0001"],
            "critical_evidence_ids": ["EVID-0001"],
        }
        if args.stage == "analysis":
            payload.update(stance="neutral", evidence_gaps=[])
            if actor == "news_content":
                payload["article_summaries"] = [
                    {
                        "evidence_id": "EVID-0001",
                        "body_available": True,
                        "event_date": "2026-08-08",
                        "source_quality": "high",
                        "summary": "event",
                        "materiality": "medium",
                    }
                ]
        elif args.stage == "debate":
            payload.update(
                round=args.round,
                stance="bullish" if actor == "bull" else "bearish",
                opposing_claims=[],
                updated_claims=[],
                unresolved_disagreements=[],
            )
        else:
            payload.update(
                recommendation=args.verdict or "hold",
                confidence=args.confidence or "medium",
                fetch_time=td.utc_now(),
            )
        args.summary_json = json.dumps(payload)
    return args


def _record_all_analyses(db_path: Path) -> None:
    for actor in ("news_content", "fundamentals", "technical", "news", "sentiment"):
        td.cmd_record(_record_args(db_path, actor=actor, content=f"{actor} report"))


def test_cmd_record_rejects_invalid_news_content_summary(tmp_path: Path):
    db_path = tmp_path / "test.db"
    _create_record_run(db_path)
    content = (
        "## Machine-readable summary\n```json\n"
        '{"actor":"news_content","stance":"neutral",'
        '"confidence":"medium","evidence_ids":["EVID-0001"],'
        '"evidence_gaps":[],"article_summaries":[{'
        '"evidence_id":"EVID-0001","body_available":true,'
        '"event_date":"2026-08-08","source_quality":"high",'
        '"summary":"event","materiality：**medium**；extra": "medium"}]}'
        "\n```"
    )

    with pytest.raises(SystemExit, match="Invalid news content summary"):
        td.cmd_record(
            _record_args(
                db_path,
                actor="news_content",
                content="news content",
                summary_json=content.removeprefix(
                    "## Machine-readable summary\n```json\n"
                ).removesuffix("\n```"),
            )
        )

    with td.connect(db_path) as con:
        assert (
            con.execute(
                "SELECT COUNT(*) FROM contributions WHERE run_id = 'run-1'"
            ).fetchone()[0]
            == 0
        )


def test_cmd_init(tmp_path: Path):
    db_path = tmp_path / "test.db"
    args = MagicMock()
    args.db = db_path
    args.symbol = "AAPL"
    args.question = "Analyze AAPL"
    args.rounds = 3
    args.run_id = None
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
    args.run_id = None
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
    args.run_id = None
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

    with td.connect(db_path) as con:
        batch = con.execute(
            "SELECT status, resolved_symbol FROM evidence_batches WHERE run_id = 'run-1'"
        ).fetchone()
        evidence_batch_ids = con.execute(
            "SELECT DISTINCT batch_id FROM evidence WHERE run_id = 'run-1'"
        ).fetchall()
    assert batch["status"] == "completed"
    assert batch["resolved_symbol"] == "AAPL"
    assert len(evidence_batch_ids) == 1
    assert evidence_batch_ids[0]["batch_id"]
    captured = capsys.readouterr()
    parsed = json.loads(captured.out.strip())
    assert parsed["run_id"] == "run-1"
    assert parsed["price"]["close"] == 150.0
    assert parsed["technicals"]["available"] is True


def test_cmd_fetch_filters_irrelevant_news(tmp_path: Path, capsys):
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
    mock_ticker = MagicMock()
    mock_ticker.get_info.return_value = {
        "shortName": "Apple Inc.",
        "currentPrice": 150.0,
    }
    mock_ticker.history.return_value = pd.DataFrame(
        {
            "Open": [150.0],
            "High": [151.0],
            "Low": [149.0],
            "Close": [150.0],
            "Volume": [1000.0],
        },
        index=idx,
    )
    mock_ticker.get_news.return_value = []

    def news_connector(*args, **kwargs):
        return [
            EvidenceItem(
                run_id="run-1",
                source="Google News RSS",
                title="Apple launches a new service",
                payload={"summary": "Apple expands subscriptions."},
                published_at="2026-08-08T10:00:00+00:00",
            ),
            EvidenceItem(
                run_id="run-1",
                source="Google News RSS",
                title="Microsoft reports cloud growth",
                payload={"summary": "Azure revenue grew."},
                published_at="2026-08-08T10:00:00+00:00",
            ),
        ]

    args = MagicMock(db=db_path, run_id="run-1", news_limit=10)
    with (
        patch("trading_debate.cli.CONNECTORS", {"News": news_connector}),
        patch(
            "trading_debate.connectors.yahoo.yfinance.Ticker", return_value=mock_ticker
        ),
    ):
        td.cmd_fetch(args)
    capsys.readouterr()

    with td.connect(db_path) as con:
        titles = [row[0] for row in con.execute("SELECT title FROM evidence")]
    assert "Apple launches a new service" in titles
    assert "Microsoft reports cloud growth" not in titles


def test_article_text_can_establish_news_relevance():
    item = EvidenceItem(
        run_id="run-1",
        source="Google News RSS",
        title="Custom chip market update",
        payload={"summary": "Industry demand is growing."},
        url="https://example.com/article",
        published_at="2026-08-08T10:00:00+00:00",
    )
    with patch(
        "trading_debate.cli.fetch_article_text_result",
        return_value=(
            "Broadcom expects custom-chip demand to grow.",
            {"state": "available"},
        ),
    ):
        enriched = _enrich_news_with_article_text([item], "AVGO", "Broadcom Inc.")

    relevant = _filter_relevant_news(enriched, "AVGO", "Broadcom Inc.")
    assert relevant == [item]
    assert item.payload["article_text"].startswith("Broadcom")
    assert item.payload["article_text_status"]["state"] == "available"


def test_article_text_attempts_every_url_and_records_failures():
    items = [
        EvidenceItem(
            run_id="run-1",
            source="Google News RSS",
            title=f"Story {index}",
            payload={},
            url=f"https://example.com/{index}",
        )
        for index in range(13)
    ]

    def fetch(url: str) -> tuple[str | None, dict[str, str]]:
        if url.endswith("/3"):
            return None, {"state": "failed", "reason": "timeout"}
        return f"body for {url}", {"state": "available"}

    with patch(
        "trading_debate.cli.fetch_article_text_result", side_effect=fetch
    ) as mocked:
        _enrich_news_with_article_text(items, "AAPL", "Apple Inc.")

    assert mocked.call_count == 13
    assert items[3].payload["article_text_status"] == {
        "state": "failed",
        "reason": "timeout",
    }
    assert items[12].payload["article_text_status"]["state"] == "available"


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

    def ticker_for(symbol, **kwargs):
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


def test_cmd_fetch_uses_chinese_company_name_for_taiwan_stock(
    tmp_path: Path, capsys, empty_connectors
):
    db_path = tmp_path / "test.db"
    con = td.connect(db_path)
    con.execute(
        "INSERT INTO runs(id, symbol, question, debate_rounds, created_at, status) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        ("run-1", "3037.TW", "Test", 3, td.utc_now(), "active"),
    )
    con.commit()
    con.close()

    history = make_history(5)
    mock_ticker = MagicMock()
    mock_ticker.get_info.return_value = {
        "longName": "Unimicron Technology Corp.",
        "currentPrice": 716.0,
    }
    mock_ticker.history.return_value = history
    mock_ticker.get_news.return_value = []

    captured_company_name = None

    def capture_connector(run_id, symbol, limit, *, company_name=None):
        nonlocal captured_company_name
        captured_company_name = company_name
        return []

    args = MagicMock()
    args.db = db_path
    args.run_id = "run-1"
    args.news_limit = 10

    with patch("trading_debate.cli.fetch_taiwan_company_name", return_value="欣興電子"):
        with patch(
            "trading_debate.connectors.yahoo.yfinance.Ticker", return_value=mock_ticker
        ):
            with patch.dict(
                "trading_debate.cli.CONNECTORS",
                {"Google News RSS": capture_connector},
                clear=True,
            ):
                td.cmd_fetch(args)

    assert captured_company_name == "欣興電子"
    captured = capsys.readouterr()
    parsed = json.loads(captured.out.strip())
    assert parsed["run_id"] == "run-1"


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

    def failing_connector(run_id, symbol, limit, *, company_name=None):
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
            "Fundamentals snapshot",
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
    args.role = "fundamentals"
    td.cmd_context(args)
    captured = capsys.readouterr()
    parsed = json.loads(captured.out.strip())
    assert parsed["run"]["symbol"] == "AAPL"
    assert len(parsed["evidence"]) == 1
    assert parsed["evidence"][0]["source"] == "Yahoo Finance"
    assert "payload_json" not in parsed["evidence"][0]


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
    created_at = "2026-07-30T12:00:00+00:00"
    con.execute(
        "INSERT INTO runs(id, symbol, question, debate_rounds, created_at, status) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        ("run-1", "AAPL", "Test", 3, created_at, "active"),
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
            '{"price": 150, "article_text": "Full article body"}',
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
    assert parsed["report_url"] == "/runs/run-1/report"
    assert not args.reports.exists()
    with td.connect(db_path) as con:
        run = con.execute(
            "SELECT status, report_path FROM runs WHERE id = 'run-1'"
        ).fetchone()
    assert run["status"] == "incomplete"
    assert run["report_path"] is None
    from trading_debate.render import render_report_markdown

    with td.connect(db_path) as con:
        run = con.execute("SELECT * FROM runs WHERE id = 'run-1'").fetchone()
        evidence = con.execute(
            "SELECT * FROM evidence WHERE run_id = 'run-1'"
        ).fetchall()
        parts = con.execute(
            "SELECT * FROM contributions WHERE run_id = 'run-1'"
        ).fetchall()
    content = render_report_markdown(run, evidence, parts).markdown
    assert "AAPL" in content
    assert "Fundamentals Analyst" in content
    assert "Analysis content" in content
    assert "Full article body" not in content

    td.cmd_render(args)
    assert json.loads(capsys.readouterr().out)["report_url"] == "/runs/run-1/report"


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
    con.execute(
        "INSERT INTO evidence(run_id, source, title, url, published_at, payload_json, fetched_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        ("run-1", "Yahoo Finance", "Price evidence", None, None, "{}", td.utc_now()),
    )
    con.commit()
    con.close()

    args = _record_args(
        db_path,
        content="Analysis content",
        summary_json=json.dumps(
            {
                "actor": "fundamentals",
                "confidence": "medium",
                "evidence_ids": [],
                "critical_evidence_ids": [],
                "stance": "neutral",
                "evidence_gaps": [],
            }
        ),
    )
    td.cmd_record(args)
    captured = capsys.readouterr()
    parsed = json.loads(captured.out.strip())
    assert parsed["recorded"] is True
    assert parsed["stage"] == "analysis"


def test_cmd_record_reads_content_from_stdin(tmp_path: Path, capsys):
    db_path = tmp_path / "test.db"
    _create_record_run(db_path)
    args = _record_args(db_path, content=None, content_file=None, content_stdin=True)

    with patch.object(sys, "stdin") as stdin:
        stdin.read.return_value = "stdin report"
        td.cmd_record(args)

    assert json.loads(capsys.readouterr().out)["record_status"] == "created"
    with td.connect(db_path) as con:
        row = con.execute("SELECT content FROM contributions").fetchone()
    assert row["content"] == "stdin report"


def test_cmd_record_requires_evidence(tmp_path: Path):
    db_path = tmp_path / "test.db"
    con = td.connect(db_path)
    con.execute(
        "INSERT INTO runs(id, symbol, question, debate_rounds, created_at, status) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        ("run-1", "AAPL", "Test", 3, td.utc_now(), "active"),
    )
    con.commit()
    con.close()

    args = _record_args(
        db_path,
        content="Analysis content",
        summary_json=json.dumps(
            {
                "actor": "fundamentals",
                "confidence": "medium",
                "evidence_ids": [],
                "critical_evidence_ids": [],
                "stance": "neutral",
                "evidence_gaps": [],
            }
        ),
    )
    with pytest.raises(SystemExit, match="no evidence"):
        td.cmd_record(args)


def test_cmd_record_force_allows_empty_run(tmp_path: Path, capsys):
    db_path = tmp_path / "test.db"
    con = td.connect(db_path)
    con.execute(
        "INSERT INTO runs(id, symbol, question, debate_rounds, created_at, status) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        ("run-1", "AAPL", "Test", 3, td.utc_now(), "active"),
    )
    con.commit()
    con.close()

    args = _record_args(
        db_path,
        content="Analysis content",
        force=True,
        summary_json=json.dumps(
            {
                "actor": "fundamentals",
                "confidence": "medium",
                "evidence_ids": [],
                "critical_evidence_ids": [],
                "stance": "neutral",
                "evidence_gaps": [],
            }
        ),
    )
    td.cmd_record(args)
    captured = capsys.readouterr()
    parsed = json.loads(captured.out.strip())
    assert parsed["recorded"] is True


def test_cmd_init_existing_run_id_is_idempotent(tmp_path: Path, capsys):
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
    td.cmd_init(args)
    captured = capsys.readouterr()
    parsed = json.loads(captured.out.strip())
    assert parsed["id"] == "run-1"

    con = sqlite3.connect(db_path)
    con.row_factory = sqlite3.Row
    runs = con.execute("SELECT * FROM runs").fetchall()
    assert len(runs) == 1
    con.close()


def test_cmd_init_unknown_run_id_errors(tmp_path: Path):
    args = MagicMock()
    args.db = tmp_path / "test.db"
    args.run_id = "nonexistent"
    with pytest.raises(SystemExit, match="Unknown run id"):
        td.cmd_init(args)


def test_cmd_init_requires_symbol_and_question(tmp_path: Path):
    args = MagicMock()
    args.db = tmp_path / "test.db"
    args.run_id = None
    args.symbol = None
    args.question = "Test"
    args.rounds = 3
    with pytest.raises(SystemExit, match="init requires"):
        td.cmd_init(args)


def test_cmd_runs_lists_counts(tmp_path: Path, capsys):
    db_path = tmp_path / "test.db"
    con = td.connect(db_path)
    for run_id in ("run-1", "run-2"):
        con.execute(
            "INSERT INTO runs(id, symbol, question, debate_rounds, created_at, status) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (run_id, "AAPL", "Test", 3, td.utc_now(), "active"),
        )
    con.execute(
        "INSERT INTO evidence(run_id, source, title, url, published_at, payload_json, fetched_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        ("run-1", "Yahoo Finance", "Price", None, None, "{}", td.utc_now()),
    )
    con.execute(
        "INSERT INTO contributions(run_id, stage, actor, round_no, content, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        ("run-1", "analysis", "Fundamentals Analyst", None, "c", td.utc_now()),
    )
    con.commit()
    con.close()

    args = MagicMock()
    args.db = db_path
    args.limit = 50
    td.cmd_runs(args)
    captured = capsys.readouterr()
    parsed = json.loads(captured.out.strip())
    by_id = {row["id"]: row for row in parsed}
    assert by_id["run-1"]["evidence_count"] == 1
    assert by_id["run-1"]["contributions_count"] == 1
    assert by_id["run-2"]["evidence_count"] == 0
    assert by_id["run-2"]["contributions_count"] == 0


def test_cmd_purge_requires_confirmation(tmp_path: Path, capsys):
    db_path = tmp_path / "test.db"
    con = td.connect(db_path)
    con.execute(
        "INSERT INTO runs(id, symbol, question, debate_rounds, created_at, status) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        ("shell-1", "AAPL", "Test", 3, td.utc_now(), "active"),
    )
    con.commit()
    con.close()

    args = MagicMock()
    args.db = db_path
    args.yes = False
    td.cmd_purge(args)
    captured = capsys.readouterr()
    parsed = json.loads(captured.out.strip())
    assert parsed["shell_runs"] == ["shell-1"]
    assert parsed["requires_yes"] is True
    assert parsed["deleted"] == []

    con = sqlite3.connect(db_path)
    con.row_factory = sqlite3.Row
    runs = con.execute("SELECT id FROM runs").fetchall()
    assert len(runs) == 1
    con.close()


def test_cmd_purge_removes_empty_runs(tmp_path: Path, capsys):
    db_path = tmp_path / "test.db"
    con = td.connect(db_path)
    for run_id in ("shell-1", "shell-2"):
        con.execute(
            "INSERT INTO runs(id, symbol, question, debate_rounds, created_at, status) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (run_id, "AAPL", "Test", 3, td.utc_now(), "active"),
        )
    con.execute(
        "INSERT INTO runs(id, symbol, question, debate_rounds, created_at, status) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        ("real-1", "NVDA", "Test", 3, td.utc_now(), "active"),
    )
    con.execute(
        "INSERT INTO evidence(run_id, source, title, url, published_at, payload_json, fetched_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        ("real-1", "Yahoo Finance", "Price", None, None, "{}", td.utc_now()),
    )
    con.commit()
    con.close()

    args = MagicMock()
    args.db = db_path
    args.yes = True
    td.cmd_purge(args)
    captured = capsys.readouterr()
    parsed = json.loads(captured.out.strip())
    assert parsed["deleted"] == ["shell-1", "shell-2"]

    con = sqlite3.connect(db_path)
    con.row_factory = sqlite3.Row
    runs = con.execute("SELECT id FROM runs").fetchall()
    assert [row["id"] for row in runs] == ["real-1"]
    con.close()


def test_cmd_search_includes_counts(tmp_path: Path, capsys):
    db_path = tmp_path / "test.db"
    con = td.connect(db_path)
    con.execute(
        "INSERT INTO runs(id, symbol, question, debate_rounds, created_at, status) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        ("run-1", "NVDA", "Analyze NVDA", 3, td.utc_now(), "active"),
    )
    con.execute(
        "INSERT INTO evidence(run_id, source, title, url, published_at, payload_json, fetched_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        ("run-1", "Yahoo Finance", "Price", None, None, "{}", td.utc_now()),
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
    assert parsed[0]["evidence_count"] == 1
    assert parsed[0]["contributions_count"] == 0


def test_max_workers_is_limited():
    assert _MAX_WORKERS <= 4


def test_cmd_record_normalizes_actor_and_retries_idempotently(tmp_path: Path, capsys):
    db_path = tmp_path / "test.db"
    _create_record_run(db_path)
    args = _record_args(db_path, content="same report")

    td.cmd_record(args)
    first = json.loads(capsys.readouterr().out)
    td.cmd_record(args)
    second = json.loads(capsys.readouterr().out)

    assert first["actor"] == "fundamentals"
    assert first["record_status"] == "created"
    assert second["record_status"] == "duplicate"
    with td.connect(db_path) as con:
        rows = con.execute("SELECT actor, content FROM contributions").fetchall()
    assert [(row["actor"], row["content"]) for row in rows] == [
        ("fundamentals", "same report")
    ]


def test_cmd_record_requires_replace_and_blocks_downstream_overwrite(tmp_path: Path):
    db_path = tmp_path / "test.db"
    _create_record_run(db_path)
    _record_all_analyses(db_path)
    td.cmd_record(
        _record_args(db_path, stage="debate", actor="Bull Researcher", round=1)
    )
    td.cmd_record(
        _record_args(db_path, stage="debate", actor="Bear Researcher", round=1)
    )

    with pytest.raises(SystemExit, match="pass --replace"):
        td.cmd_record(_record_args(db_path, content="changed report"))
    with pytest.raises(SystemExit, match="downstream"):
        td.cmd_record(_record_args(db_path, content="changed report", replace=True))


def test_cmd_record_enforces_analysis_and_debate_order(tmp_path: Path):
    db_path = tmp_path / "test.db"
    _create_record_run(db_path, rounds=2)

    with pytest.raises(SystemExit, match="Invalid actor"):
        td.cmd_record(_record_args(db_path, actor="Bull Researcher"))

    with pytest.raises(SystemExit, match="all four analyst"):
        td.cmd_record(
            _record_args(db_path, stage="debate", actor="Bear Researcher", round=1)
        )

    _record_all_analyses(db_path)
    with pytest.raises(SystemExit, match="sequential"):
        td.cmd_record(
            _record_args(db_path, stage="debate", actor="Bear Researcher", round=1)
        )
    with pytest.raises(SystemExit, match="sequential"):
        td.cmd_record(
            _record_args(db_path, stage="debate", actor="Bull Researcher", round=2)
        )


def test_cmd_record_abstain_requires_explicit_valid_options(tmp_path: Path, capsys):
    db_path = tmp_path / "test.db"
    _create_record_run(db_path)
    _record_all_analyses(db_path)
    td.cmd_record(_record_args(db_path, stage="debate", actor="bull", round=1))
    td.cmd_record(_record_args(db_path, stage="debate", actor="bear", round=1))

    with pytest.raises(SystemExit, match="Verdict requires"):
        td.cmd_record(_record_args(db_path, stage="verdict", actor="committee"))
    with pytest.raises(SystemExit, match="cannot be combined"):
        td.cmd_record(
            _record_args(
                db_path,
                stage="verdict",
                actor="committee",
                abstain=True,
                confidence="low",
            )
        )

    td.cmd_record(
        _record_args(
            db_path,
            stage="verdict",
            actor="Investment Committee",
            abstain=True,
            content="Evidence is insufficient.",
        )
    )
    parsed = json.loads(capsys.readouterr().out.splitlines()[-1])
    assert parsed["actor"] == "committee"
    with td.connect(db_path) as con:
        run = con.execute(
            "SELECT verdict, confidence FROM runs WHERE id = 'run-1'"
        ).fetchone()
    assert (run["verdict"], run["confidence"]) == (None, None)

    render_args = MagicMock(db=db_path, run_id="run-1", reports=tmp_path / "reports")
    td.cmd_render(render_args)
    rendered = json.loads(capsys.readouterr().out)
    assert rendered["status"] == "incomplete"


def test_complete_workflow_renders_completed(tmp_path: Path, capsys):
    db_path = tmp_path / "test.db"
    _create_record_run(db_path)
    fetch_time = td.utc_now()
    with td.connect(db_path) as con:
        con.execute(
            "INSERT INTO evidence("
            "run_id, source, title, url, published_at, payload_json, fetched_at, dedup_key"
            ") VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                "run-1",
                "Yahoo Finance",
                "Fundamentals",
                None,
                None,
                "{}",
                fetch_time,
                "fundamentals",
            ),
        )
    _record_all_analyses(db_path)
    td.cmd_record(_record_args(db_path, stage="debate", actor="bull", round=1))
    td.cmd_record(_record_args(db_path, stage="debate", actor="bear", round=1))
    td.cmd_record(
        _record_args(
            db_path,
            stage="verdict",
            actor="committee",
            verdict="hold",
            confidence="medium",
            content="# 投資委員會裁決",
            summary_json=json.dumps(
                {
                    "recommendation": "hold",
                    "confidence": "medium",
                    "fetch_time": fetch_time,
                    "critical_evidence_ids": ["EVID-0001"],
                }
            ),
        )
    )

    render_args = MagicMock(db=db_path, run_id="run-1", reports=tmp_path / "reports")
    td.cmd_render(render_args)
    rendered = json.loads(capsys.readouterr().out.splitlines()[-1])
    assert rendered["status"] == "completed"
