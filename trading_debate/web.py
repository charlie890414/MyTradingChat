"""Local, dependency-free web UI for browsing historical research."""

# ruff: noqa: E501

from __future__ import annotations

import html
import mimetypes
import secrets
import sqlite3
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, quote, unquote, urlparse

from jinja2 import Environment, FileSystemLoader, select_autoescape
from markupsafe import Markup

from .context import news_content_summary_status
from .db import connect, current_evidence, delete_run, evidence_reference
from .render import render_report_markdown
from .utils import is_news_source

_STATUSES = ("active", "fetching", "incomplete", "completed", "failed")
_VERDICTS = ("buy", "hold", "reduce", "abstain")
_TEMPLATE_DIR = Path(__file__).parent / "templates"
_STATIC_DIR = Path(__file__).parent / "static"
_csrf_token = ""

_env = Environment(
    loader=FileSystemLoader(str(_TEMPLATE_DIR)),
    autoescape=select_autoescape(["html", "xml"]),
)


def _escape(value: object) -> str:
    return html.escape(str(value if value is not None else ""), quote=True)


def _badge(value: str | None, kind: str) -> str:
    labels = {
        "active": "進行中",
        "incomplete": "未完成",
        "completed": "已完成",
        "failed": "失敗",
        "buy": "買入",
        "hold": "持有",
        "reduce": "減碼",
    }
    label = labels.get(value or "", "未評等")
    return f'<span class="badge {kind}-{_escape(value or "abstain")}">{_escape(label)}</span>'


def _urlencode(value: object) -> Markup:
    return Markup(quote(str(value)))


_env.globals["escape"] = _escape
_env.globals["badge"] = _badge
_env.globals["evidence_reference"] = evidence_reference
_env.filters["urlencode"] = _urlencode


def _resolve_report_path(stored_path: str, reports_path: Path) -> Path:
    """Resolve report paths written on either Windows or POSIX hosts."""
    direct = Path(stored_path)
    if direct.is_absolute() or direct.is_file():
        return direct

    normalized = Path(stored_path.replace("\\", "/"))
    parts = normalized.parts
    if parts and parts[0].casefold() == reports_path.name.casefold():
        normalized = Path(*parts[1:])
    return reports_path / normalized


def _layout(title: str, content: str) -> str:
    return _env.get_template("layout.html").render(
        title=title, content=content, csrf_token=_csrf_token
    )


def _options(values: tuple[str, ...], selected: str) -> str:
    labels = {"abstain": "未評等"}
    return "".join(
        f"<option value='{value}'{' selected' if value == selected else ''}>{labels.get(value, value)}</option>"
        for value in values
    )


def _detail_evidence(
    evidence: list[object], contributions: list[object]
) -> list[dict[str, object]]:
    """Build web-safe evidence rows without exposing raw news payloads."""
    summaries, summary_status = news_content_summary_status(contributions)  # type: ignore[arg-type]
    rows: list[dict[str, object]] = []
    for item in evidence:
        row = dict(item)  # type: ignore[arg-type]
        if is_news_source(str(row["source"])):
            summary = summaries.get(evidence_reference(int(row["id"])))
            row["is_news"] = True
            row["news_summary"] = _web_news_summary(summary) if summary else None
            row["news_summary_status"] = (
                None if summary else summary_status or "此新聞未被納入新聞內文總結"
            )
        else:
            row["is_news"] = False
        rows.append(row)
    return rows


def _web_news_summary(summary: dict[str, object]) -> dict[str, object]:
    fields = (
        "body_available",
        "event_date",
        "summary",
        "materiality",
        "source_quality",
    )
    compact = {key: summary[key] for key in fields if key in summary}
    if isinstance(compact.get("summary"), str):
        compact["summary"] = compact["summary"][:1000]
    return compact


def _display_contributions(
    contributions: list[sqlite3.Row], stage: str
) -> list[dict[str, object]]:
    """Return contribution content suitable for the human-facing web UI."""
    return [dict(item) for item in contributions if item["stage"] == stage]


class ResearchApp(BaseHTTPRequestHandler):
    db_path: Path
    csrf_token: str
    _MAX_FORM_BYTES = 16_384

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        if parsed.path == "/":
            self._send(
                HTTPStatus.OK,
                _layout(
                    "歷史研究",
                    self._list_content(parse_qs(parsed.query))
                    + "<style>.panel>.actions label:nth-of-type(2){display:none}</style>"
                    + "<script>document.querySelector('[data-delete-selected]')?.setAttribute('type','button');</script>",
                ),
            )
        elif parsed.path.startswith("/static/"):
            self._send_static(parsed.path[8:])
        elif parsed.path.startswith("/runs/") and parsed.path.endswith("/report"):
            self._report(unquote(parsed.path[6:-7]))
        elif parsed.path.startswith("/runs/"):
            self._detail(unquote(parsed.path[6:]))
        else:
            self._send(
                HTTPStatus.NOT_FOUND,
                _layout("找不到頁面", _env.get_template("not_found.html").render()),
            )

    def do_POST(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        try:
            content_length = int(self.headers.get("Content-Length", "0"))
            if not 0 <= content_length <= self._MAX_FORM_BYTES:
                raise ValueError
            form = parse_qs(self.rfile.read(content_length).decode("utf-8"))
        except (UnicodeDecodeError, ValueError):
            self._send(
                HTTPStatus.BAD_REQUEST,
                _layout("無效請求", "<h1>無效請求</h1><p>表單格式或大小無效。</p>"),
            )
            return
        if not secrets.compare_digest(form.get("csrf_token", [""])[0], self.csrf_token):
            self._send(
                HTTPStatus.FORBIDDEN,
                _layout("未刪除", "<h1>未刪除</h1><p>請重新開啟頁面後再試。</p>"),
            )
            return
        if parsed.path == "/runs/delete":
            run_ids = list(dict.fromkeys(form.get("run_id", [])))
            if not run_ids or form.get("confirmation", [""])[0] != "DELETE":
                self._send(
                    HTTPStatus.BAD_REQUEST,
                    _layout("未刪除", "<h1>未刪除</h1><p>確認文字不符。</p>"),
                )
                return
            warnings = [
                warning for run_id in run_ids if (warning := self._delete(run_id))
            ]
            message = "已刪除 " + str(len(run_ids)) + " 筆研究"
            if warnings:
                message += "；" + "；".join(warnings)
            self.send_response(HTTPStatus.SEE_OTHER)
            self.send_header("Location", "/?message=" + quote(message))
            self.end_headers()
            return
        if not parsed.path.startswith("/runs/") or not parsed.path.endswith("/delete"):
            self._send(
                HTTPStatus.NOT_FOUND,
                _layout("找不到頁面", _env.get_template("not_found.html").render()),
            )
            return
        run_id = unquote(parsed.path[6:-7])
        if form.get("confirmation", [""])[0] != run_id:
            self._send(
                HTTPStatus.BAD_REQUEST,
                _layout("未刪除", "<h1>未刪除</h1><p>確認文字不符。</p>"),
            )
            return
        warning = self._delete(run_id)
        self.send_response(HTTPStatus.SEE_OTHER)
        self.send_header("Location", "/?message=" + quote(warning or "研究已刪除"))
        self.end_headers()

    def _list_content(self, query: dict[str, list[str]]) -> str:
        text, status, verdict = (
            query.get("q", [""])[0].strip(),
            query.get("status", [""])[0],
            query.get("verdict", [""])[0],
        )
        clauses, values = [], []
        if text:
            clauses.append("(symbol LIKE ? OR question LIKE ?)")
            values.extend([f"%{text}%", f"%{text}%"])
        if status:
            clauses.append("status = ?")
            values.append(status)
        if verdict == "abstain":
            clauses.append("verdict IS NULL")
        elif verdict:
            clauses.append("verdict = ?")
            values.append(verdict)
        where = " WHERE " + " AND ".join(clauses) if clauses else ""
        with connect(self.db_path) as con:
            rows = con.execute(
                "SELECT runs.id, runs.symbol, runs.question, runs.created_at, "
                "runs.status, runs.verdict, runs.confidence, runs.report_path, "
                "latest_evidence.fetched_at AS latest_evidence_at "
                "FROM runs LEFT JOIN ("
                "SELECT run_id, MAX(fetched_at) AS fetched_at FROM evidence GROUP BY run_id"
                ") AS latest_evidence ON latest_evidence.run_id = runs.id"
                + where
                + " ORDER BY runs.created_at DESC LIMIT 100",
                values,
            ).fetchall()
            counts = dict(
                con.execute(
                    "SELECT status, COUNT(*) FROM runs GROUP BY status"
                ).fetchall()
            )
            total = con.execute("SELECT COUNT(*) FROM runs").fetchone()[0]
        return _env.get_template("index.html").render(
            message=_escape(query.get("message", [""])[0]),
            total=total,
            status_counts=[(key, counts.get(key, 0)) for key in _STATUSES],
            text=_escape(text),
            status_options=_options(_STATUSES, status),
            verdict_options=_options(_VERDICTS, verdict),
            rows=rows,
        )

    def _detail(self, run_id: str) -> None:
        with connect(self.db_path) as con:
            run = con.execute("SELECT * FROM runs WHERE id = ?", (run_id,)).fetchone()
            evidence = current_evidence(con, run_id)
            parts = con.execute(
                "SELECT * FROM contributions WHERE run_id = ? ORDER BY id", (run_id,)
            ).fetchall()
            latest_evidence = max(
                (item["fetched_at"] for item in evidence), default=None
            )
        if not run:
            self._send(
                HTTPStatus.NOT_FOUND,
                _layout("找不到研究", _env.get_template("not_found.html").render()),
            )
            return
        report = (
            f"<a class='button' href='/runs/{quote(run_id, safe='')}/report'>"
            "檢視 Markdown 報表</a>"
        )
        actor_labels = {
            "fundamentals": "基本面分析",
            "technical": "技術面分析",
            "news_content": "新聞內文總結",
            "news": "新聞與事件分析",
            "sentiment": "情緒分析",
            "bull": "多方觀點",
            "bear": "空方觀點",
            "committee": "投資委員會結論",
        }
        evidence_batches: dict[str, int] = {}
        for item in evidence:
            fetched_at = item["fetched_at"]
            evidence_batches[fetched_at] = evidence_batches.get(fetched_at, 0) + 1
        timeline = [
            {"at": run["created_at"], "label": "建立研究", "detail": run["symbol"]},
            *[
                {
                    "at": fetched_at,
                    "label": "擷取證據",
                    "detail": f"{count} 筆證據",
                }
                for fetched_at, count in evidence_batches.items()
            ],
            *[
                {
                    "at": item["created_at"],
                    "label": "保存研究內容",
                    "detail": (
                        f"第 {item['round_no']} 回合｜"
                        f"{actor_labels.get(item['actor'], item['actor'])}"
                        if item["stage"] == "debate"
                        else actor_labels.get(item["actor"], item["actor"])
                    ),
                }
                for item in parts
            ],
        ]
        timeline.sort(key=lambda item: item["at"])
        self._send(
            HTTPStatus.OK,
            _layout(
                f"{run['symbol']} 歷史研究",
                _env.get_template("detail.html").render(
                    run_id=run_id,
                    symbol=run["symbol"],
                    question=run["question"],
                    created_at=run["created_at"],
                    status=run["status"],
                    verdict=run["verdict"],
                    confidence=run["confidence"],
                    debate_rounds=run["debate_rounds"],
                    report=report,
                    evidence=_detail_evidence(evidence, parts),
                    analyses=_display_contributions(parts, "analysis"),
                    debates=_display_contributions(parts, "debate"),
                    verdicts=_display_contributions(parts, "verdict"),
                    latest_evidence=latest_evidence,
                    timeline=timeline,
                ),
            ),
        )

    def _report(self, run_id: str) -> None:
        with connect(self.db_path) as con:
            run = con.execute("SELECT * FROM runs WHERE id = ?", (run_id,)).fetchone()
            evidence = current_evidence(con, run_id)
            parts = con.execute(
                "SELECT * FROM contributions WHERE run_id = ? ORDER BY id", (run_id,)
            ).fetchall()
        if not run:
            self._send(
                HTTPStatus.NOT_FOUND,
                _layout(
                    "報表無法使用",
                    "<h1>報表無法使用</h1><p>保存的研究資料仍可從詳情頁查看。</p>",
                ),
            )
            return
        rendered = render_report_markdown(run, evidence, parts)
        self._send(
            HTTPStatus.OK,
            _layout(
                "Markdown 報表",
                _env.get_template("report.html").render(
                    run_id=run_id,
                    report_text=rendered.markdown,
                ),
            ),
        )

    def _send_static(self, relative_path: str) -> None:
        requested = (_STATIC_DIR / relative_path).resolve()
        if not requested.is_relative_to(_STATIC_DIR.resolve()):
            self._send(
                HTTPStatus.NOT_FOUND,
                _layout("找不到頁面", _env.get_template("not_found.html").render()),
            )
            return
        if not requested.is_file():
            self._send(
                HTTPStatus.NOT_FOUND,
                _layout("找不到頁面", _env.get_template("not_found.html").render()),
            )
            return
        content_type = (
            mimetypes.guess_type(str(requested))[0] or "application/octet-stream"
        )
        payload = requested.read_bytes()
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def _delete(self, run_id: str) -> str | None:
        with connect(self.db_path) as con:
            run = delete_run(con, run_id)
        if not run:
            return "研究不存在或已刪除"
        return None

    def _send(self, status: HTTPStatus, body: str) -> None:
        payload = body.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)


def serve(db_path: Path, host: str = "127.0.0.1", port: int = 8765) -> None:
    """Serve the local UI until interrupted by the user."""
    global _csrf_token
    _csrf_token = secrets.token_urlsafe(32)
    handler = type(
        "ConfiguredResearchApp",
        (ResearchApp,),
        {"db_path": db_path, "csrf_token": _csrf_token},
    )
    ThreadingHTTPServer((host, port), handler).serve_forever()
