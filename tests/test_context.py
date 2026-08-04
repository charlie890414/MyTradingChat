"""Tests for role-specific model context assembly."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import trading_debate as td
from trading_debate.context import ContextSummaryError, assemble_context


def _run_rows(db_path: Path):
    with td.connect(db_path) as con:
        run = con.execute("SELECT * FROM runs WHERE id = 'run-1'").fetchone()
        evidence = con.execute(
            "SELECT id, source, title, url, published_at, payload_json, "
            "fetched_at, dedup_key FROM evidence ORDER BY id"
        ).fetchall()
        contributions = con.execute(
            "SELECT * FROM contributions ORDER BY id"
        ).fetchall()
    return run, evidence, contributions


def _setup_run(db_path: Path, *, rounds: int = 1) -> None:
    with td.connect(db_path) as con:
        con.execute(
            "INSERT INTO runs(id, symbol, question, debate_rounds, created_at, status) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            ("run-1", "AAPL", "Test", rounds, td.utc_now(), "active"),
        )


def _insert_evidence(
    db_path: Path,
    source: str,
    title: str,
    payload: object,
    *,
    url: str | None = None,
    published_at: str = "2026-07-28",
) -> str:
    with td.connect(db_path) as con:
        con.execute(
            "INSERT INTO evidence(run_id, source, title, url, published_at, "
            "payload_json, fetched_at, dedup_key) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                "run-1",
                source,
                title,
                url,
                published_at,
                json.dumps(payload),
                td.utc_now(),
                f"{source}-{title}-{url or ''}",
            ),
        )
        row_id = con.execute("SELECT last_insert_rowid()").fetchone()[0]
    return f"EVID-{row_id:04d}"


def _summary(**overrides: object) -> str:
    payload = {
        "actor": "technical",
        "stance": "neutral",
        "confidence": "medium",
        "evidence_ids": [],
        "critical_evidence_ids": [],
        "evidence_gaps": [],
        "opposing_claims": [],
        "updated_claims": [],
        "unresolved_disagreements": [],
        **overrides,
    }
    return (
        "# Report\n\n## Machine-readable summary\n```json\n"
        + json.dumps(payload)
        + "\n```"
    )


def _insert_contribution(
    db_path: Path,
    stage: str,
    actor: str,
    content: str,
    round_no: int | None = None,
) -> None:
    with td.connect(db_path) as con:
        con.execute(
            "INSERT INTO contributions(run_id, stage, actor, round_no, content, "
            "created_at) VALUES (?, ?, ?, ?, ?, ?)",
            ("run-1", stage, actor, round_no, content, td.utc_now()),
        )


def test_technical_context_samples_ohlcv_without_mutating_storage(tmp_path: Path):
    db_path = tmp_path / "test.db"
    _setup_run(db_path)
    daily = [
        {
            "date": f"2026-06-{day:02d}",
            "open": day,
            "high": day + 1,
            "low": day - 1,
            "close": day,
            "volume": day * 100,
        }
        for day in range(1, 31)
    ] + [
        {
            "date": f"2026-07-{day:02d}",
            "open": day,
            "high": day + 1,
            "low": day - 1,
            "close": day,
            "volume": day * 100,
        }
        for day in range(1, 29)
    ]
    weekly = [
        {"date": f"2026-01-{(index % 28) + 1:02d}", "close": index}
        for index in range(40)
    ]
    monthly = [
        {"date": f"2025-{month:02d}-28", "close": month} for month in range(1, 13)
    ] + [{"date": "2026-07-31", "close": 20}]
    _insert_evidence(
        db_path,
        "Yahoo Finance",
        "Daily OHLCV history",
        {"bars": len(daily), "records": daily},
    )
    _insert_evidence(
        db_path,
        "Yahoo Finance",
        "Weekly adjusted OHLCV history",
        {"bars": len(weekly), "frequency": "W-FRI", "records": weekly},
    )
    _insert_evidence(
        db_path,
        "Yahoo Finance",
        "Monthly adjusted OHLCV history",
        {"bars": len(monthly), "frequency": "ME", "records": monthly},
    )

    run, evidence, contributions = _run_rows(db_path)
    context = assemble_context(run, evidence, contributions, "technical")
    by_title = {item["title"]: item["payload"] for item in context["evidence"]}

    assert len(by_title["Daily OHLCV history"]["records"]) == 30
    assert len(by_title["Weekly adjusted OHLCV history"]["records"]) == 26
    assert len(by_title["Monthly adjusted OHLCV history"]["records"]) == 12
    assert (
        by_title["Weekly adjusted OHLCV history"]["records"][-1]["partial_period"]
        is True
    )
    assert (
        by_title["Monthly adjusted OHLCV history"]["records"][-1]["partial_period"]
        is True
    )
    with td.connect(db_path) as con:
        stored = json.loads(
            con.execute(
                "SELECT payload_json FROM evidence WHERE title = 'Daily OHLCV history'"
            ).fetchone()[0]
        )
    assert len(stored["records"]) == len(daily)


def test_role_context_excludes_irrelevant_evidence_and_status_items(tmp_path: Path):
    db_path = tmp_path / "test.db"
    _setup_run(db_path)
    _insert_evidence(db_path, "Yahoo Finance", "One-year price snapshot", {"close": 1})
    _insert_evidence(db_path, "Yahoo Finance", "Daily OHLCV history", {"records": []})
    _insert_evidence(
        db_path,
        "SEC EDGAR Company Facts",
        "Official financial facts snapshot",
        {"revenue": 1},
    )
    _insert_evidence(
        db_path,
        "Finnhub",
        "Connector skipped",
        {"state": "skipped", "detail": "no key"},
    )

    run, evidence, contributions = _run_rows(db_path)
    fundamental = assemble_context(run, evidence, contributions, "fundamentals")
    titles = {item["title"] for item in fundamental["evidence"]}

    assert "One-year price snapshot" in titles
    assert "Official financial facts snapshot" in titles
    assert "Daily OHLCV history" not in titles
    assert "Connector skipped" not in titles
    assert fundamental["evidence_gaps"][0]["state"] == "skipped"
    assert all("payload_json" not in item for item in fundamental["evidence"])


def test_news_context_deduplicates_canonical_url_and_title(tmp_path: Path):
    db_path = tmp_path / "test.db"
    _setup_run(db_path)
    _insert_evidence(
        db_path, "Google News RSS", "Same event - Publisher", {"summary": "a"}
    )
    _insert_evidence(db_path, "Bing News RSS", "Same event — Other", {"summary": "b"})
    _insert_evidence(
        db_path,
        "Yahoo Finance News",
        "URL item",
        {"summary": "c"},
        url="https://example.com/story",
    )
    _insert_evidence(
        db_path,
        "Finnhub Company News",
        "URL duplicate",
        {"summary": "d"},
        url="https://example.com/story",
    )

    run, evidence, contributions = _run_rows(db_path)
    context = assemble_context(run, evidence, contributions, "news")

    assert len(context["evidence"]) == 2


def test_fundamental_context_semantically_compacts_finnhub_financials(
    tmp_path: Path,
):
    db_path = tmp_path / "test.db"
    _setup_run(db_path)
    reports = [
        {
            "year": 2026 - index,
            "quarter": 1,
            "report": {
                "ic": [
                    {"label": "Total revenue", "value": 100 - index},
                    {"label": "Immaterial custom item", "value": index},
                ],
                "bs": [{"label": "Total assets", "value": 500 - index}],
            },
        }
        for index in range(6)
    ]
    _insert_evidence(
        db_path,
        "Finnhub Financials As Reported",
        "Quarterly financials as reported",
        {"symbol": "AAPL", "reports": reports},
    )
    _insert_evidence(
        db_path,
        "Finnhub Basic Financials",
        "Basic financial metrics",
        {
            "symbol": "AAPL",
            "metricType": "all",
            "metric": {"revenueGrowthTTM": 0.1, "10DayAverageTradingVolume": 2},
            "series": {
                "quarterly": {
                    "revenuePerShare": list(range(12)),
                    "inventoryTurnover": list(range(12)),
                }
            },
        },
    )

    run, evidence, contributions = _run_rows(db_path)
    context = assemble_context(run, evidence, contributions, "fundamentals")
    by_source = {item["source"]: item["payload"] for item in context["evidence"]}

    reported = by_source["Finnhub Financials As Reported"]
    assert len(reported["reports"]) == 4
    assert reported["reports"][0]["report"]["ic"] == [
        {"label": "Total revenue", "value": 100}
    ]
    basic = by_source["Finnhub Basic Financials"]
    assert basic["metric"] == {"revenueGrowthTTM": 0.1}
    assert basic["series"]["quarterly"]["revenuePerShare"] == list(range(4, 12))


def test_debate_context_uses_summaries_and_previous_full_turn(tmp_path: Path):
    db_path = tmp_path / "test.db"
    _setup_run(db_path, rounds=2)
    evidence_id = _insert_evidence(
        db_path, "Yahoo Finance", "One-year price snapshot", {"close": 100}
    )
    for actor in ("fundamentals", "technical", "news", "sentiment"):
        _insert_contribution(
            db_path,
            "analysis",
            actor,
            _summary(actor=actor, evidence_ids=[evidence_id]),
        )
    bull = _summary(actor="bull", round=1, stance="bullish", evidence_ids=[evidence_id])
    _insert_contribution(db_path, "debate", "bull", bull, round_no=1)

    run, evidence, contributions = _run_rows(db_path)
    context = assemble_context(run, evidence, contributions, "debate")

    assert context["next_turn"] == {"actor": "bear", "round": 1}
    assert context["previous_opposing_turn"]["content"] == bull
    assert len(context["contribution_summaries"]) == 5
    assert [item["evidence_id"] for item in context["referenced_evidence"]] == [
        evidence_id
    ]


def test_committee_context_requires_every_debate_summary(tmp_path: Path):
    db_path = tmp_path / "test.db"
    _setup_run(db_path, rounds=2)
    for actor in ("fundamentals", "technical", "news", "sentiment"):
        _insert_contribution(db_path, "analysis", actor, _summary(actor=actor))
    for actor in ("bull", "bear"):
        _insert_contribution(
            db_path,
            "debate",
            actor,
            _summary(actor=actor, round=1),
            round_no=1,
        )

    run, evidence, contributions = _run_rows(db_path)
    with pytest.raises(ContextSummaryError, match="every debate summary"):
        assemble_context(run, evidence, contributions, "committee")


def test_downstream_context_rejects_missing_machine_summary(tmp_path: Path):
    db_path = tmp_path / "test.db"
    _setup_run(db_path)
    for actor in ("fundamentals", "technical", "news"):
        _insert_contribution(db_path, "analysis", actor, _summary(actor=actor))
    _insert_contribution(db_path, "analysis", "sentiment", "plain Markdown")

    run, evidence, contributions = _run_rows(db_path)
    with pytest.raises(ContextSummaryError, match="analysis/sentiment"):
        assemble_context(run, evidence, contributions, "debate")
