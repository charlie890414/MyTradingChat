"""Markdown report rendering for completed research runs."""

from __future__ import annotations

import argparse
import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path

from .context import (
    ContextSummaryError,
    _validate_contribution_summary,
    _validate_model,
    parse_machine_summary,
    validate_news_content_summary,
)
from .db import assess_evidence, connect, current_evidence, evidence_reference
from .summaries import VerdictSummary
from .utils import as_json


def render_evidence(rows: list[sqlite3.Row]) -> str:
    chunks = []
    for i, row in enumerate(rows, 1):
        link = f" — {row['url']}" if row["url"] else ""
        reference = evidence_reference(row["id"])
        payload = json.loads(row["payload_json"])
        if isinstance(payload, dict):
            payload = {
                key: value for key, value in payload.items() if key != "article_text"
            }
        chunks.append(
            f"{i}. **[{reference}] {row['source']} — {row['title']}**{link}\n"
            f"   - published: {row['published_at'] or 'unknown'}\n"
            f"   - fetched: {row['fetched_at']}\n"
            f"   - `{json.dumps(payload, ensure_ascii=False, sort_keys=True)}`"
        )
    return "\n".join(chunks) or "No evidence captured."


@dataclass(frozen=True)
class RenderedReport:
    markdown: str
    status: str
    limitations: tuple[str, ...]


def render_report_markdown(
    run: sqlite3.Row, evidence: list[sqlite3.Row], parts: list[sqlite3.Row]
) -> RenderedReport:
    """Build a deterministic report from persisted records without filesystem I/O."""
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
    return RenderedReport(
        markdown="\n".join(body).strip() + "\n",
        status=status,
        limitations=tuple(limitations),
    )


def _load_report(db: Path, run_id: str) -> RenderedReport:
    with connect(db) as con:
        run = con.execute("SELECT * FROM runs WHERE id = ?", (run_id,)).fetchone()
        evidence = current_evidence(con, run_id)
        parts = con.execute(
            "SELECT * FROM contributions WHERE run_id = ? ORDER BY id", (run_id,)
        ).fetchall()
    if not run:
        raise SystemExit(f"Unknown run id: {run_id}")
    return render_report_markdown(run, evidence, parts)


def cmd_render(args: argparse.Namespace) -> None:
    rendered = _load_report(args.db, args.run_id)
    with connect(args.db) as con:
        con.execute(
            "UPDATE runs SET status = ?, report_path = NULL WHERE id = ?",
            (rendered.status, args.run_id),
        )
    print(
        as_json(
            {
                "run_id": args.run_id,
                "report_url": f"/runs/{args.run_id}/report",
                "status": rendered.status,
            }
        )
    )


def cmd_export(args: argparse.Namespace) -> None:
    """Write a report only when the caller explicitly provides an export path."""
    rendered = _load_report(args.db, args.run_id)
    output = args.output.expanduser()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(rendered.markdown, encoding="utf-8")
    print(
        as_json(
            {"run_id": args.run_id, "output": str(output), "status": rendered.status}
        )
    )


def _render_status(
    run: sqlite3.Row, evidence: list[sqlite3.Row], parts: list[sqlite3.Row]
) -> tuple[str, list[str]]:
    """Return completion state without allowing an incomplete run to look complete."""
    limitations: list[str] = []
    if not evidence:
        limitations.append("尚未擷取任何證據。")
    analyses = {row["actor"].lower() for row in parts if row["stage"] == "analysis"}
    required_analyses = {
        "fundamentals",
        "technical",
        "news_content",
        "news",
        "sentiment",
    }
    if not required_analyses.issubset(analyses):
        limitations.append("新聞內文總結與四位指定分析師報告尚未齊備。")
    for part in parts:
        if part["stage"] not in {"analysis", "debate"}:
            continue
        try:
            summary = parse_machine_summary(part["summary_json"])
            _validate_contribution_summary(part, summary)
            if part["stage"] == "analysis" and part["actor"] == "news_content":
                validate_news_content_summary(part["summary_json"])
        except ContextSummaryError:
            limitations.append(
                f"{part['stage']}/{part['actor']} 缺少有效的 machine-readable summary。"
            )
    debates = [row for row in parts if row["stage"] == "debate"]
    expected_debates = [
        (actor, round_no)
        for round_no in range(1, run["debate_rounds"] + 1)
        for actor in ("bull", "bear")
    ]
    actual_debates = [(row["actor"].lower(), row["round_no"]) for row in debates]
    if actual_debates != expected_debates:
        limitations.append("牛熊辯論回合尚未完整保存。")
    if not run["verdict"]:
        limitations.append("尚未取得可用的投資委員會評等。")
    else:
        limitations.extend(assess_evidence(evidence))
        verdict_parts = [row for row in parts if row["stage"] == "verdict"]
        if len(verdict_parts) != 1 or verdict_parts[0]["actor"].lower() != "committee":
            limitations.append("投資委員會裁決紀錄不唯一或角色不正確。")
        elif not _valid_verdict_summary(
            run, evidence, verdict_parts[0]["summary_json"]
        ):
            limitations.append(
                "投資委員會缺少與資料庫一致、可驗證的 machine-readable summary。"
            )
    return ("completed" if not limitations else "incomplete", limitations)


def _valid_verdict_summary(
    run: sqlite3.Row, evidence: list[sqlite3.Row], summary_json: str | None
) -> bool:
    """Validate the committee's structured conclusion against persisted data."""
    try:
        summary = _validate_model(VerdictSummary, parse_machine_summary(summary_json))
    except ContextSummaryError:
        return False
    if summary.get("recommendation") != run["verdict"]:
        return False
    if summary.get("confidence") != run["confidence"]:
        return False
    fetched_at = max((row["fetched_at"] for row in evidence), default=None)
    if summary.get("fetch_time") != fetched_at:
        return False
    valid_ids = {evidence_reference(row["id"]) for row in evidence}
    critical_ids = summary.get("critical_evidence_ids")
    return (
        isinstance(critical_ids, list)
        and bool(critical_ids)
        and all(item in valid_ids for item in critical_ids)
    )
