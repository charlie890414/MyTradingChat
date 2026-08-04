"""Tests for the local historical research UI's persistence behavior."""

from __future__ import annotations

from pathlib import Path

import trading_debate as td
from trading_debate.web import ResearchApp, _layout, _resolve_report_path


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
            "INSERT INTO contributions(run_id, stage, actor, round_no, content, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            ("run-1", "analysis", "fundamentals", None, "content", td.utc_now()),
        )


def test_evidence_reference_is_stable():
    assert td.evidence_reference(12) == "EVID-0012"


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
    assert "completed" in page


def test_ui_delete_removes_legacy_report_without_shared_directory(tmp_path: Path):
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
    assert not report.exists()
    assert report.parent.exists()
    with td.connect(db_path) as con:
        assert con.execute("SELECT * FROM runs").fetchall() == []
        assert con.execute("SELECT * FROM evidence").fetchall() == []
        assert con.execute("SELECT * FROM contributions").fetchall() == []


def test_report_path_resolves_windows_path_inside_linux_container(tmp_path: Path):
    reports = tmp_path / "reports"

    resolved = _resolve_report_path(r"reports\2026-07-30\NVDA\report.md", reports)

    assert resolved == reports / "2026-07-30" / "NVDA" / "report.md"


def test_ui_delete_removes_run_specific_report_directory(tmp_path: Path):
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
    assert not report.parent.exists()


def test_layout_links_to_static_stylesheet():
    page = _layout("歷史研究", "")
    assert '<link rel="stylesheet" href="/static/style.css">' in page


def test_history_list_layout_allocates_space_for_confidence_and_actions():
    style_path = (
        Path(__file__).parent.parent / "trading_debate" / "static" / "style.css"
    )
    style = style_path.read_text(encoding="utf-8")
    assert "width: 85px" in style
    assert "width: 160px" in style
    assert "overflow-wrap: anywhere" in style
    assert "flex-wrap: wrap" in style


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


def test_ui_delete_keeps_report_outside_configured_directory(tmp_path: Path):
    db_path = tmp_path / "research.sqlite3"
    reports = tmp_path / "reports"
    external = tmp_path / "outside" / "report.md"
    external.parent.mkdir(parents=True)
    external.write_text("report", encoding="utf-8")
    _insert_run(db_path, external)
    app = object.__new__(ResearchApp)
    app.db_path = db_path
    app.reports_path = reports

    assert "未刪除" in (app._delete("run-1") or "")
    assert external.exists()
