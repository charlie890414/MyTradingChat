"""Markdown report rendering for completed research runs."""

from __future__ import annotations

import argparse
import sqlite3

from .db import connect
from .utils import as_json


def render_evidence(rows: list[sqlite3.Row]) -> str:
    chunks = []
    for i, row in enumerate(rows, 1):
        link = f" — {row['url']}" if row["url"] else ""
        chunks.append(
            f"{i}. **{row['source']} — {row['title']}**{link}\n"
            f"   - fetched: {row['fetched_at']}\n"
            f"   - `{row['payload_json']}`"
        )
    return "\n".join(chunks) or "No evidence captured."


def cmd_render(args: argparse.Namespace) -> None:
    with connect(args.db) as con:
        run = con.execute("SELECT * FROM runs WHERE id = ?", (args.run_id,)).fetchone()
        evidence = con.execute(
            "SELECT * FROM evidence WHERE run_id = ? ORDER BY id", (args.run_id,)
        ).fetchall()
        parts = con.execute(
            "SELECT * FROM contributions WHERE run_id = ? ORDER BY id", (args.run_id,)
        ).fetchall()
    if not run:
        raise SystemExit(f"Unknown run id: {args.run_id}")
    groups: dict[str, list[sqlite3.Row]] = {}
    for part in parts:
        groups.setdefault(part["stage"], []).append(part)
    body = [
        f"# {run['symbol']} multi-agent research report",
        "",
        f"- Run: `{run['id']}`",
        f"- Created: {run['created_at']}",
        f"- Question: {run['question']}",
        f"- Debate rounds requested: {run['debate_rounds']}",
        "",
        "## Evidence pack",
        "",
        render_evidence(evidence),
    ]
    names = {
        "analysis": "Analyst reports",
        "debate": "Bull/bear debate",
        "verdict": "Investment committee verdict",
    }
    for stage in ("analysis", "debate", "verdict"):
        if groups.get(stage):
            body.extend(["", f"## {names[stage]}"])
            for part in groups[stage]:
                round_label = f" — round {part['round_no']}" if part["round_no"] else ""
                body.extend(
                    ["", f"### {part['actor']}{round_label}", "", part["content"]]
                )
    report_date = run["created_at"][:10]
    report_dir = args.reports / report_date / run["symbol"]
    report_dir.mkdir(parents=True, exist_ok=True)
    path = report_dir / "report.md"
    path.write_text("\n".join(body).strip() + "\n", encoding="utf-8")
    with connect(args.db) as con:
        con.execute(
            "UPDATE runs SET status = 'completed', report_path = ? WHERE id = ?",
            (str(path), args.run_id),
        )
    print(as_json({"run_id": args.run_id, "report_path": str(path)}))
