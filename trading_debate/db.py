"""SQLite persistence for the trading-debate research runs."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

from .utils import as_json, utc_now


def connect(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(db_path)
    con.row_factory = sqlite3.Row
    con.executescript(
        """
        PRAGMA foreign_keys = ON;
        CREATE TABLE IF NOT EXISTS runs (
          id TEXT PRIMARY KEY, symbol TEXT NOT NULL, question TEXT NOT NULL,
          debate_rounds INTEGER NOT NULL, created_at TEXT NOT NULL, status TEXT NOT NULL,
          verdict TEXT, confidence TEXT, report_path TEXT
        );
        CREATE TABLE IF NOT EXISTS evidence (
          id INTEGER PRIMARY KEY AUTOINCREMENT, run_id TEXT NOT NULL REFERENCES runs(id),
          source TEXT NOT NULL, title TEXT NOT NULL, url TEXT, published_at TEXT,
          payload_json TEXT NOT NULL, fetched_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS contributions (
          id INTEGER PRIMARY KEY AUTOINCREMENT, run_id TEXT NOT NULL REFERENCES runs(id),
          stage TEXT NOT NULL, actor TEXT NOT NULL, round_no INTEGER,
          content TEXT NOT NULL, created_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS ix_runs_symbol ON runs(symbol, created_at DESC);
        CREATE INDEX IF NOT EXISTS ix_evidence_run ON evidence(run_id);
        CREATE INDEX IF NOT EXISTS ix_contributions_run ON contributions(run_id, id);
        """
    )
    return con


def insert_evidence(
    con: sqlite3.Connection,
    run_id: str,
    source: str,
    title: str,
    payload: Any,
    *,
    url: str | None = None,
    published_at: str | None = None,
) -> None:
    con.execute(
        "INSERT INTO evidence(run_id, source, title, url, published_at, payload_json, fetched_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (run_id, source, title, url, published_at, as_json(payload), utc_now()),
    )


def connector_status(
    con: sqlite3.Connection, run_id: str, source: str, state: str, detail: str
) -> None:
    insert_evidence(
        con, run_id, source, f"Connector {state}", {"state": state, "detail": detail}
    )
