"""SQLite persistence for the trading-debate research runs."""

from __future__ import annotations

import json
import re
import sqlite3
from pathlib import Path
from typing import Any

from .models import EvidenceItem
from .utils import as_json, is_news_source, utc_now

RUN_STATUSES = frozenset({"active", "fetching", "incomplete", "completed", "failed"})
RATINGS = frozenset({"buy", "hold", "reduce"})
CONFIDENCE_LEVELS = frozenset({"low", "medium", "high"})
_SCHEMA_VERSION = 4
_LEGACY_SUMMARY_RE = re.compile(
    r"\n## Machine-readable summary\s*```json\s*(\{.*?\})\s*```",
    flags=re.DOTALL | re.IGNORECASE,
)

_ACTOR_ALIASES = {
    "analysis": {
        "fundamentals": "fundamentals",
        "fundamentals analyst": "fundamentals",
        "technical": "technical",
        "technical analyst": "technical",
        "news_content": "news_content",
        "news content analyst": "news_content",
        "news content summarizer": "news_content",
        "news": "news",
        "news analyst": "news",
        "news & events analyst": "news",
        "news and events analyst": "news",
        "news-events": "news",
        "sentiment": "sentiment",
        "sentiment analyst": "sentiment",
    },
    "debate": {
        "bull": "bull",
        "bull researcher": "bull",
        "bear": "bear",
        "bear researcher": "bear",
    },
    "verdict": {
        "committee": "committee",
        "investment committee": "committee",
    },
}


class MigrationError(RuntimeError):
    """Raised when legacy contribution data cannot be migrated safely."""


def normalize_contribution_actor(stage: str, actor: str) -> str:
    """Return the canonical actor for a workflow stage.

    Display names remain accepted at the CLI boundary so existing agent skills can
    retry safely, while the database stores one stable value per logical role.
    """
    normalized = " ".join(actor.strip().lower().split())
    canonical = _ACTOR_ALIASES.get(stage, {}).get(normalized)
    if not canonical:
        allowed = ", ".join(sorted(set(_ACTOR_ALIASES.get(stage, {}).values())))
        raise ValueError(
            f"Invalid actor {actor!r} for {stage}; expected one of: {allowed}"
        )
    return canonical


def connect(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(db_path, timeout=30)
    con.row_factory = sqlite3.Row
    con.executescript(
        """
        PRAGMA foreign_keys = ON;
        PRAGMA journal_mode = WAL;
        CREATE TABLE IF NOT EXISTS runs (
          id TEXT PRIMARY KEY, symbol TEXT NOT NULL, requested_symbol TEXT,
          question TEXT NOT NULL,
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
          batch_id TEXT REFERENCES evidence_batches(id),
          dedup_key TEXT NOT NULL DEFAULT ''
        );
        CREATE TABLE IF NOT EXISTS evidence_batches (
          id TEXT PRIMARY KEY,
          run_id TEXT NOT NULL REFERENCES runs(id),
          started_at TEXT NOT NULL,
          completed_at TEXT,
          status TEXT NOT NULL CHECK(
            status IN ('fetching', 'completed', 'partial', 'failed')
          ),
          resolved_symbol TEXT NOT NULL,
          error_detail TEXT
        );

        CREATE TABLE IF NOT EXISTS contributions (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          run_id TEXT NOT NULL REFERENCES runs(id),
          stage TEXT NOT NULL, actor TEXT NOT NULL, round_no INTEGER,
          content TEXT NOT NULL, summary_json TEXT, created_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS ix_runs_symbol
          ON runs(symbol, created_at DESC);
        CREATE INDEX IF NOT EXISTS ix_evidence_run
          ON evidence(run_id);
        CREATE UNIQUE INDEX IF NOT EXISTS ux_evidence_dedup
          ON evidence(run_id, batch_id, dedup_key);
        CREATE INDEX IF NOT EXISTS ix_contributions_run
          ON contributions(run_id, id);
        """
    )
    _migrate_contributions(con)
    _migrate_evidence_batches(con)
    _migrate_evidence_dedup(con)
    _migrate_runs(con)
    return con


def _migrate_runs(con: sqlite3.Connection) -> None:
    """Preserve the user's original symbol so bare Taiwan codes can be resolved."""
    columns = {row[1] for row in con.execute("PRAGMA table_info(runs)")}
    if "requested_symbol" not in columns:
        with con:
            con.execute("ALTER TABLE runs ADD COLUMN requested_symbol TEXT")
    with con:
        con.execute(
            "UPDATE runs SET requested_symbol = symbol "
            "WHERE requested_symbol IS NULL OR requested_symbol = ''"
        )


def _migrate_contributions(con: sqlite3.Connection) -> None:
    """Canonicalize contributions and move legacy summaries into SQL."""
    version = con.execute("PRAGMA user_version").fetchone()[0]
    legacy_summary = con.execute(
        "SELECT 1 FROM contributions "
        "WHERE summary_json IS NULL AND content LIKE '%## Machine-readable summary%' "
        "LIMIT 1"
    ).fetchone()
    if version >= _SCHEMA_VERSION and not legacy_summary:
        return

    columns = {row[1] for row in con.execute("PRAGMA table_info(contributions)")}
    if "summary_json" not in columns:
        with con:
            con.execute("ALTER TABLE contributions ADD COLUMN summary_json TEXT")
    rows = con.execute(
        "SELECT id, run_id, stage, actor, round_no, content, summary_json "
        "FROM contributions ORDER BY id"
    ).fetchall()
    normalized: dict[int, str] = {}
    grouped: dict[tuple[str, str, str, int], list[sqlite3.Row]] = {}
    for row in rows:
        try:
            actor = normalize_contribution_actor(row["stage"], row["actor"])
        except ValueError:
            actor = row["actor"]
        normalized[row["id"]] = actor
        key = (row["run_id"], row["stage"], actor, row["round_no"] or 0)
        grouped.setdefault(key, []).append(row)

    conflicts = sorted(
        {
            key[0]
            for key, duplicates in grouped.items()
            if len(duplicates) > 1 and len({row["content"] for row in duplicates}) > 1
        }
    )
    if conflicts:
        run_ids = ", ".join(conflicts)
        raise MigrationError(
            f"Cannot migrate conflicting duplicate contributions for run IDs: {run_ids}"
        )

    duplicate_ids = [
        row["id"]
        for duplicates in grouped.values()
        if len(duplicates) > 1
        for row in duplicates[:-1]
    ]
    with con:
        for row_id, actor in normalized.items():
            con.execute(
                "UPDATE contributions SET actor = ? WHERE id = ?", (actor, row_id)
            )
        if duplicate_ids:
            con.executemany(
                "DELETE FROM contributions WHERE id = ?",
                [(row_id,) for row_id in duplicate_ids],
            )
        for row in rows:
            if row["summary_json"] is not None:
                continue
            match = _LEGACY_SUMMARY_RE.search(row["content"])
            if not match:
                continue
            try:
                summary = json.loads(match.group(1))
            except json.JSONDecodeError:
                continue
            if not isinstance(summary, dict):
                continue
            con.execute(
                "UPDATE contributions SET content = ?, summary_json = ? WHERE id = ?",
                (
                    (
                        row["content"][: match.start()] + row["content"][match.end() :]
                    ).strip(),
                    json.dumps(summary, ensure_ascii=False, sort_keys=True),
                    row["id"],
                ),
            )
        con.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS ux_contributions_logical "
            "ON contributions(run_id, stage, actor, IFNULL(round_no, 0))"
        )
        con.execute(f"PRAGMA user_version = {_SCHEMA_VERSION}")


def _migrate_evidence_dedup(con: sqlite3.Connection) -> None:
    """Move legacy evidence to source-scoped keys before cross-source dedup."""
    index_columns = con.execute("PRAGMA index_info(ux_evidence_dedup)").fetchall()
    if [row[2] for row in index_columns] == ["run_id", "batch_id", "dedup_key"]:
        return
    with con:
        con.execute(
            "UPDATE evidence SET dedup_key = source || ':' || dedup_key "
            "WHERE dedup_key NOT LIKE 'source:%'"
        )
        con.execute("DROP INDEX IF EXISTS ux_evidence_dedup")
        con.execute(
            "CREATE UNIQUE INDEX ux_evidence_dedup "
            "ON evidence(run_id, batch_id, dedup_key)"
        )


def _migrate_evidence_batches(con: sqlite3.Connection) -> None:
    """Add batch identity without rewriting legacy evidence snapshots."""
    columns = {row[1] for row in con.execute("PRAGMA table_info(evidence)").fetchall()}
    if "batch_id" not in columns:
        with con:
            con.execute("ALTER TABLE evidence ADD COLUMN batch_id TEXT")


def create_evidence_batch(
    con: sqlite3.Connection, batch_id: str, run_id: str, resolved_symbol: str
) -> None:
    con.execute(
        "INSERT INTO evidence_batches(id, run_id, started_at, status, resolved_symbol) "
        "VALUES (?, ?, ?, 'fetching', ?)",
        (batch_id, run_id, utc_now(), resolved_symbol),
    )


def finish_evidence_batch(
    con: sqlite3.Connection,
    batch_id: str,
    *,
    status: str,
    error_detail: str | None = None,
) -> None:
    if status not in {"completed", "partial", "failed"}:
        raise ValueError("batch status must be completed, partial, or failed")
    con.execute(
        "UPDATE evidence_batches SET completed_at = ?, status = ?, error_detail = ? "
        "WHERE id = ?",
        (utc_now(), status, error_detail, batch_id),
    )


def current_evidence(
    con: sqlite3.Connection, run_id: str, *, columns: str = "*"
) -> list[sqlite3.Row]:
    """Return the latest usable batch, or unbatched legacy evidence."""
    batch = con.execute(
        "SELECT id FROM evidence_batches WHERE run_id = ? "
        "AND status IN ('completed', 'partial') "
        "ORDER BY completed_at DESC, rowid DESC LIMIT 1",
        (run_id,),
    ).fetchone()
    if batch:
        return con.execute(
            f"SELECT {columns} FROM evidence WHERE run_id = ? "
            "AND batch_id = ? ORDER BY id",
            (run_id, batch["id"]),
        ).fetchall()
    return con.execute(
        f"SELECT {columns} FROM evidence WHERE run_id = ? "
        "AND batch_id IS NULL ORDER BY id",
        (run_id,),
    ).fetchall()


def assess_current_evidence(con: sqlite3.Connection, run_id: str) -> list[str]:
    """Return blocking gaps for a current-market rating in the latest evidence batch."""
    return assess_evidence(current_evidence(con, run_id))


def assess_evidence(evidence: list[sqlite3.Row]) -> list[str]:
    """Return blocking gaps for a current-market rating from evidence rows."""
    price_snapshot = False
    price_history = False
    fundamentals = False
    for row in evidence:
        if row["title"].startswith("Connector "):
            continue
        try:
            payload = json.loads(row["payload_json"])
        except (TypeError, json.JSONDecodeError):
            continue
        if row["title"] == "One-year price snapshot" and isinstance(payload, dict):
            price_snapshot = bool(payload.get("as_of")) and isinstance(
                payload.get("close"), int | float
            )
        elif row["title"] == "Daily OHLCV history" and isinstance(payload, dict):
            price_history = bool(payload.get("records"))
        elif row["title"] == "Fundamentals snapshot" and isinstance(payload, dict):
            fundamentals = bool(payload)
        elif (
            row["source"].startswith(("SEC EDGAR", "MOPS Official", "TWSE/TPEX"))
            and isinstance(payload, dict)
            and payload
        ):
            fundamentals = True
    gaps: list[str] = []
    if not price_snapshot:
        gaps.append("缺少具日期與收盤價的價格快照。")
    if not price_history:
        gaps.append("缺少可用的日線價格歷史。")
    if not fundamentals:
        gaps.append("缺少可用的基本面證據。")
    return gaps


def evidence_reference(evidence_id: int) -> str:
    """Return the stable, user-facing reference for a persisted evidence row."""
    return f"EVID-{evidence_id:04d}"


def update_run_verdict(
    con: sqlite3.Connection,
    run_id: str,
    *,
    verdict: str | None,
    confidence: str | None,
) -> None:
    """Persist a committee rating, or an explicit abstention represented by None."""
    if verdict is not None and verdict not in RATINGS:
        raise ValueError("verdict must be buy, hold, reduce, or None")
    if verdict is None and confidence is not None:
        raise ValueError("confidence must be None when verdict is None")
    if verdict is not None and confidence not in CONFIDENCE_LEVELS:
        raise ValueError("confidence must be low, medium, or high with a verdict")
    result = con.execute(
        "UPDATE runs SET verdict = ?, confidence = ? WHERE id = ?",
        (verdict, confidence, run_id),
    )
    if result.rowcount != 1:
        raise ValueError(f"Unknown run id: {run_id}")


def delete_run(con: sqlite3.Connection, run_id: str) -> sqlite3.Row | None:
    """Delete one run and dependent SQLite records, returning its former metadata."""
    run = con.execute("SELECT * FROM runs WHERE id = ?", (run_id,)).fetchone()
    if not run:
        return None
    con.execute("DELETE FROM evidence WHERE run_id = ?", (run_id,))
    con.execute("DELETE FROM evidence_batches WHERE run_id = ?", (run_id,))
    con.execute("DELETE FROM contributions WHERE run_id = ?", (run_id,))
    con.execute("DELETE FROM runs WHERE id = ?", (run_id,))
    return run


def insert_evidence_item(
    con: sqlite3.Connection, item: EvidenceItem, *, batch_id: str | None = None
) -> None:
    con.execute(
        """
        INSERT INTO evidence(
            run_id, source, title, url, published_at,
            payload_json, fetched_at, batch_id, dedup_key
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(run_id, batch_id, dedup_key) DO UPDATE SET
            title=excluded.title,
            url=excluded.url,
            published_at=excluded.published_at,
            payload_json=excluded.payload_json,
            fetched_at=excluded.fetched_at,
            batch_id=excluded.batch_id
        """,
        (
            item.run_id,
            item.source,
            item.title,
            item.url,
            item.published_at,
            as_json(item.payload),
            utc_now(),
            batch_id,
            item.dedup_key,
        ),
    )


def insert_evidence_items(
    con: sqlite3.Connection, items: list[EvidenceItem], *, batch_id: str | None = None
) -> None:
    """Bulk upsert evidence items for a run.

    The dedup_key on each item is used to resolve conflicts so repeated
    fetches and syndicated news from multiple sources do not create duplicates.
    """
    unique_items: dict[str, EvidenceItem] = {}
    for item in items:
        if is_news_source(item.source):
            existing = unique_items.get(item.dedup_key)
            unique_items[item.dedup_key] = (
                _merge_news_items(existing, item) if existing else item
            )
        else:
            unique_items[item.dedup_key] = item
    rows = [
        (
            item.run_id,
            item.source,
            item.title,
            item.url,
            item.published_at,
            as_json(item.payload),
            utc_now(),
            batch_id,
            item.dedup_key,
        )
        for item in unique_items.values()
    ]
    con.executemany(
        """
        INSERT INTO evidence(
            run_id, source, title, url, published_at,
            payload_json, fetched_at, batch_id, dedup_key
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(run_id, batch_id, dedup_key) DO UPDATE SET
            title=excluded.title,
            url=excluded.url,
            published_at=excluded.published_at,
            payload_json=excluded.payload_json,
            fetched_at=excluded.fetched_at,
            batch_id=excluded.batch_id
        """,
        rows,
    )


def _merge_news_items(existing: EvidenceItem, candidate: EvidenceItem) -> EvidenceItem:
    """Keep syndicated-news provenance while selecting the most useful record."""
    existing_payload = existing.payload if isinstance(existing.payload, dict) else {}
    candidate_payload = candidate.payload if isinstance(candidate.payload, dict) else {}
    urls = {
        str(url)
        for url in (
            existing.url,
            candidate.url,
            *existing_payload.get("related_urls", []),
            *candidate_payload.get("related_urls", []),
        )
        if isinstance(url, str) and url
    }
    sources = {
        str(source)
        for source in (
            existing.source,
            candidate.source,
            *existing_payload.get("related_sources", []),
            *candidate_payload.get("related_sources", []),
        )
        if isinstance(source, str) and source
    }

    def score(item: EvidenceItem) -> tuple[int, int]:
        payload = item.payload if isinstance(item.payload, dict) else {}
        status = payload.get("article_text_status")
        body = payload.get("article_text")
        return (
            int(isinstance(status, dict) and status.get("state") == "available"),
            len(body) if isinstance(body, str) else 0,
        )

    selected = candidate if score(candidate) > score(existing) else existing
    payload = selected.payload if isinstance(selected.payload, dict) else {}
    selected.payload = {
        **payload,
        "related_sources": sorted(sources),
        "related_urls": sorted(urls),
    }
    return selected


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
