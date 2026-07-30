"""Markdown report rendering for completed research runs."""

from __future__ import annotations

import argparse
import sqlite3

from .db import connect, evidence_reference
from .utils import as_json


def render_evidence(rows: list[sqlite3.Row]) -> str:
    chunks = []
    for i, row in enumerate(rows, 1):
        link = f" — {row['url']}" if row["url"] else ""
        reference = evidence_reference(row["id"])
        chunks.append(
            f"{i}. **[{reference}] {row['source']} — {row['title']}**{link}\n"
            f"   - published: {row['published_at'] or 'unknown'}\n"
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
    status, limitations = _render_status(run, evidence, parts)
    body = [
        f"# {run['symbol']} 多代理研究報告",
        "",
        f"- 研究 ID：`{run['id']}`",
        f"- 建立時間：{run['created_at']}",
        f"- 問題：{run['question']}",
        f"- 預定辯論回合：{run['debate_rounds']}",
        f"- 狀態：{status}",
        f"- 委員會評等：{run['verdict'] or '棄權／尚未評等'}",
        f"- 信心：{run['confidence'] or '未提供'}",
        "",
        "> 歷史研究僅供脈絡參考；價格、指標與新聞可能已過時，不能視為目前建議。",
        "",
        "## 證據包",
        "",
        render_evidence(evidence),
    ]
    names = {
        "analysis": "分析師報告",
        "debate": "牛熊辯論",
        "verdict": "投資委員會結論",
    }
    for stage in ("analysis", "debate", "verdict"):
        if groups.get(stage):
            body.extend(["", f"## {names[stage]}"])
            for part in groups[stage]:
                round_label = f" — round {part['round_no']}" if part["round_no"] else ""
                body.extend(
                    ["", f"### {part['actor']}{round_label}", "", part["content"]]
                )
    body.extend(["", "## 資料限制", ""])
    body.extend([f"- {item}" for item in limitations] or ["- 無額外限制。"])
    report_date = run["created_at"][:10]
    report_dir = args.reports / report_date / run["symbol"]
    report_dir.mkdir(parents=True, exist_ok=True)
    path = report_dir / "report.md"
    path.write_text("\n".join(body).strip() + "\n", encoding="utf-8")
    with connect(args.db) as con:
        con.execute(
            "UPDATE runs SET status = ?, report_path = ? WHERE id = ?",
            (status, str(path), args.run_id),
        )
    print(as_json({"run_id": args.run_id, "report_path": str(path), "status": status}))


def _render_status(
    run: sqlite3.Row, evidence: list[sqlite3.Row], parts: list[sqlite3.Row]
) -> tuple[str, list[str]]:
    """Return completion state without allowing an incomplete run to look complete."""
    limitations: list[str] = []
    titles = {row["title"] for row in evidence}
    if not evidence:
        limitations.append("尚未擷取任何證據。")
    if not any("price" in title.lower() for title in titles):
        limitations.append("缺少可用的價格證據。")
    if not any("fundamental" in title.lower() for title in titles):
        limitations.append("缺少基本面證據。")
    analyses = {row["actor"].lower() for row in parts if row["stage"] == "analysis"}
    required_analyses = {"fundamentals", "technical", "news", "sentiment"}
    if not required_analyses.issubset(analyses):
        limitations.append("四位指定分析師報告尚未齊備。")
    debates = [row for row in parts if row["stage"] == "debate"]
    expected_turns = run["debate_rounds"] * 2
    if len(debates) != expected_turns:
        limitations.append("牛熊辯論回合尚未完整保存。")
    if not run["verdict"]:
        limitations.append("尚未取得可用的投資委員會評等。")
    return ("completed" if not limitations else "incomplete", limitations)
