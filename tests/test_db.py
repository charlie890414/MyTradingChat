"""Tests for SQLite persistence and evidence upsert behavior."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

import trading_debate as td
from trading_debate.db import MigrationError
from trading_debate.models import EvidenceItem


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
        "INSERT INTO runs(id, symbol, question, debate_rounds, created_at, status) "
        "VALUES (?, ?, ?, ?, ?, ?)",
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


def test_insert_evidence_items_upserts_on_duplicate(tmp_path: Path):
    db_path = tmp_path / "test.db"
    con = td.connect(db_path)
    con.execute(
        "INSERT INTO runs(id, symbol, question, debate_rounds, created_at, status) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        ("run-1", "AAPL", "Test", 3, td.utc_now(), "active"),
    )
    items = [
        EvidenceItem(
            run_id="run-1",
            source="Source",
            title="Title",
            payload={"v": 1},
            url="https://example.com",
        ),
        EvidenceItem(
            run_id="run-1",
            source="Source",
            title="Title",
            payload={"v": 2},
            url="https://example.com",
        ),
    ]
    td.insert_evidence_items(con, items)
    con.commit()
    con.row_factory = sqlite3.Row
    rows = con.execute(
        "SELECT payload_json FROM evidence WHERE run_id = ?", ("run-1",)
    ).fetchall()
    assert len(rows) == 1
    assert json.loads(rows[0]["payload_json"]) == {"v": 2}
    con.close()


def test_insert_evidence_items_deduplicates_syndicated_news(tmp_path: Path):
    db_path = tmp_path / "test.db"
    con = td.connect(db_path)
    con.execute(
        "INSERT INTO runs(id, symbol, question, debate_rounds, created_at, status) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        ("run-1", "AAPL", "Test", 3, td.utc_now(), "active"),
    )
    td.insert_evidence_items(
        con,
        [
            EvidenceItem(
                run_id="run-1",
                source="Yahoo Finance News",
                title="Apple launches a new product",
                payload={"summary": "Yahoo copy"},
                url="https://finance.example.com/apple?utm_source=yahoo",
                published_at="2026-08-08T10:00:00+00:00",
            ),
            EvidenceItem(
                run_id="run-1",
                source="Finnhub Company News",
                title="Apple launches a new product",
                payload={"summary": "Syndicated copy"},
                url="https://finnhub.example.com/article/123",
                published_at="2026-08-08T15:00:00+00:00",
            ),
        ],
    )
    con.commit()
    con.row_factory = sqlite3.Row
    rows = con.execute("SELECT source, payload_json FROM evidence").fetchall()
    assert len(rows) == 1
    assert rows[0]["source"] == "Yahoo Finance News"
    assert json.loads(rows[0]["payload_json"]) == {"summary": "Yahoo copy"}
    con.close()


def test_connector_status(tmp_path: Path):
    db_path = tmp_path / "test.db"
    con = td.connect(db_path)
    con.execute(
        "INSERT INTO runs(id, symbol, question, debate_rounds, created_at, status) "
        "VALUES (?, ?, ?, ?, ?, ?)",
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


def test_connector_status_records_error(tmp_path: Path):
    db_path = tmp_path / "test.db"
    con = td.connect(db_path)
    con.execute(
        "INSERT INTO runs(id, symbol, question, debate_rounds, created_at, status) "
        "VALUES (?, ?, ?, ?, ?, ?)",
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


def test_contribution_migration_normalizes_and_deduplicates(tmp_path: Path):
    db_path = tmp_path / "test.db"
    with td.connect(db_path) as con:
        con.execute("DROP INDEX ux_contributions_logical")
        con.execute("PRAGMA user_version = 0")
        con.execute(
            "INSERT INTO runs(id, symbol, question, debate_rounds, created_at, status) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            ("run-1", "AAPL", "Test", 1, td.utc_now(), "active"),
        )
        for actor, content in (
            ("News & Events Analyst", "news report"),
            ("Investment Committee", "same verdict"),
            ("committee", "same verdict"),
        ):
            con.execute(
                "INSERT INTO contributions(run_id, stage, actor, round_no, content, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (
                    "run-1",
                    "analysis" if "Analyst" in actor else "verdict",
                    actor,
                    None,
                    content,
                    td.utc_now(),
                ),
            )

    with td.connect(db_path) as con:
        rows = con.execute(
            "SELECT stage, actor, content FROM contributions ORDER BY id"
        ).fetchall()
        version = con.execute("PRAGMA user_version").fetchone()[0]
    assert [(row["stage"], row["actor"], row["content"]) for row in rows] == [
        ("analysis", "news", "news report"),
        ("verdict", "committee", "same verdict"),
    ]
    assert version == 2


def test_contribution_migration_rejects_conflicting_duplicates(tmp_path: Path):
    db_path = tmp_path / "test.db"
    with td.connect(db_path) as con:
        con.execute("DROP INDEX ux_contributions_logical")
        con.execute("PRAGMA user_version = 0")
        con.execute(
            "INSERT INTO runs(id, symbol, question, debate_rounds, created_at, status) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            ("run-conflict", "AAPL", "Test", 1, td.utc_now(), "active"),
        )
        for content in ("first verdict", "different verdict"):
            con.execute(
                "INSERT INTO contributions(run_id, stage, actor, round_no, content, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                ("run-conflict", "verdict", "committee", None, content, td.utc_now()),
            )

    with pytest.raises(MigrationError, match="run-conflict"):
        td.connect(db_path)

    con = sqlite3.connect(db_path)
    assert con.execute("SELECT COUNT(*) FROM contributions").fetchone()[0] == 2
    con.close()
