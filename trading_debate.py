"""Local evidence, history, and report tools for the Codex trading-debate skill."""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
import textwrap
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4


ROOT = Path(__file__).resolve().parent
DEFAULT_DB = ROOT / "data" / "research.sqlite3"
DEFAULT_REPORTS = ROOT / "reports"


def utc_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat()


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


def as_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, default=str, sort_keys=True)


def cmd_init(args: argparse.Namespace) -> None:
    run_id = f"{args.symbol.upper()}-{datetime.now():%Y%m%d-%H%M%S}-{uuid4().hex[:6]}"
    with connect(args.db) as con:
        con.execute(
            "INSERT INTO runs(id, symbol, question, debate_rounds, created_at, status) VALUES (?, ?, ?, ?, ?, 'active')",
            (run_id, args.symbol.upper(), args.question, args.rounds, utc_now()),
        )
    print(as_json({"run_id": run_id, "symbol": args.symbol.upper(), "rounds": args.rounds}))


def scalar(value: Any) -> Any:
    try:
        return value.item() if hasattr(value, "item") else value
    except ValueError:
        return str(value)


def cmd_fetch(args: argparse.Namespace) -> None:
    try:
        import yfinance as yf
    except ImportError as exc:
        raise SystemExit("Install dependencies first: python -m pip install -e .") from exc
    with connect(args.db) as con:
        run = con.execute("SELECT symbol FROM runs WHERE id = ?", (args.run_id,)).fetchone()
        if not run:
            raise SystemExit(f"Unknown run id: {args.run_id}")
        ticker = yf.Ticker(run["symbol"])
        info = ticker.get_info()
        history = ticker.history(period="1y", auto_adjust=False)
        news = ticker.get_news(count=args.news_limit, tab="news")
        fields = ["shortName", "longName", "currency", "exchange", "sector", "industry", "marketCap",
                  "trailingPE", "forwardPE", "priceToBook", "dividendYield", "returnOnEquity",
                  "revenueGrowth", "earningsGrowth", "totalRevenue", "freeCashflow", "debtToEquity",
                  "currentPrice", "targetMeanPrice", "recommendationKey"]
        fundamentals = {key: scalar(info.get(key)) for key in fields if info.get(key) is not None}
        closes = history["Close"].dropna() if "Close" in history else []
        price = {"as_of": str(history.index[-1].date()) if len(history) else None,
                 "close": float(closes.iloc[-1]) if len(closes) else None,
                 "return_1y": float(closes.iloc[-1] / closes.iloc[0] - 1) if len(closes) > 1 else None,
                 "high_1y": float(closes.max()) if len(closes) else None,
                 "low_1y": float(closes.min()) if len(closes) else None}
        now = utc_now()
        con.execute("DELETE FROM evidence WHERE run_id = ?", (args.run_id,))
        con.execute("INSERT INTO evidence(run_id, source, title, url, published_at, payload_json, fetched_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (args.run_id, "Yahoo Finance", "Fundamentals snapshot", None, None, as_json(fundamentals), now))
        con.execute("INSERT INTO evidence(run_id, source, title, url, published_at, payload_json, fetched_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (args.run_id, "Yahoo Finance", "One-year price snapshot", None, price["as_of"], as_json(price), now))
        stored_news = 0
        for item in news or []:
            content = item.get("content", item)
            title = content.get("title") or item.get("title") or "Untitled Yahoo Finance item"
            url = content.get("canonicalUrl", {}).get("url") or content.get("clickThroughUrl", {}).get("url")
            published = content.get("pubDate") or item.get("providerPublishTime")
            con.execute("INSERT INTO evidence(run_id, source, title, url, published_at, payload_json, fetched_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                        (args.run_id, "Yahoo Finance News", title, url, str(published) if published else None, as_json(item), now))
            stored_news += 1
    print(as_json({"run_id": args.run_id, "fundamental_fields": len(fundamentals), "news_items": stored_news, "price": price}))


def cmd_context(args: argparse.Namespace) -> None:
    with connect(args.db) as con:
        run = con.execute("SELECT * FROM runs WHERE id = ?", (args.run_id,)).fetchone()
        evidence = con.execute("SELECT source, title, url, published_at, payload_json, fetched_at FROM evidence WHERE run_id = ? ORDER BY id", (args.run_id,)).fetchall()
    if not run:
        raise SystemExit(f"Unknown run id: {args.run_id}")
    print(as_json({"run": dict(run), "evidence": [{**dict(row), "payload": json.loads(row["payload_json"])} for row in evidence]}))


def cmd_record(args: argparse.Namespace) -> None:
    content = Path(args.content_file).read_text(encoding="utf-8") if args.content_file else args.content
    if not content or not content.strip():
        raise SystemExit("Provide non-empty --content or --content-file")
    with connect(args.db) as con:
        if not con.execute("SELECT 1 FROM runs WHERE id = ?", (args.run_id,)).fetchone():
            raise SystemExit(f"Unknown run id: {args.run_id}")
        con.execute("INSERT INTO contributions(run_id, stage, actor, round_no, content, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                    (args.run_id, args.stage, args.actor, args.round, content.strip(), utc_now()))
    print(as_json({"recorded": True, "run_id": args.run_id, "actor": args.actor, "stage": args.stage}))


def render_evidence(rows: list[sqlite3.Row]) -> str:
    chunks = []
    for i, row in enumerate(rows, 1):
        link = f" — {row['url']}" if row["url"] else ""
        chunks.append(f"{i}. **{row['source']} — {row['title']}**{link}\n   - fetched: {row['fetched_at']}\n   - `{row['payload_json']}`")
    return "\n".join(chunks) or "No evidence captured."


def cmd_render(args: argparse.Namespace) -> None:
    with connect(args.db) as con:
        run = con.execute("SELECT * FROM runs WHERE id = ?", (args.run_id,)).fetchone()
        evidence = con.execute("SELECT * FROM evidence WHERE run_id = ? ORDER BY id", (args.run_id,)).fetchall()
        parts = con.execute("SELECT * FROM contributions WHERE run_id = ? ORDER BY id", (args.run_id,)).fetchall()
    if not run:
        raise SystemExit(f"Unknown run id: {args.run_id}")
    groups: dict[str, list[sqlite3.Row]] = {}
    for part in parts:
        groups.setdefault(part["stage"], []).append(part)
    body = [f"# {run['symbol']} multi-agent research report", "", f"- Run: `{run['id']}`", f"- Created: {run['created_at']}", f"- Question: {run['question']}", f"- Debate rounds requested: {run['debate_rounds']}", "", "## Evidence pack", "", render_evidence(evidence)]
    names = {"analysis": "Analyst reports", "debate": "Bull/bear debate", "verdict": "Investment committee verdict"}
    for stage in ("analysis", "debate", "verdict"):
        if groups.get(stage):
            body.extend(["", f"## {names[stage]}"])
            for part in groups[stage]:
                round_label = f" — round {part['round_no']}" if part["round_no"] else ""
                body.extend(["", f"### {part['actor']}{round_label}", "", part["content"]])
    report_dir = args.reports
    report_dir.mkdir(parents=True, exist_ok=True)
    path = report_dir / f"{run['id']}.md"
    path.write_text("\n".join(body).strip() + "\n", encoding="utf-8")
    with connect(args.db) as con:
        con.execute("UPDATE runs SET status = 'completed', report_path = ? WHERE id = ?", (str(path), args.run_id))
    print(as_json({"run_id": args.run_id, "report_path": str(path)}))


def cmd_search(args: argparse.Namespace) -> None:
    term = f"%{args.query}%"
    with connect(args.db) as con:
        rows = con.execute("SELECT id, symbol, question, created_at, status, report_path FROM runs WHERE symbol LIKE ? OR question LIKE ? OR id IN (SELECT run_id FROM contributions WHERE content LIKE ?) ORDER BY created_at DESC LIMIT ?", (term, term, term, args.limit)).fetchall()
    print(as_json([dict(row) for row in rows]))


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--db", type=Path, default=DEFAULT_DB)
    sub = p.add_subparsers(required=True)
    init = sub.add_parser("init"); init.add_argument("--symbol", required=True); init.add_argument("--question", required=True); init.add_argument("--rounds", type=int, default=3); init.set_defaults(func=cmd_init)
    fetch = sub.add_parser("fetch"); fetch.add_argument("--run-id", required=True); fetch.add_argument("--news-limit", type=int, default=10); fetch.set_defaults(func=cmd_fetch)
    context = sub.add_parser("context"); context.add_argument("--run-id", required=True); context.set_defaults(func=cmd_context)
    record = sub.add_parser("record"); record.add_argument("--run-id", required=True); record.add_argument("--stage", choices=("analysis", "debate", "verdict"), required=True); record.add_argument("--actor", required=True); record.add_argument("--round", type=int); source = record.add_mutually_exclusive_group(required=True); source.add_argument("--content"); source.add_argument("--content-file"); record.set_defaults(func=cmd_record)
    render = sub.add_parser("render"); render.add_argument("--run-id", required=True); render.add_argument("--reports", type=Path, default=DEFAULT_REPORTS); render.set_defaults(func=cmd_render)
    search = sub.add_parser("search"); search.add_argument("--query", required=True); search.add_argument("--limit", type=int, default=10); search.set_defaults(func=cmd_search)
    return p


def main() -> None:
    args = parser().parse_args()
    if hasattr(args, "rounds") and args.rounds < 1:
        raise SystemExit("--rounds must be at least 1")
    args.func(args)


if __name__ == "__main__":
    main()
