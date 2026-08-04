"""Command-line interface for the trading-debate research workflow."""

from __future__ import annotations

import argparse
import os
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from .connectors import CONNECTORS, fetch_yahoo
from .context import CONTEXT_ROLES, ContextSummaryError, assemble_context
from .db import (
    CONFIDENCE_LEVELS,
    RATINGS,
    connect,
    delete_run,
    insert_evidence_items,
    normalize_contribution_actor,
    update_run_verdict,
)
from .models import EvidenceItem, YahooFetchResult
from .render import cmd_render
from .symbols import company_search_name, normalize_symbol, resolve_taiwan_yahoo_symbol
from .taiwan_names import fetch_taiwan_company_name
from .utils import as_json, load_dotenv, utc_now
from .web import serve

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
    name: str,
    fetcher: Any,
    run_id: str,
    symbol: str,
    limit: int,
    *,
    company_name: str | None = None,
) -> tuple[list[EvidenceItem], str | None]:
    try:
        return fetcher(run_id, symbol, limit, company_name=company_name), None
    except Exception as exc:  # pragma: no cover - defensive
        return [_connector_status_item(run_id, name, "error", str(exc))], str(exc)


def cmd_init(args: argparse.Namespace) -> None:
    if args.run_id:
        with connect(args.db) as con:
            run = con.execute(
                "SELECT id, symbol, question, debate_rounds FROM runs WHERE id = ?",
                (args.run_id,),
            ).fetchone()
        if not run:
            raise SystemExit(f"Unknown run id: {args.run_id}")
        print(as_json(dict(run)))
        return
    if not args.symbol or not args.question:
        raise SystemExit("init requires --symbol and --question (or --run-id)")
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

        chinese_name = fetch_taiwan_company_name(symbol)
        company_name = (
            company_search_name(symbol, fetched.fundamentals, chinese_name=chinese_name)
            if fetched
            else None
        )

        connector_items: dict[str, int] = {}
        connector_errors: dict[str, str] = {}
        connector_results: list[EvidenceItem] = []
        with ThreadPoolExecutor(max_workers=_MAX_WORKERS) as executor:
            futures = {
                executor.submit(
                    _run_connector,
                    name,
                    fetcher,
                    args.run_id,
                    symbol,
                    args.news_limit,
                    company_name=company_name,
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

        insert_evidence_items(con, yahoo_items + connector_results)
        if yahoo_error:
            con.execute(
                "UPDATE runs SET status = 'incomplete' WHERE id = ?",
                (args.run_id,),
            )

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
            SELECT id, source, title, url, published_at, payload_json, fetched_at,
                   dedup_key
            FROM evidence WHERE run_id = ? ORDER BY id
            """,
            (args.run_id,),
        ).fetchall()
        contributions = con.execute(
            "SELECT * FROM contributions WHERE run_id = ? ORDER BY id",
            (args.run_id,),
        ).fetchall()
    if not run:
        raise SystemExit(f"Unknown run id: {args.run_id}")
    try:
        context = assemble_context(run, evidence, contributions, args.role)
    except ContextSummaryError as exc:
        raise SystemExit(f"Cannot build {args.role} context: {exc}") from exc
    print(as_json(context))


_ANALYSTS = {"fundamentals", "technical", "news", "sentiment"}


def _option(args: argparse.Namespace, name: str) -> str | None:
    value = getattr(args, name, None)
    return value if isinstance(value, str) else None


def _flag(args: argparse.Namespace, name: str) -> bool:
    return getattr(args, name, False) is True


def _validate_verdict_options(
    args: argparse.Namespace,
) -> tuple[str | None, str | None]:
    verdict = _option(args, "verdict")
    confidence = _option(args, "confidence")
    abstain = _flag(args, "abstain")
    if args.stage != "verdict":
        if verdict or confidence or abstain:
            raise SystemExit("--verdict, --confidence, and --abstain are verdict-only")
        return None, None
    if abstain:
        if verdict or confidence:
            raise SystemExit(
                "--abstain cannot be combined with --verdict or --confidence"
            )
        return None, None
    if verdict not in RATINGS or confidence not in CONFIDENCE_LEVELS:
        raise SystemExit(
            "Verdict requires --verdict buy|hold|reduce and "
            "--confidence low|medium|high, or --abstain"
        )
    return verdict, confidence


def _existing_contribution(
    con: Any, run_id: str, stage: str, actor: str, round_no: int | None
) -> Any:
    return con.execute(
        "SELECT * FROM contributions WHERE run_id = ? AND stage = ? AND actor = ? "
        "AND IFNULL(round_no, 0) = ?",
        (run_id, stage, actor, round_no or 0),
    ).fetchone()


def _has_downstream_records(
    con: Any, run: Any, stage: str, actor: str, round_no: int | None
) -> bool:
    if stage == "analysis":
        return bool(
            con.execute(
                "SELECT 1 FROM contributions WHERE run_id = ? "
                "AND stage IN ('debate', 'verdict') LIMIT 1",
                (run["id"],),
            ).fetchone()
        )
    if stage == "verdict":
        return bool(run["report_path"])
    if actor == "bull":
        query = (
            "SELECT 1 FROM contributions WHERE run_id = ? AND stage = 'debate' "
            "AND (round_no > ? OR (round_no = ? AND actor = 'bear')) LIMIT 1"
        )
        params = (run["id"], round_no, round_no)
    else:
        query = (
            "SELECT 1 FROM contributions WHERE run_id = ? AND stage = 'debate' "
            "AND round_no > ? LIMIT 1"
        )
        params = (run["id"], round_no)
    if con.execute(query, params).fetchone():
        return True
    return bool(
        con.execute(
            "SELECT 1 FROM contributions WHERE run_id = ? "
            "AND stage = 'verdict' LIMIT 1",
            (run["id"],),
        ).fetchone()
    )


def _validate_record(
    con: Any,
    args: argparse.Namespace,
    actor: str,
    *,
    existing: Any | None = None,
) -> Any:
    run = con.execute("SELECT * FROM runs WHERE id = ?", (args.run_id,)).fetchone()
    if not run:
        raise SystemExit(f"Unknown run id: {args.run_id}")
    if run["status"] in {"completed", "failed"}:
        raise SystemExit(f"Cannot record a {run['status']} run")
    if not args.force:
        evidence_count = con.execute(
            "SELECT COUNT(*) FROM evidence WHERE run_id = ?", (args.run_id,)
        ).fetchone()[0]
        if evidence_count == 0:
            raise SystemExit(
                "Run has no evidence yet; run fetch first (or pass --force)"
            )
    if args.stage == "analysis":
        if args.round is not None:
            raise SystemExit("--round is only valid for debate records")
        if con.execute(
            "SELECT 1 FROM contributions WHERE run_id = ? "
            "AND stage IN ('debate', 'verdict') LIMIT 1",
            (args.run_id,),
        ).fetchone():
            raise SystemExit("Analysis records must be completed before debate begins")
    elif args.stage == "debate":
        if args.round is None or args.round < 1 or args.round > run["debate_rounds"]:
            raise SystemExit("Debate records require a valid --round")
        analyses = {
            row["actor"]
            for row in con.execute(
                "SELECT actor FROM contributions WHERE run_id = ? "
                "AND stage = 'analysis'",
                (args.run_id,),
            ).fetchall()
        }
        if not _ANALYSTS.issubset(analyses):
            raise SystemExit("Debate requires all four analyst reports")
        turns = con.execute(
            "SELECT actor, round_no FROM contributions WHERE run_id = ? "
            "AND stage = 'debate' ORDER BY round_no, id",
            (args.run_id,),
        ).fetchall()
        expected_turns = [
            (expected_actor, expected_round)
            for expected_round in range(1, run["debate_rounds"] + 1)
            for expected_actor in ("bull", "bear")
        ]
        actual_turns = [(row["actor"], row["round_no"]) for row in turns]
        if actual_turns != expected_turns[: len(actual_turns)]:
            raise SystemExit("Existing debate turns are out of order")
        next_turn = (
            expected_turns[len(actual_turns)]
            if len(actual_turns) < len(expected_turns)
            else None
        )
        if existing is None and (actor, args.round) != next_turn:
            raise SystemExit(
                "Debate records must be sequential: bull, then bear, round by round"
            )
    elif args.round is not None:
        raise SystemExit("--round is only valid for debate records")
    elif args.stage == "verdict":
        analyses = {
            row["actor"]
            for row in con.execute(
                "SELECT actor FROM contributions "
                "WHERE run_id = ? AND stage = 'analysis'",
                (args.run_id,),
            ).fetchall()
        }
        if not _ANALYSTS.issubset(analyses):
            raise SystemExit("Verdict requires all four analyst reports")
        debate_turns = con.execute(
            "SELECT actor, round_no FROM contributions WHERE run_id = ? "
            "AND stage = 'debate' ORDER BY round_no, id",
            (args.run_id,),
        ).fetchall()
        expected = [
            (actor, round_no)
            for round_no in range(1, run["debate_rounds"] + 1)
            for actor in ("bull", "bear")
        ]
        actual = [(row["actor"], row["round_no"]) for row in debate_turns]
        if actual != expected:
            raise SystemExit("Verdict requires all bull/bear debate turns in order")
    return run


def cmd_record(args: argparse.Namespace) -> None:
    content = (
        Path(args.content_file).read_text(encoding="utf-8")
        if args.content_file
        else args.content
    )
    if not content or not content.strip():
        raise SystemExit("Provide non-empty --content or --content-file")
    verdict, confidence = _validate_verdict_options(args)
    replace = _flag(args, "replace")
    with connect(args.db) as con:
        con.execute("BEGIN IMMEDIATE")
        run_metadata = con.execute(
            "SELECT * FROM runs WHERE id = ?", (args.run_id,)
        ).fetchone()
        if not run_metadata:
            raise SystemExit(f"Unknown run id: {args.run_id}")
        try:
            actor = normalize_contribution_actor(args.stage, args.actor)
        except ValueError as exc:
            raise SystemExit(str(exc)) from exc
        existing = _existing_contribution(
            con, args.run_id, args.stage, actor, args.round
        )
        if existing:
            same_content = existing["content"] == content.strip()
            same_verdict = args.stage != "verdict" or (
                run_metadata["verdict"],
                run_metadata["confidence"],
            ) == (verdict, confidence)
            if same_content and same_verdict:
                record_status = "duplicate"
            else:
                if not replace:
                    raise SystemExit(
                        "A different contribution already exists; "
                        "pass --replace to overwrite it"
                    )
                if _has_downstream_records(
                    con, run_metadata, args.stage, actor, args.round
                ):
                    raise SystemExit(
                        "Cannot replace a contribution with downstream records"
                    )
                _validate_record(con, args, actor, existing=existing)
                con.execute(
                    "UPDATE contributions SET content = ?, created_at = ? WHERE id = ?",
                    (content.strip(), utc_now(), existing["id"]),
                )
                if args.stage == "verdict":
                    update_run_verdict(
                        con, args.run_id, verdict=verdict, confidence=confidence
                    )
                record_status = "replaced"
        else:
            _validate_record(con, args, actor, existing=None)
            if replace:
                raise SystemExit("--replace requires an existing logical contribution")
            if args.stage == "verdict":
                update_run_verdict(
                    con, args.run_id, verdict=verdict, confidence=confidence
                )
            con.execute(
                """
                INSERT INTO contributions(
                    run_id, stage, actor, round_no, content, created_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    args.run_id,
                    args.stage,
                    actor,
                    args.round,
                    content.strip(),
                    utc_now(),
                ),
            )
            record_status = "created"
    print(
        as_json(
            {
                "recorded": True,
                "run_id": args.run_id,
                "actor": actor,
                "stage": args.stage,
                "record_status": record_status,
            }
        )
    )


def cmd_search(args: argparse.Namespace) -> None:
    term = f"%{args.query}%"
    with connect(args.db) as con:
        rows = con.execute(
            """
            SELECT r.id, r.symbol, r.question, r.created_at, r.status,
                   r.report_path,
                   (SELECT COUNT(*) FROM evidence e WHERE e.run_id = r.id)
                       AS evidence_count,
                   (SELECT COUNT(*) FROM contributions c WHERE c.run_id = r.id)
                       AS contributions_count
            FROM runs r
            WHERE r.symbol LIKE ? OR r.question LIKE ? OR r.id IN (
                SELECT run_id FROM contributions WHERE content LIKE ?
            )
            ORDER BY r.created_at DESC LIMIT ?
            """,
            (term, term, term, args.limit),
        ).fetchall()
    print(as_json([dict(row) for row in rows]))


def cmd_runs(args: argparse.Namespace) -> None:
    with connect(args.db) as con:
        rows = con.execute(
            """
            SELECT r.id, r.symbol, r.question, r.created_at, r.status,
                   r.verdict, r.confidence, r.report_path,
                   (SELECT COUNT(*) FROM evidence e WHERE e.run_id = r.id)
                       AS evidence_count,
                   (SELECT COUNT(*) FROM contributions c WHERE c.run_id = r.id)
                       AS contributions_count
            FROM runs r
            ORDER BY r.created_at DESC LIMIT ?
            """,
            (args.limit,),
        ).fetchall()
    print(as_json([dict(row) for row in rows]))


def cmd_purge(args: argparse.Namespace) -> None:
    with connect(args.db) as con:
        shell_ids = [
            row["id"]
            for row in con.execute(
                """
                SELECT r.id FROM runs r
                WHERE NOT EXISTS (
                    SELECT 1 FROM evidence e WHERE e.run_id = r.id
                )
                AND NOT EXISTS (
                    SELECT 1 FROM contributions c WHERE c.run_id = r.id
                )
                ORDER BY r.created_at
                """,
            ).fetchall()
        ]
    if not shell_ids:
        print(as_json({"shell_runs": [], "deleted": [], "requires_yes": False}))
        return
    if not args.yes:
        print(as_json({"shell_runs": shell_ids, "deleted": [], "requires_yes": True}))
        return
    deleted: list[str] = []
    with connect(args.db) as con:
        for run_id in shell_ids:
            run = delete_run(con, run_id)
            if run:
                deleted.append(run["id"])
    print(as_json({"shell_runs": shell_ids, "deleted": deleted, "requires_yes": False}))


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--db", type=Path, default=DEFAULT_DB)
    sub = p.add_subparsers(required=True)

    init = sub.add_parser("init")
    init.add_argument("--symbol")
    init.add_argument("--question")
    init.add_argument("--rounds", type=int, default=3)
    init.add_argument("--run-id", help="Return an existing run instead of creating one")
    init.set_defaults(func=cmd_init)

    fetch = sub.add_parser("fetch")
    fetch.add_argument("--run-id", required=True)
    fetch.add_argument("--news-limit", type=int, default=10)
    fetch.set_defaults(func=cmd_fetch)

    context = sub.add_parser("context")
    context.add_argument("--run-id", required=True)
    context.add_argument("--role", choices=CONTEXT_ROLES, required=True)
    context.set_defaults(func=cmd_context)

    record = sub.add_parser("record")
    record.add_argument("--run-id", required=True)
    record.add_argument(
        "--stage", choices=("analysis", "debate", "verdict"), required=True
    )
    record.add_argument("--actor", required=True)
    record.add_argument("--round", type=int)
    record.add_argument("--verdict", choices=tuple(sorted(RATINGS)))
    record.add_argument("--confidence")
    record.add_argument("--abstain", action="store_true")
    record.add_argument("--replace", action="store_true")
    record.add_argument(
        "--force",
        action="store_true",
        help="Allow recording into a run that has no evidence yet",
    )
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

    runs = sub.add_parser("runs", help="List research runs with record counts")
    runs.add_argument("--limit", type=int, default=50)
    runs.set_defaults(func=cmd_runs)

    purge = sub.add_parser(
        "purge", help="Delete empty shell runs with no evidence and no contributions"
    )
    purge.add_argument(
        "--yes", action="store_true", help="Confirm deletion without prompting"
    )
    purge.set_defaults(func=cmd_purge)

    ui = sub.add_parser("serve", help="Start the local historical research UI")
    ui.add_argument("--reports", type=Path, default=DEFAULT_REPORTS)
    ui.add_argument("--host", default="127.0.0.1")
    ui.add_argument("--port", type=int, default=8765)
    ui.set_defaults(
        func=lambda args: serve(args.db, args.reports, args.host, args.port)
    )
    return p


def main() -> None:
    load_dotenv(DEFAULT_ENV)
    args = parser().parse_args()
    if hasattr(args, "rounds") and args.rounds < 1:
        raise SystemExit("--rounds must be at least 1")
    args.func(args)


if __name__ == "__main__":
    main()
