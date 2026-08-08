"""Tests for the local historical research UI's persistence behavior."""

from __future__ import annotations

from pathlib import Path

import trading_debate as td
from trading_debate.web import (
    ResearchApp,
    _detail_evidence,
    _display_contributions,
    _env,
    _layout,
    _resolve_report_path,
)


def _insert_run(db_path: Path, report_path: Path | None = None) -> None:
    with td.connect(db_path) as con:
        con.execute(
            "INSERT INTO runs(id, symbol, question, debate_rounds, created_at, status, "
            "report_path) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                "run-1",
                "NVDA",
                "Test",
                1,
                td.utc_now(),
                "completed",
                str(report_path) if report_path else None,
            ),
        )
        td.insert_evidence(con, "run-1", "Source", "Evidence", {"value": 1})
        con.execute(
            "INSERT INTO contributions(run_id, stage, actor, round_no, content, "
            "summary_json, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                "run-1",
                "analysis",
                "fundamentals",
                None,
                "content",
                None,
                td.utc_now(),
            ),
        )


def test_evidence_reference_is_stable():
    assert td.evidence_reference(12) == "EVID-0012"


def test_report_is_rendered_from_sqlite_without_report_path(tmp_path: Path):
    db_path = tmp_path / "research.sqlite3"
    _insert_run(db_path)
    app = object.__new__(ResearchApp)
    app.db_path = db_path
    sent: dict[str, object] = {}
    app._send = lambda status, body: sent.update(status=status, body=body)

    app._report("run-1")

    assert sent["status"].value == 200
    assert "NVDA 多代理研究報告" in sent["body"]


def test_web_displays_content_without_summary_filter(tmp_path: Path):
    db_path = tmp_path / "research.sqlite3"
    _insert_run(db_path)
    content = (
        "# Human-readable analysis\n\n正文內容\n\n"
        '## Machine-readable summary\n```json\n{"actor":"fundamentals"}\n```'
    )
    with td.connect(db_path) as con:
        con.execute(
            "UPDATE contributions SET content = ? WHERE run_id = ?", (content, "run-1")
        )
        parts = con.execute("SELECT * FROM contributions").fetchall()
        stored = con.execute("SELECT content FROM contributions").fetchone()[0]

    display = _display_contributions(parts, "analysis")
    assert display[0]["content"] == content
    assert stored == content


def test_history_list_includes_dashboard_actions_and_delete_modal(tmp_path: Path):
    db_path = tmp_path / "research.sqlite3"
    _insert_run(db_path)
    app = object.__new__(ResearchApp)
    app.db_path = db_path
    app.reports_path = tmp_path / "reports"

    page = _layout("歷史研究", app._list_content({}))

    assert "操作" in page
    assert "data-delete='run-1'" in page
    assert "delete-modal" in page
    assert "確認刪除" in page
    assert "狀態" in page
    assert "已完成" in page
    assert "證據" in page
    assert "RESEARCH LEDGER" in page
    assert 'class="local-time"' in page


def test_ui_delete_does_not_touch_legacy_report_files(tmp_path: Path):
    db_path = tmp_path / "research.sqlite3"
    reports = tmp_path / "reports"
    report = reports / "2026-07-30" / "NVDA" / "report.md"
    report.parent.mkdir(parents=True)
    report.write_text("report", encoding="utf-8")
    _insert_run(db_path, report)

    app = object.__new__(ResearchApp)
    app.db_path = db_path
    app.reports_path = reports

    assert app._delete("run-1") is None
    assert report.exists()
    assert report.parent.exists()
    with td.connect(db_path) as con:
        assert con.execute("SELECT * FROM runs").fetchall() == []
        assert con.execute("SELECT * FROM evidence").fetchall() == []
        assert con.execute("SELECT * FROM contributions").fetchall() == []


def test_report_path_resolves_windows_path_inside_linux_container(tmp_path: Path):
    reports = tmp_path / "reports"

    resolved = _resolve_report_path(r"reports\2026-07-30\NVDA\report.md", reports)

    assert resolved == reports / "2026-07-30" / "NVDA" / "report.md"


def test_ui_delete_leaves_run_specific_legacy_report_directory(tmp_path: Path):
    db_path = tmp_path / "research.sqlite3"
    reports = tmp_path / "reports"
    report = reports / "2026-07-30" / "NVDA" / "run-1" / "report.md"
    report.parent.mkdir(parents=True)
    report.write_text("report", encoding="utf-8")
    _insert_run(db_path, report)
    app = object.__new__(ResearchApp)
    app.db_path = db_path
    app.reports_path = reports

    assert app._delete("run-1") is None
    assert report.parent.exists()


def test_layout_links_to_static_stylesheet():
    page = _layout("歷史研究", "")
    assert '<link rel="stylesheet" href="/static/style.css">' in page
    assert "Intl.DateTimeFormat('zh-TW'" in page
    assert "time.local-time" in page


def test_history_list_uses_responsive_register_layout():
    style_path = (
        Path(__file__).parent.parent / "trading_debate" / "static" / "style.css"
    )
    style = style_path.read_text(encoding="utf-8")
    assert ".research-register" in style
    assert ".mobile-list" in style
    assert "@media (max-width: 760px)" in style
    assert "prefers-reduced-motion" in style
    assert ".rail-report .button { width: 100%; color: var(--paper-bright);" in style
    assert "grid-template-columns: 2fr repeat(5, 1fr);" in style
    assert ".status-fetching" in style


def test_history_list_includes_mobile_card_view(tmp_path: Path):
    db_path = tmp_path / "research.sqlite3"
    _insert_run(db_path)
    app = object.__new__(ResearchApp)
    app.db_path = db_path
    app.reports_path = tmp_path / "reports"
    page = _layout("歷史研究", app._list_content({}))
    assert "mobile-list" in page
    assert "mobile-card" in page
    assert "NVDA" in page
    assert "data-delete='run-1'" in page
    assert "建檔時間" in page
    assert "證據更新" not in page


def test_detail_groups_research_into_evidence_chain(tmp_path: Path):
    db_path = tmp_path / "research.sqlite3"
    _insert_run(db_path)
    app = object.__new__(ResearchApp)
    app.db_path = db_path
    app.reports_path = tmp_path / "reports"

    with td.connect(db_path) as con:
        run = con.execute("SELECT * FROM runs WHERE id = ?", ("run-1",)).fetchone()
        evidence = con.execute(
            "SELECT * FROM evidence WHERE run_id = ?", ("run-1",)
        ).fetchall()
        parts = con.execute(
            "SELECT * FROM contributions WHERE run_id = ?", ("run-1",)
        ).fetchall()
    page = _layout(
        "NVDA 歷史研究",
        _env.get_template("detail.html").render(
            run_id="run-1",
            symbol=run["symbol"],
            question=run["question"],
            created_at=run["created_at"],
            status=run["status"],
            verdict=run["verdict"],
            confidence=run["confidence"],
            debate_rounds=run["debate_rounds"],
            report="",
            evidence=evidence,
            analyses=[item for item in parts if item["stage"] == "analysis"],
            debates=[],
            verdicts=[],
            latest_evidence=evidence[0]["fetched_at"],
            timeline=[
                {
                    "at": run["created_at"],
                    "label": "建立研究",
                    "detail": run["symbol"],
                }
            ],
        ),
    )

    assert "CHAIN OF CUSTODY" in page
    assert "專家分析" in page
    assert "EVID-0001" in page
    assert 'class="local-time"' in page
    assert "RESEARCH TIMELINE" in page


def test_detail_uses_news_content_summary_instead_of_raw_payload(tmp_path: Path):
    db_path = tmp_path / "research.sqlite3"
    _insert_run(db_path)
    with td.connect(db_path) as con:
        td.insert_evidence(
            con,
            "run-1",
            "Google News RSS",
            "Nvidia event",
            {"summary": "Raw RSS payload", "article_text": "Raw article body"},
            url="https://example.com/news",
            published_at="2026-08-08",
        )
        con.execute(
            "INSERT INTO contributions(run_id, stage, actor, round_no, content, "
            "summary_json, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                "run-1",
                "analysis",
                "news_content",
                None,
                "news summary",
                '{"actor":"news_content","stance":"neutral","confidence":"medium",'
                '"evidence_ids":["EVID-0002"],"evidence_gaps":[],"article_summaries":'
                '[{"evidence_id":"EVID-0002","summary":"Readable event summary",'
                '"body_available":true,"event_date":"2026-08-08",'
                '"source_quality":"high","materiality":"high"}]}',
                td.utc_now(),
            ),
        )
        evidence = con.execute(
            "SELECT * FROM evidence WHERE run_id = ? ORDER BY id", ("run-1",)
        ).fetchall()
        parts = con.execute(
            "SELECT * FROM contributions WHERE run_id = ? ORDER BY id", ("run-1",)
        ).fetchall()

    rows = _detail_evidence(evidence, parts)
    news = rows[1]
    assert news["news_summary"]["summary"] == "Readable event summary"
    assert "payload_json" in news
    page = _env.get_template("detail.html").render(
        run_id="run-1",
        symbol="NVDA",
        question="Test",
        created_at=td.utc_now(),
        status="completed",
        verdict=None,
        confidence=None,
        debate_rounds=1,
        report="",
        evidence=rows,
        analyses=[],
        debates=[],
        verdicts=[],
        latest_evidence=td.utc_now(),
        timeline=[],
    )
    assert "Readable event summary" in page
    assert "Raw RSS payload" not in page
    assert "Raw article body" not in page


def test_detail_explains_missing_or_invalid_news_content_summary(tmp_path: Path):
    db_path = tmp_path / "research.sqlite3"
    _insert_run(db_path)
    with td.connect(db_path) as con:
        td.insert_evidence(
            con,
            "run-1",
            "Google News RSS",
            "Nvidia event",
            {"summary": "Raw RSS payload"},
        )
        evidence = con.execute("SELECT * FROM evidence ORDER BY id").fetchall()
        parts = con.execute("SELECT * FROM contributions ORDER BY id").fetchall()

    missing = _detail_evidence(evidence, parts)[1]
    assert missing["news_summary_status"] == "尚未產生新聞內文總結"

    with td.connect(db_path) as con:
        con.execute(
            "INSERT INTO contributions(run_id, stage, actor, round_no, content, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            ("run-1", "analysis", "news_content", None, "invalid", td.utc_now()),
        )
        parts = con.execute("SELECT * FROM contributions ORDER BY id").fetchall()

    invalid = _detail_evidence(evidence, parts)[1]
    assert invalid["news_summary_status"] == (
        "此新聞內文總結缺少獨立的 Machine-readable summary JSON；"
        "這通常表示該記錄建立於摘要欄位啟用前"
    )


def test_ui_delete_ignores_report_path_outside_configured_directory(tmp_path: Path):
    db_path = tmp_path / "research.sqlite3"
    reports = tmp_path / "reports"
    external = tmp_path / "outside" / "report.md"
    external.parent.mkdir(parents=True)
    external.write_text("report", encoding="utf-8")
    _insert_run(db_path, external)
    app = object.__new__(ResearchApp)
    app.db_path = db_path
    app.reports_path = reports

    assert app._delete("run-1") is None
    assert external.exists()
