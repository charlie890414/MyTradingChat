"""Command-line interface for the trading-debate research workflow."""

from __future__ import annotations

import argparse
import json
import os
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from .connectors import CONNECTORS, fetch_yahoo
from .db import connect, insert_evidence_items
from .models import EvidenceItem, YahooFetchResult
from .render import cmd_render
from .symbols import normalize_symbol, resolve_taiwan_yahoo_symbol
from .utils import as_json, load_dotenv, utc_now

ROOT = Path(__file__).resolve().parent
DEFAULT_DB = ROOT.parent / "data" / "research.sqlite3"
DEFAULT_REPORTS = ROOT.parent / "reports"
DEFAULT_ENV = ROOT.parent / ".env"

_MAX_WORKERS = int(os.getenv("TRADING_DEBATE_MAX_WORKERS", "2"))


def _connector_status_item(
    run_id: str, source: str, state: str, detail: str
) -> EvidenceItem:
    return EvidenceItem(
        run_id=run_id,
        source=source,
        title=f"Connector {state}",
        payload={"state": state, "detail": detail},
    )


def _run_connector(
    name: str, fetcher: Any, run_id: str, symbol: str, limit: int
) -> tuple[list[EvidenceItem], str | None]:
    try:
        return fetcher(run_id, symbol, limit), None
    except Exception as exc:  # pragma: no cover - defensive
        return [_connector_status_item(run_id, name, "error", str(exc))], str(exc)


def cmd_init(args: argparse.Namespace) -> None:
    symbol = normalize_symbol(args.symbol)
    run_id = f"{symbol}-{datetime.now():%Y%m%d-%H%M%S}-{uuid4().hex[:6]}"
    with connect(args.db) as con:
        con.execute(
            """
            INSERT INTO runs(
                id, symbol, question, debate_rounds, created_at, status
            ) VALUES (?, ?, ?, ?, ?, 'active')
            """,
            (run_id, symbol, args.question, args.rounds, utc_now()),
        )
    print(as_json({"run_id": run_id, "symbol": symbol, "rounds": args.rounds}))


def cmd_fetch(args: argparse.Namespace) -> None:
    with connect(args.db) as con:
        run = con.execute(
            "SELECT symbol FROM runs WHERE id = ?", (args.run_id,)
        ).fetchone()
        if not run:
            raise SystemExit(f"Unknown run id: {args.run_id}")
        symbol = resolve_taiwan_yahoo_symbol(run["symbol"])
        if symbol != run["symbol"]:
            con.execute(
                "UPDATE runs SET symbol = ? WHERE id = ?",
                (symbol, args.run_id),
            )

        fetched: YahooFetchResult | None = None
        yahoo_error: str | None = None
        try:
            fetched = fetch_yahoo(args.run_id, symbol, args.news_limit)
            yahoo_items = list(fetched.items)
        except Exception as exc:
            yahoo_error = str(exc)
            yahoo_items = [
                _connector_status_item(
                    args.run_id, "Yahoo Finance", "error", yahoo_error
                )
            ]

        connector_items: dict[str, int] = {}
        connector_errors: dict[str, str] = {}
        connector_results: list[EvidenceItem] = []
        with ThreadPoolExecutor(max_workers=_MAX_WORKERS) as executor:
            futures = {
                executor.submit(
                    _run_connector, name, fetcher, args.run_id, symbol, args.news_limit
                ): name
                for name, fetcher in CONNECTORS.items()
            }
            for future in futures:
                name = futures[future]
                try:
                    items, error = future.result()
                    connector_results.extend(items)
                    connector_items[name] = len(items)
                    if error:
                        connector_errors[name] = error
                except Exception as exc:  # pragma: no cover - defensive
                    connector_errors[name] = str(exc)

        con.execute("DELETE FROM evidence WHERE run_id = ?", (args.run_id,))
        insert_evidence_items(con, yahoo_items + connector_results)

    print(
        as_json(
            {
                "run_id": args.run_id,
                "fundamental_fields": (len(fetched.fundamentals) if fetched else None),
                "yahoo_news_items": fetched.stored_news if fetched else 0,
                "connector_items": connector_items,
                "connector_errors": connector_errors,
                "price": fetched.price if fetched else None,
                "technicals": fetched.technicals if fetched else None,
                "yahoo_error": yahoo_error,
            }
        )
    )


def cmd_context(args: argparse.Namespace) -> None:
    with connect(args.db) as con:
        run = con.execute("SELECT * FROM runs WHERE id = ?", (args.run_id,)).fetchone()
        evidence = con.execute(
            """
            SELECT source, title, url, published_at, payload_json, fetched_at
            FROM evidence WHERE run_id = ? ORDER BY id
            """,
            (args.run_id,),
        ).fetchall()
    if not run:
        raise SystemExit(f"Unknown run id: {args.run_id}")
    print(
        as_json(
            {
                "run": dict(run),
                "evidence": [
                    {**dict(row), "payload": json.loads(row["payload_json"])}
                    for row in evidence
                ],
            }
        )
    )


def cmd_record(args: argparse.Namespace) -> None:
    content = (
        Path(args.content_file).read_text(encoding="utf-8")
        if args.content_file
        else args.content
    )
    if not content or not content.strip():
        raise SystemExit("Provide non-empty --content or --content-file")
    with connect(args.db) as con:
        if not con.execute(
            "SELECT 1 FROM runs WHERE id = ?", (args.run_id,)
        ).fetchone():
            raise SystemExit(f"Unknown run id: {args.run_id}")
        con.execute(
            """
            INSERT INTO contributions(
                run_id, stage, actor, round_no, content, created_at
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                args.run_id,
                args.stage,
                args.actor,
                args.round,
                content.strip(),
                utc_now(),
            ),
        )
    print(
        as_json(
            {
                "recorded": True,
                "run_id": args.run_id,
                "actor": args.actor,
                "stage": args.stage,
            }
        )
    )


def cmd_search(args: argparse.Namespace) -> None:
    term = f"%{args.query}%"
    with connect(args.db) as con:
        rows = con.execute(
            """
            SELECT id, symbol, question, created_at, status, report_path
            FROM runs
            WHERE symbol LIKE ? OR question LIKE ? OR id IN (
                SELECT run_id FROM contributions WHERE content LIKE ?
            )
            ORDER BY created_at DESC LIMIT ?
            """,
            (term, term, term, args.limit),
        ).fetchall()
    print(as_json([dict(row) for row in rows]))


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--db", type=Path, default=DEFAULT_DB)
    sub = p.add_subparsers(required=True)

    init = sub.add_parser("init")
    init.add_argument("--symbol", required=True)
    init.add_argument("--question", required=True)
    init.add_argument("--rounds", type=int, default=3)
    init.set_defaults(func=cmd_init)

    fetch = sub.add_parser("fetch")
    fetch.add_argument("--run-id", required=True)
    fetch.add_argument("--news-limit", type=int, default=10)
    fetch.set_defaults(func=cmd_fetch)

    context = sub.add_parser("context")
    context.add_argument("--run-id", required=True)
    context.set_defaults(func=cmd_context)

    record = sub.add_parser("record")
    record.add_argument("--run-id", required=True)
    record.add_argument(
        "--stage", choices=("analysis", "debate", "verdict"), required=True
    )
    record.add_argument("--actor", required=True)
    record.add_argument("--round", type=int)
    source = record.add_mutually_exclusive_group(required=True)
    source.add_argument("--content")
    source.add_argument("--content-file")
    record.set_defaults(func=cmd_record)

    render = sub.add_parser("render")
    render.add_argument("--run-id", required=True)
    render.add_argument("--reports", type=Path, default=DEFAULT_REPORTS)
    render.set_defaults(func=cmd_render)

    search = sub.add_parser("search")
    search.add_argument("--query", required=True)
    search.add_argument("--limit", type=int, default=10)
    search.set_defaults(func=cmd_search)
    return p


def main() -> None:
    load_dotenv(DEFAULT_ENV)
    args = parser().parse_args()
    if hasattr(args, "rounds") and args.rounds < 1:
        raise SystemExit("--rounds must be at least 1")
    args.func(args)


if __name__ == "__main__":
    main()
