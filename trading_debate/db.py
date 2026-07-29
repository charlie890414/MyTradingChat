"""SQLite persistence for the trading-debate research runs."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

from .models import EvidenceItem
from .utils import as_json, utc_now


def connect(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(db_path)
    con.row_factory = sqlite3.Row
    con.executescript(
        """
        PRAGMA foreign_keys = ON;
        PRAGMA journal_mode = WAL;
        CREATE TABLE IF NOT EXISTS runs (
          id TEXT PRIMARY KEY, symbol TEXT NOT NULL, question TEXT NOT NULL,
          debate_rounds INTEGER NOT NULL, created_at TEXT NOT NULL,
          status TEXT NOT NULL, verdict TEXT, confidence TEXT,
          report_path TEXT
        );
        CREATE TABLE IF NOT EXISTS evidence (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          run_id TEXT NOT NULL REFERENCES runs(id),
          source TEXT NOT NULL, title TEXT NOT NULL, url TEXT,
          published_at TEXT,           payload_json TEXT NOT NULL,
          fetched_at TEXT NOT NULL,
          dedup_key TEXT NOT NULL DEFAULT ''
        );

        CREATE TABLE IF NOT EXISTS contributions (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          run_id TEXT NOT NULL REFERENCES runs(id),
          stage TEXT NOT NULL, actor TEXT NOT NULL, round_no INTEGER,
          content TEXT NOT NULL, created_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS ix_runs_symbol
          ON runs(symbol, created_at DESC);
        CREATE INDEX IF NOT EXISTS ix_evidence_run
          ON evidence(run_id);
        CREATE UNIQUE INDEX IF NOT EXISTS ux_evidence_dedup
          ON evidence(run_id, source, dedup_key);
        CREATE INDEX IF NOT EXISTS ix_contributions_run
          ON contributions(run_id, id);
        """
    )
    return con


def insert_evidence_item(con: sqlite3.Connection, item: EvidenceItem) -> None:
    con.execute(
        """
        INSERT INTO evidence(
            run_id, source, title, url, published_at,
            payload_json, fetched_at, dedup_key
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(run_id, source, dedup_key) DO UPDATE SET
            title=excluded.title,
            url=excluded.url,
            published_at=excluded.published_at,
            payload_json=excluded.payload_json,
            fetched_at=excluded.fetched_at
        """,
        (
            item.run_id,
            item.source,
            item.title,
            item.url,
            item.published_at,
            as_json(item.payload),
            utc_now(),
            item.dedup_key,
        ),
    )


def insert_evidence_items(con: sqlite3.Connection, items: list[EvidenceItem]) -> None:
    """Bulk upsert evidence items for a run.

    The dedup_key on each item is used to resolve conflicts so repeated
    fetches of the same source/title/url update existing rows instead of
    creating duplicates.
    """
    rows = [
        (
            item.run_id,
            item.source,
            item.title,
            item.url,
            item.published_at,
            as_json(item.payload),
            utc_now(),
            item.dedup_key,
        )
        for item in items
    ]
    con.executemany(
        """
        INSERT INTO evidence(
            run_id, source, title, url, published_at,
            payload_json, fetched_at, dedup_key
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(run_id, source, dedup_key) DO UPDATE SET
            title=excluded.title,
            url=excluded.url,
            published_at=excluded.published_at,
            payload_json=excluded.payload_json,
            fetched_at=excluded.fetched_at
        """,
        rows,
    )


def connector_status(
    con: sqlite3.Connection, run_id: str, source: str, state: str, detail: str
) -> None:
    """Backward-compatible helper to record a connector status item."""
    insert_evidence_item(
        con,
        EvidenceItem(
            run_id=run_id,
            source=source,
            title=f"Connector {state}",
            payload={"state": state, "detail": detail},
        ),
    )


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
    """Backward-compatible helper to insert a single evidence row."""
    insert_evidence_item(
        con,
        EvidenceItem(
            run_id=run_id,
            source=source,
            title=title,
            payload=payload,
            url=url,
            published_at=published_at,
        ),
    )
