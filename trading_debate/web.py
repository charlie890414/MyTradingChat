"""Local, dependency-free web UI for browsing historical research."""

# ruff: noqa: E501

from __future__ import annotations

import html
import shutil
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, quote, unquote, urlparse

from .db import connect, delete_run, evidence_reference

_STATUSES = ("active", "incomplete", "completed", "failed")
_VERDICTS = ("buy", "hold", "reduce", "abstain")


def _escape(value: object) -> str:
    return html.escape(str(value if value is not None else ""), quote=True)


def _badge(value: str | None, kind: str) -> str:
    label = value or "未評等"
    return f'<span class="badge {kind}-{_escape(value or "abstain")}">{_escape(label)}</span>'


def _layout(title: str, content: str) -> str:
    return f"""<!doctype html><html lang="zh-Hant"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><title>{_escape(title)}｜MyTradingChat</title>
<style>
:root{{color-scheme:light;--navy:#0d1b2a;--blue:#1677c8;--ink:#162536;--muted:#627385;--line:#dce4ec;--panel:#fff;--ground:#f4f7fb;--danger:#c73737;--warn:#a86700;--green:#16834b}}
*{{box-sizing:border-box}}body{{margin:0;background:var(--ground);color:var(--ink);font:15px/1.55 Inter,"Noto Sans TC",system-ui,sans-serif}}a{{color:var(--blue);text-decoration:none}}a:hover{{text-decoration:underline}}.nav{{background:var(--navy);color:#fff;padding:16px 0;box-shadow:0 2px 12px #0003}}.nav-inner,.page{{max-width:1180px;margin:auto;padding:0 24px}}.brand{{font-weight:800;font-size:18px;color:#fff}}.brand span{{color:#76c7ff}}.page{{padding-top:28px;padding-bottom:48px}}h1,h2{{margin:0 0 8px;line-height:1.25}}h1{{font-size:28px}}h2{{font-size:18px;margin-top:28px}}.subtle,.muted{{color:var(--muted)}}.notice{{margin:20px 0;padding:12px 16px;border:1px solid #f2d18a;border-left:4px solid #d28b00;background:#fffaf0;border-radius:8px}}.notice.success{{border-color:#a5dfbf;border-left-color:var(--green);background:#f1fff6}}.cards{{display:grid;grid-template-columns:repeat(5,1fr);gap:12px;margin:24px 0}}.card,.panel{{background:var(--panel);border:1px solid var(--line);border-radius:12px;box-shadow:0 2px 6px #0d1b2a0a}}.card{{padding:16px}}.card b{{display:block;font-size:24px}}.card span{{color:var(--muted);font-size:13px}}.panel{{padding:20px}}.filters{{display:flex;gap:10px;align-items:end;flex-wrap:wrap}}.field{{display:grid;gap:5px;font-size:13px;color:var(--muted)}}input,select,button{{font:inherit;border-radius:7px;padding:9px 10px;border:1px solid #cbd6e2;background:#fff}}input{{min-width:230px}}button,.button{{display:inline-flex;align-items:center;justify-content:center;gap:6px;border:0;background:var(--blue);color:#fff;font-weight:700;cursor:pointer;text-decoration:none;padding:9px 12px;border-radius:7px}}button:hover,.button:hover{{filter:brightness(.94);text-decoration:none}}.button.secondary{{background:#e8f2fb;color:#1268ae}}.button.danger{{background:var(--danger)}}.table-wrap{{overflow-x:auto;margin-top:18px}}table{{width:100%;border-collapse:collapse;min-width:900px}}th{{text-transform:uppercase;font-size:11px;letter-spacing:.05em;color:var(--muted);background:#f8fafc}}th,td{{padding:13px 12px;text-align:left;border-bottom:1px solid var(--line);vertical-align:middle}}tr:last-child td{{border:0}}.symbol{{font-weight:800;color:var(--ink)}}.actions{{display:flex;gap:8px;white-space:nowrap}}.badge{{display:inline-block;padding:3px 8px;border-radius:999px;font-size:12px;font-weight:750;background:#e9eef4;color:#425264}}.status-completed,.verdict-buy{{background:#dcf7e8;color:#10703d}}.status-active{{background:#ddebfa;color:#145e9e}}.status-incomplete,.verdict-hold,.verdict-abstain{{background:#fff1d2;color:#875600}}.status-failed,.verdict-reduce{{background:#ffe2e2;color:#a52d2d}}.meta{{display:grid;grid-template-columns:repeat(4,1fr);gap:12px}}.meta .card b{{font-size:15px;margin-top:4px;overflow-wrap:anywhere}}details{{border:1px solid var(--line);border-radius:9px;padding:12px 14px;margin:9px 0;background:#fff}}summary{{font-weight:750;cursor:pointer}}pre{{white-space:pre-wrap;overflow-wrap:anywhere;background:#f7f9fc;border:1px solid var(--line);padding:12px;border-radius:7px}}.danger-zone{{border-color:#f0b6b6;background:#fff7f7}}.modal{{position:fixed;inset:0;background:#08111ccc;display:none;align-items:center;justify-content:center;padding:20px;z-index:10}}.modal.open{{display:flex}}.dialog{{width:min(480px,100%);background:#fff;border-radius:14px;padding:24px;box-shadow:0 20px 60px #0008}}.dialog h2{{margin-top:0}}.dialog .run-id{{padding:9px;background:#f4f7fb;border-radius:6px;font-family:ui-monospace,monospace;overflow-wrap:anywhere}}.dialog-actions{{display:flex;justify-content:flex-end;gap:8px;margin-top:16px}}@media(max-width:760px){{.nav-inner,.page{{padding-left:16px;padding-right:16px}}.cards,.meta{{grid-template-columns:repeat(2,1fr)}}.filters .field{{width:100%}}.filters input,.filters select{{width:100%}}}}
input[type=checkbox]{{min-width:0;padding:0;width:16px;height:16px;accent-color:var(--blue)}}.panel>.actions{{align-items:center;gap:14px;padding-bottom:12px;border-bottom:1px solid var(--line)}}.panel>.actions label{{display:flex;align-items:center;gap:7px;white-space:nowrap}}.table-wrap table{{min-width:1050px;table-layout:fixed}}.table-wrap th:nth-child(1){{width:42px}}.table-wrap th:nth-child(2){{width:90px}}.table-wrap th:nth-child(3){{width:255px}}.table-wrap th:nth-child(4){{width:210px}}.table-wrap th:nth-child(5){{width:100px}}.table-wrap th:nth-child(6){{width:80px}}.table-wrap th:nth-child(7){{width:55px}}.table-wrap th:nth-child(8){{width:150px}}.table-wrap td:nth-child(4){{white-space:nowrap;font-variant-numeric:tabular-nums}}.table-wrap td:nth-child(8){{white-space:nowrap}}
</style></head><body><header class="nav"><div class="nav-inner"><a class="brand" href="/">My<span>Trading</span>Chat</a></div></header><main class="page"><div class="notice">歷史研究僅供脈絡參考；價格、指標與新聞可能已過時，不能視為目前建議。</div>{content}</main>
<div class="modal" id="delete-modal" aria-hidden="true"><form class="dialog" method="post" id="delete-form"><h2>刪除研究</h2><p>這將永久刪除研究、證據、分析、辯論及報表目錄，無法復原。</p><p id="delete-question"></p><p class="run-id" id="delete-run-id"></p><div class="dialog-actions"><button class="secondary" type="button" data-close-modal>取消</button><button class="danger" type="submit">確認刪除</button></div></form></div>
<script>const m=document.getElementById('delete-modal'),f=document.getElementById('delete-form'),rid=document.getElementById('delete-run-id'),q=document.getElementById('delete-question');function openDelete(action,summary,ids){{f.action=action;f.querySelectorAll('[name=run_id]').forEach(x=>x.remove());(ids||[]).forEach(id=>{{const x=document.createElement('input');x.type='hidden';x.name='run_id';x.value=id;f.append(x)}});q.textContent=summary;rid.textContent=ids?'共 '+ids.length+' 筆研究':action.split('/')[2];m.classList.add('open');m.setAttribute('aria-hidden','false')}}document.querySelectorAll('[data-delete]').forEach(b=>b.addEventListener('click',()=>openDelete('/runs/'+encodeURIComponent(b.dataset.delete)+'/delete',b.dataset.symbol+'｜'+b.dataset.question)));document.querySelector('[data-delete-selected]')?.addEventListener('click',()=>{{const ids=[...document.querySelectorAll('[data-select-run]:checked')].map(x=>x.value);if(ids.length)openDelete('/runs/delete','即將刪除已選取的研究',ids)}});document.querySelectorAll('[data-close-modal]').forEach(b=>b.addEventListener('click',()=>m.classList.remove('open')));m.addEventListener('click',e=>{{if(e.target===m)m.classList.remove('open')}});</script></body></html>"""


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
        elif parsed.path.startswith("/runs/") and parsed.path.endswith("/report"):
            self._report(unquote(parsed.path[6:-7]))
        elif parsed.path.startswith("/runs/"):
            self._detail(unquote(parsed.path[6:]))
        else:
            self._send(
                HTTPStatus.NOT_FOUND, _layout("找不到頁面", "<h1>找不到頁面</h1>")
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
                HTTPStatus.NOT_FOUND, _layout("找不到頁面", "<h1>找不到頁面</h1>")
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
        cards = "".join(
            f'<div class="card"><b>{counts.get(key, 0)}</b><span>{key}</span></div>'
            for key in _STATUSES
        )
        rows_html = (
            "".join(
                f"<tr><td><input type='checkbox' name='run_id' value='{_escape(row['id'])}' data-select-run></td><td><a class='symbol' href='/runs/{quote(row['id'])}'>{_escape(row['symbol'])}</a></td><td>{_escape(row['question'])}</td><td>{_escape(row['created_at'])}</td><td>{_badge(row['status'], 'status')}</td><td>{_badge(row['verdict'], 'verdict')}</td><td>{_escape(row['confidence'] or '—')}</td><td><div class='actions'><a class='button secondary' href='/runs/{quote(row['id'])}'>查看</a><button class='danger' type='button' data-delete='{_escape(row['id'])}' data-symbol='{_escape(row['symbol'])}' data-question='{_escape(row['question'])}'>🗑 刪除</button></div></td></tr>"
                for row in rows
            )
            or "<tr><td colspan='8' class='muted'>沒有符合條件的研究。</td></tr>"
        )
        message = _escape(query.get("message", [""])[0])
        return f"""<h1>歷史研究</h1><p class="subtle">集中檢視已保存的研究、證據與委員會結論。</p>{f'<div class="notice success">{message}</div>' if message else ""}<div class="cards"><div class="card"><b>{total}</b><span>全部研究</span></div>{cards}</div><section class="panel"><form class="filters" method="get"><label class="field">搜尋<input name="q" value="{_escape(text)}" placeholder="代號或研究問題"></label><label class="field">狀態<select name="status"><option value="">全部</option>{_options(_STATUSES, status)}</select></label><label class="field">評等<select name="verdict"><option value="">全部</option>{_options(_VERDICTS, verdict)}</select></label><button>篩選研究</button></form></section><form class="panel" method="post" action="/runs/delete"><div class="actions"><label><input type="checkbox" data-select-all> 全選</label><strong data-selected-count>已選取 0 筆</strong><label>輸入 <code>DELETE N</code> 確認<input name="confirm" placeholder="例如 DELETE 2"></label><button class="danger" data-delete-selected disabled>刪除已選取項目</button></div><div class="table-wrap"><table><thead><tr><th></th><th>代號</th><th>問題</th><th>建立時間</th><th>狀態</th><th>評等</th><th>信心</th><th>操作</th></tr></thead><tbody>{rows_html}</tbody></table></div></form><script>const all=document.querySelector('[data-select-all]'),selected=()=>[...document.querySelectorAll('[data-select-run]:checked')];function updateBulk(){{const n=selected().length;document.querySelector('[data-selected-count]').textContent='已選取 '+n+' 筆';document.querySelector('[data-delete-selected]').disabled=!n;}}all?.addEventListener('change',e=>{{document.querySelectorAll('[data-select-run]').forEach(x=>x.checked=e.target.checked);updateBulk()}});document.querySelectorAll('[data-select-run]').forEach(x=>x.addEventListener('change',updateBulk));</script>"""

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
                HTTPStatus.NOT_FOUND, _layout("找不到研究", "<h1>找不到研究</h1>")
            )
            return
        evidence_html = "".join(_evidence_detail(row) for row in evidence)
        evidence_html = evidence_html or "<p class='muted'>沒有證據。</p>"
        parts_html = (
            "".join(
                f"<details><summary>{_escape(row['stage'])} — {_escape(row['actor'])}{'（第 ' + str(row['round_no']) + ' 回合）' if row['round_no'] else ''}</summary><pre>{_escape(row['content'])}</pre></details>"
                for row in parts
            )
            or "<p class='muted'>沒有已保存的工作流程內容。</p>"
        )
        report = (
            f"<a class='button' href='/runs/{quote(run_id)}/report'>檢視 Markdown 報表</a>"
            if run["report_path"]
            else "<span class='muted'>尚未產生報表</span>"
        )
        symbol, question = _escape(run["symbol"]), _escape(run["question"])
        content = f"""<p><a href="/">← 返回歷史研究</a></p><h1>{symbol}</h1><p class="subtle">{question}</p><div class="meta"><div class="card"><span>研究 ID</span><b>{_escape(run["id"])}</b></div><div class="card"><span>建立時間</span><b>{_escape(run["created_at"])}</b></div><div class="card"><span>狀態／評等</span><b>{_badge(run["status"], "status")} {_badge(run["verdict"], "verdict")}</b></div><div class="card"><span>信心</span><b>{_escape(run["confidence"] or "—")}</b></div></div><p>{report}</p><h2>證據包</h2>{evidence_html}<h2>分析、辯論與委員會</h2>{parts_html}<section class="panel danger-zone"><h2>危險操作</h2><p>永久刪除這筆研究及其所有資料，無法復原。</p><button class="danger" type="button" data-delete="{_escape(run_id)}" data-symbol="{symbol}" data-question="{question}">🗑 刪除研究</button></section>"""
        self._send(HTTPStatus.OK, _layout(f"{run['symbol']} 歷史研究", content))

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
                f"<p><a href='/runs/{quote(run_id)}'>← 返回研究詳情</a></p><h1>Markdown 報表</h1><pre>{_escape(path.read_text(encoding='utf-8'))}</pre>",
            ),
        )

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


def _options(values: tuple[str, ...], selected: str) -> str:
    labels = {"abstain": "未評等"}
    return "".join(
        f"<option value='{value}'{' selected' if value == selected else ''}>{labels.get(value, value)}</option>"
        for value in values
    )


def _evidence_detail(row: object) -> str:
    url = row["url"]
    link = (
        f'<p><a href="{_escape(url)}" target="_blank">開啟來源 ↗</a></p>' if url else ""
    )
    return (
        f"<details><summary>[{evidence_reference(row['id'])}] "
        f"{_escape(row['source'])} — {_escape(row['title'])}</summary>"
        f"<p class='muted'>發布：{_escape(row['published_at'] or '未知')}｜"
        f"擷取：{_escape(row['fetched_at'])}</p>{link}"
        f"<pre>{_escape(row['payload_json'])}</pre></details>"
    )


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
