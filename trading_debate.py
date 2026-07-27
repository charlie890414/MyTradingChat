"""Local evidence, history, and report tools for the Codex trading-debate skill."""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import re
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen
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


def request_json(url: str, params: dict[str, Any] | None = None, headers: dict[str, str] | None = None,
                 method: str = "GET", body: bytes | None = None) -> Any:
    if params:
        url = f"{url}?{urlencode({key: value for key, value in params.items() if value is not None})}"
    request = Request(url, data=body, method=method, headers={"User-Agent": "MyTradingChat/0.1", **(headers or {})})
    with urlopen(request, timeout=20) as response:  # nosec B310: fixed HTTPS provider URLs only
        return json.loads(response.read().decode("utf-8"))


def taiwan_code(symbol: str) -> str | None:
    match = re.fullmatch(r"(\d{4,6})(?:\.(?:TW|TWO))?", symbol.upper())
    return match.group(1) if match else None


def insert_evidence(con: sqlite3.Connection, run_id: str, source: str, title: str, payload: Any,
                    *, url: str | None = None, published_at: str | None = None) -> None:
    con.execute(
        "INSERT INTO evidence(run_id, source, title, url, published_at, payload_json, fetched_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (run_id, source, title, url, published_at, as_json(payload), utc_now()),
    )


def connector_status(con: sqlite3.Connection, run_id: str, source: str, state: str, detail: str) -> None:
    insert_evidence(con, run_id, source, f"Connector {state}", {"state": state, "detail": detail})


def fetch_alpha_vantage(con: sqlite3.Connection, run_id: str, symbol: str, limit: int) -> int:
    key = os.getenv("ALPHA_VANTAGE_API_KEY")
    if not key:
        connector_status(con, run_id, "Alpha Vantage", "skipped", "Set ALPHA_VANTAGE_API_KEY to enable NEWS_SENTIMENT.")
        return 0
    data = request_json("https://www.alphavantage.co/query", {"function": "NEWS_SENTIMENT", "tickers": symbol, "limit": limit, "apikey": key})
    if "Error Message" in data or "Information" in data:
        raise RuntimeError(data.get("Error Message") or data.get("Information"))
    for article in data.get("feed", []):
        insert_evidence(con, run_id, "Alpha Vantage News & Sentiment", article.get("title", "Untitled article"), article,
                        url=article.get("url"), published_at=article.get("time_published"))
    return len(data.get("feed", []))


def fetch_finnhub(con: sqlite3.Connection, run_id: str, symbol: str, limit: int) -> int:
    key = os.getenv("FINNHUB_API_KEY")
    if not key:
        connector_status(con, run_id, "Finnhub", "skipped", "Set FINNHUB_API_KEY to enable company news.")
        return 0
    end = datetime.now(UTC).date()
    start = end - timedelta(days=365)
    items = request_json("https://finnhub.io/api/v1/company-news", {"symbol": symbol, "from": start.isoformat(), "to": end.isoformat(), "token": key})
    if isinstance(items, dict) and items.get("error"):
        raise RuntimeError(items["error"])
    for article in (items or [])[:limit]:
        insert_evidence(con, run_id, "Finnhub Company News", article.get("headline", "Untitled article"), article,
                        url=article.get("url"), published_at=str(article.get("datetime") or ""))
    return len((items or [])[:limit])


def fetch_finmind(con: sqlite3.Connection, run_id: str, symbol: str, limit: int) -> int:
    code = taiwan_code(symbol)
    if not code:
        connector_status(con, run_id, "FinMind", "skipped", "FinMind TaiwanStockNews is only queried for Taiwan ticker codes.")
        return 0
    end = datetime.now(UTC).date()
    data = request_json("https://api.finmindtrade.com/api/v4/data", {
        "dataset": "TaiwanStockNews", "data_id": code, "start_date": (end - timedelta(days=365)).isoformat(),
        "end_date": end.isoformat(), "token": os.getenv("FINMIND_TOKEN"),
    })
    if data.get("status") not in (200, "200"):
        raise RuntimeError(data.get("msg") or data.get("message") or str(data))
    items = data.get("data", [])
    for article in items[-limit:]:
        insert_evidence(con, run_id, "FinMind TaiwanStockNews", article.get("title") or article.get("headline") or "Taiwan stock news", article,
                        url=article.get("link") or article.get("url"), published_at=str(article.get("date") or ""))
    return len(items[-limit:])


def fetch_twse_mops(con: sqlite3.Connection, run_id: str, symbol: str, limit: int = 0) -> int:
    code = taiwan_code(symbol)
    if not code:
        connector_status(con, run_id, "TWSE OpenAPI / MOPS", "skipped", "Official disclosures are only queried for Taiwan ticker codes.")
        return 0
    records = request_json("https://openapi.twse.com.tw/v1/opendata/t187ap04_L")
    profile = next((item for item in records if str(item.get("公司代號", "")).strip() == code), None)
    if not profile:
        connector_status(con, run_id, "TWSE OpenAPI / MOPS", "empty", f"No listed-company profile found for {code}.")
        return 0
    insert_evidence(con, run_id, "TWSE OpenAPI / MOPS", "Official listed-company disclosure profile", profile,
                    url="https://openapi.twse.com.tw/v1/opendata/t187ap04_L")
    return 1


def fetch_reddit_summary(con: sqlite3.Connection, run_id: str, symbol: str, limit: int) -> int:
    client_id, secret = os.getenv("REDDIT_CLIENT_ID"), os.getenv("REDDIT_CLIENT_SECRET")
    if not client_id or not secret:
        connector_status(con, run_id, "Reddit", "skipped", "Set REDDIT_CLIENT_ID and REDDIT_CLIENT_SECRET for official OAuth access.")
        return 0
    token_data = request_json("https://www.reddit.com/api/v1/access_token", headers={"Authorization": "Basic " + __import__("base64").b64encode(f"{client_id}:{secret}".encode()).decode(), "Content-Type": "application/x-www-form-urlencoded"}, method="POST", body=b"grant_type=client_credentials")
    token = token_data.get("access_token")
    if not token:
        raise RuntimeError(token_data.get("error") or "Reddit OAuth token was not returned")
    listing = request_json("https://oauth.reddit.com/search", {"q": symbol, "sort": "new", "limit": limit, "type": "link"}, headers={"Authorization": f"Bearer {token}"})
    posts = listing.get("data", {}).get("children", [])
    aggregate = {"query": symbol, "post_count": len(posts), "score_total": sum(item.get("data", {}).get("score", 0) for item in posts),
                 "comment_total": sum(item.get("data", {}).get("num_comments", 0) for item in posts),
                 "sample_urls": ["https://reddit.com" + item.get("data", {}).get("permalink", "") for item in posts]}
    # Store only an aggregate and URLs: do not retain post bodies or use Reddit user content as model training data.
    insert_evidence(con, run_id, "Reddit public-discussion proxy", "OAuth search aggregate (no post bodies retained)", aggregate)
    return len(posts)


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
        con.execute("DELETE FROM evidence WHERE run_id = ?", (args.run_id,))
        insert_evidence(con, args.run_id, "Yahoo Finance", "Fundamentals snapshot", fundamentals)
        insert_evidence(con, args.run_id, "Yahoo Finance", "One-year price snapshot", price, published_at=price["as_of"])
        stored_news = 0
        for item in news or []:
            content = item.get("content", item)
            title = content.get("title") or item.get("title") or "Untitled Yahoo Finance item"
            url = content.get("canonicalUrl", {}).get("url") or content.get("clickThroughUrl", {}).get("url")
            published = content.get("pubDate") or item.get("providerPublishTime")
            insert_evidence(con, args.run_id, "Yahoo Finance News", title, item, url=url, published_at=str(published) if published else None)
            stored_news += 1
        connectors = {"Alpha Vantage": fetch_alpha_vantage, "Finnhub": fetch_finnhub, "FinMind": fetch_finmind,
                      "TWSE OpenAPI / MOPS": fetch_twse_mops, "Reddit": fetch_reddit_summary}
        connector_counts, connector_errors = {}, {}
        for name, fetcher in connectors.items():
            try:
                connector_counts[name] = fetcher(con, args.run_id, run["symbol"], args.news_limit)
            except (HTTPError, URLError, TimeoutError, ValueError, RuntimeError) as exc:
                connector_errors[name] = str(exc)
                connector_status(con, args.run_id, name, "error", str(exc))
    print(as_json({"run_id": args.run_id, "fundamental_fields": len(fundamentals), "yahoo_news_items": stored_news,
                   "connector_items": connector_counts, "connector_errors": connector_errors, "price": price}))


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
