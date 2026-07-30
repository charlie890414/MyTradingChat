"""Local, dependency-free web UI for browsing historical research."""

# ruff: noqa: E501

from __future__ import annotations

import html
import mimetypes
import shutil
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, quote, unquote, urlparse

from jinja2 import Environment, FileSystemLoader, select_autoescape
from markupsafe import Markup

from .db import connect, delete_run, evidence_reference

_STATUSES = ("active", "incomplete", "completed", "failed")
_VERDICTS = ("buy", "hold", "reduce", "abstain")

_TEMPLATE_DIR = Path(__file__).parent / "templates"
_STATIC_DIR = Path(__file__).parent / "static"

_env = Environment(
    loader=FileSystemLoader(str(_TEMPLATE_DIR)),
    autoescape=select_autoescape(["html", "xml"]),
)


def _escape(value: object) -> str:
    return html.escape(str(value if value is not None else ""), quote=True)


def _badge(value: str | None, kind: str) -> str:
    label = value or "未評等"
    return f'<span class="badge {kind}-{_escape(value or "abstain")}">{_escape(label)}</span>'


def _urlencode(value: object) -> Markup:
    return Markup(quote(str(value)))


_env.globals["escape"] = _escape
_env.globals["badge"] = _badge
_env.globals["evidence_reference"] = evidence_reference
_env.filters["urlencode"] = _urlencode


def _layout(title: str, content: str) -> str:
    return _env.get_template("layout.html").render(title=title, content=content)


def _options(values: tuple[str, ...], selected: str) -> str:
    labels = {"abstain": "未評等"}
    return "".join(
        f"<option value='{value}'{' selected' if value == selected else ''}>{labels.get(value, value)}</option>"
        for value in values
    )


class ResearchApp(BaseHTTPRequestHandler):
    db_path: Path
    reports_path: Path

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
        form = parse_qs(
            self.rfile.read(int(self.headers.get("Content-Length", "0"))).decode()
        )
        if parsed.path == "/runs/delete":
            run_ids = list(dict.fromkeys(form.get("run_id", [])))
            if not run_ids:
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
                "SELECT id, symbol, question, created_at, status, verdict, confidence, report_path FROM runs"
                + where
                + " ORDER BY created_at DESC LIMIT 100",
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
            evidence = con.execute(
                "SELECT * FROM evidence WHERE run_id = ? ORDER BY id", (run_id,)
            ).fetchall()
            parts = con.execute(
                "SELECT * FROM contributions WHERE run_id = ? ORDER BY id", (run_id,)
            ).fetchall()
        if not run:
            self._send(
                HTTPStatus.NOT_FOUND,
                _layout("找不到研究", _env.get_template("not_found.html").render()),
            )
            return
        report = (
            f"<a class='button' href='/runs/{quote(run_id)}/report'>檢視 Markdown 報表</a>"
            if run["report_path"]
            else "<span class='muted'>尚未產生報表</span>"
        )
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
                    report=report,
                    evidence=evidence,
                    parts=parts,
                ),
            ),
        )

    def _report(self, run_id: str) -> None:
        with connect(self.db_path) as con:
            row = con.execute(
                "SELECT report_path FROM runs WHERE id = ?", (run_id,)
            ).fetchone()
        path = Path(row["report_path"]) if row and row["report_path"] else None
        if not path or not path.is_file():
            self._send(
                HTTPStatus.NOT_FOUND,
                _layout(
                    "報表無法使用",
                    "<h1>報表無法使用</h1><p>保存的研究資料仍可從詳情頁查看。</p>",
                ),
            )
            return
        self._send(
            HTTPStatus.OK,
            _layout(
                "Markdown 報表",
                _env.get_template("report.html").render(
                    run_id=run_id,
                    report_text=path.read_text(encoding="utf-8"),
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
        if not run["report_path"]:
            return None
        try:
            path = Path(run["report_path"]).resolve()
            if path.is_relative_to(self.reports_path.resolve()):
                shutil.rmtree(path.parent)
            else:
                return "研究資料已刪除；報表位於預期目錄外，因此未刪除"
        except OSError as exc:
            return f"研究資料已刪除，但報表無法刪除：{exc}"
        return None

    def _send(self, status: HTTPStatus, body: str) -> None:
        payload = body.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)


def serve(
    db_path: Path, reports_path: Path, host: str = "127.0.0.1", port: int = 8765
) -> None:
    """Serve the local UI until interrupted by the user."""
    handler = type(
        "ConfiguredResearchApp",
        (ResearchApp,),
        {"db_path": db_path, "reports_path": reports_path},
    )
    ThreadingHTTPServer((host, port), handler).serve_forever()
