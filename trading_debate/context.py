"""Role-specific context assembly for downstream research agents."""

from __future__ import annotations

import calendar
import json
import re
import sqlite3
from collections.abc import Iterable
from datetime import date
from typing import Any

from .db import evidence_reference, normalize_contribution_actor

CONTEXT_ROLES = (
    "fundamentals",
    "technical",
    "news_content",
    "news",
    "sentiment",
    "debate",
    "committee",
)

_EVIDENCE_ID_RE = re.compile(r"^EVID-\d{4,}$")
_OHLCV_LIMITS = {
    "Daily OHLCV history": 30,
    "Weekly adjusted OHLCV history": 26,
    "Monthly adjusted OHLCV history": 12,
}
_FINNHUB_METRIC_TERMS = (
    "revenue",
    "sales",
    "grossmargin",
    "operatingmargin",
    "netmargin",
    "eps",
    "ebit",
    "ebitda",
    "freecashflow",
    "cashflowpershare",
    "cashper",
    "debt",
    "currentratio",
    "quickratio",
    "returnon",
    "roa",
    "roe",
    "roic",
    "bookvalue",
    "capex",
    "dividend",
    "pe",
    "pb",
    "pricebook",
    "pricetosales",
    "enterprisevalue",
    "currentev",
    "evto",
)
_REPORTED_LINE_ITEM_TERMS = (
    "revenue",
    "sales",
    "gross profit",
    "operating income",
    "operating loss",
    "net income",
    "net loss",
    "earnings per share",
    "cash and cash equivalents",
    "total assets",
    "total liabilities",
    "stockholders' equity",
    "shareholders' equity",
    "long-term debt",
    "short-term debt",
    "operating activities",
    "capital expenditure",
    "property, plant",
    "free cash flow",
)


class ContextSummaryError(ValueError):
    """Raised when a required downstream machine summary is absent or invalid."""


def parse_machine_summary(summary_json: str | None) -> dict[str, Any]:
    """Decode a machine summary stored in the contributions SQL column."""
    if not summary_json:
        raise ContextSummaryError("missing machine summary JSON")
    try:
        summary = json.loads(summary_json)
    except json.JSONDecodeError as exc:
        raise ContextSummaryError(
            f"invalid Machine-readable summary JSON: {exc}"
        ) from exc
    if not isinstance(summary, dict):
        raise ContextSummaryError("Machine-readable summary must be a JSON object")
    return summary


def validate_news_content_summary(summary_json: str | None) -> dict[str, Any]:
    """Validate the structured handoff produced by the news summarizer."""
    summary = parse_machine_summary(summary_json)
    if summary.get("actor") != "news_content":
        raise ContextSummaryError("news content summary actor must be news_content")
    if summary.get("stance") != "neutral":
        raise ContextSummaryError("news content summary stance must be neutral")
    if summary.get("confidence") not in {"low", "medium", "high"}:
        raise ContextSummaryError(
            "news content summary confidence is missing or invalid"
        )
    if not isinstance(summary.get("evidence_gaps"), list):
        raise ContextSummaryError("news content summary evidence_gaps must be a list")
    _validate_summary_evidence_ids(summary)

    article_summaries = summary.get("article_summaries")
    if not isinstance(article_summaries, list) or not article_summaries:
        raise ContextSummaryError(
            "news content summary article_summaries must be a non-empty list"
        )
    evidence_ids = set(summary["evidence_ids"])
    for index, item in enumerate(article_summaries):
        prefix = f"article_summaries[{index}]"
        if not isinstance(item, dict):
            raise ContextSummaryError(f"{prefix} must be a JSON object")
        evidence_id = item.get("evidence_id")
        if not isinstance(evidence_id, str) or not _EVIDENCE_ID_RE.fullmatch(
            evidence_id
        ):
            raise ContextSummaryError(f"{prefix}.evidence_id must be an evidence ID")
        if evidence_id not in evidence_ids:
            raise ContextSummaryError(
                f"{prefix}.evidence_id must also appear in evidence_ids"
            )
        if not isinstance(item.get("body_available"), bool):
            raise ContextSummaryError(f"{prefix}.body_available must be a boolean")
        if not isinstance(item.get("event_date"), str):
            raise ContextSummaryError(f"{prefix}.event_date must be a string")
        if not isinstance(item.get("summary"), str) or not item["summary"].strip():
            raise ContextSummaryError(f"{prefix}.summary must be a non-empty string")
        if item.get("materiality") not in {"high", "medium", "low"}:
            raise ContextSummaryError(
                f"{prefix}.materiality must be high, medium, or low"
            )
        if (
            not isinstance(item.get("source_quality"), str)
            or not item["source_quality"].strip()
        ):
            raise ContextSummaryError(
                f"{prefix}.source_quality must be a non-empty string"
            )
    return summary


def assemble_context(
    run: sqlite3.Row,
    evidence: list[sqlite3.Row],
    contributions: list[sqlite3.Row],
    role: str,
) -> dict[str, Any]:
    """Build the minimum evidence and prior-stage state needed by ``role``."""
    if role not in CONTEXT_ROLES:
        raise ValueError(f"Unsupported context role: {role}")
    statuses = [_connector_status(row) for row in evidence if _is_status(row)]
    base: dict[str, Any] = {
        "role": role,
        "run": dict(run),
        "evidence_fetched_at": max(
            (row["fetched_at"] for row in evidence), default=None
        ),
        "connector_status": statuses,
        "evidence_gaps": [
            status for status in statuses if status["state"] != "available"
        ],
    }
    investable = [row for row in evidence if not _is_status(row)]
    if role in {"fundamentals", "technical", "news_content", "news", "sentiment"}:
        selected = _select_analyst_evidence(investable, role)
        base["evidence"] = [
            _serialize_evidence(row, include_article_text=role == "news_content")
            for row in selected
        ]
        if role == "news":
            summary = _latest_news_content_summary(contributions)
            base["news_content_summary"] = summary
        return base

    summaries = _required_summaries(run, contributions, role)
    base["contribution_summaries"] = summaries
    referenced_ids = _summary_evidence_ids(summaries)
    evidence_by_id = {
        evidence_reference(row["id"]): row
        for row in evidence
        if not _is_status(row) or evidence_reference(row["id"]) in referenced_ids
    }
    base["referenced_evidence"] = [
        _serialize_evidence(evidence_by_id[item])
        for item in referenced_ids
        if item in evidence_by_id
    ]
    missing_ids = [item for item in referenced_ids if item not in evidence_by_id]
    if missing_ids:
        raise ContextSummaryError(
            "summary references unknown evidence IDs: " + ", ".join(missing_ids)
        )
    if role == "debate":
        base.update(_debate_turn_context(run, contributions))
    else:
        base["latest_full_debate_turns"] = _latest_full_debate_turns(contributions)
    return base


def _connector_status(row: sqlite3.Row) -> dict[str, Any]:
    payload = _payload(row)
    return {
        "evidence_id": evidence_reference(row["id"]),
        "source": row["source"],
        "state": payload.get("state", "unknown")
        if isinstance(payload, dict)
        else "unknown",
        "detail": payload.get("detail") if isinstance(payload, dict) else None,
        "fetched_at": row["fetched_at"],
    }


def _is_status(row: sqlite3.Row) -> bool:
    return str(row["title"]).startswith("Connector ")


def _payload(row: sqlite3.Row) -> Any:
    return json.loads(row["payload_json"])


def _serialize_evidence(
    row: sqlite3.Row, *, include_article_text: bool = False
) -> dict[str, Any]:
    payload = _compact_payload(
        str(row["title"]),
        str(row["source"]),
        _payload(row),
        published_at=row["published_at"],
        include_article_text=include_article_text,
    )
    return {
        "id": row["id"],
        "evidence_id": evidence_reference(row["id"]),
        "source": row["source"],
        "title": row["title"],
        "url": row["url"],
        "published_at": row["published_at"],
        "fetched_at": row["fetched_at"],
        "payload": payload,
    }


def _compact_payload(
    title: str,
    source: str,
    payload: Any,
    *,
    published_at: str | None,
    include_article_text: bool = False,
) -> Any:
    if (
        isinstance(payload, dict)
        and "article_text" in payload
        and not include_article_text
    ):
        payload = {
            key: value for key, value in payload.items() if key != "article_text"
        }
    if title in _OHLCV_LIMITS:
        return _compact_ohlcv(title, payload, published_at)
    if source == "Finnhub Financials As Reported":
        return _compact_reported_financials(payload)
    if source == "Finnhub Basic Financials":
        return _compact_basic_financials(payload)
    return payload


def _compact_ohlcv(title: str, payload: Any, as_of: str | None) -> Any:
    if not isinstance(payload, dict):
        return payload
    records = payload.get("records")
    if not isinstance(records, list):
        return payload
    limit = _OHLCV_LIMITS[title]
    sampled = [dict(row) for row in records[-limit:] if isinstance(row, dict)]
    if sampled and title != "Daily OHLCV history":
        for row in sampled:
            row["partial_period"] = False
        sampled[-1]["partial_period"] = _last_period_is_partial(title, as_of)
    return {
        key: value for key, value in payload.items() if key not in {"records", "bars"}
    } | {
        "source_bars": payload.get("bars", len(records)),
        "sample_bars": len(sampled),
        "records": sampled,
    }


def _last_period_is_partial(title: str, as_of: str | None) -> bool:
    if not as_of:
        return False
    try:
        observed = date.fromisoformat(as_of[:10])
    except ValueError:
        return False
    if title == "Weekly adjusted OHLCV history":
        return observed.weekday() != 4
    return observed.day != calendar.monthrange(observed.year, observed.month)[1]


def _compact_reported_financials(payload: Any) -> Any:
    if not isinstance(payload, dict) or not isinstance(payload.get("reports"), list):
        return payload
    reports = []
    for report in payload["reports"][:4]:
        if not isinstance(report, dict):
            continue
        compact = {key: value for key, value in report.items() if key != "report"}
        statements: dict[str, list[Any]] = {}
        raw_statements = report.get("report")
        if not isinstance(raw_statements, dict):
            compact["report"] = statements
            reports.append(compact)
            continue
        for statement, items in raw_statements.items():
            if not isinstance(items, list):
                continue
            selected = [item for item in items if _is_core_reported_line(item)]
            statements[statement] = selected
        compact["report"] = statements
        reports.append(compact)
    return {"symbol": payload.get("symbol"), "reports": reports}


def _is_core_reported_line(item: Any) -> bool:
    if not isinstance(item, dict):
        return False
    text = f"{item.get('concept', '')} {item.get('label', '')}".lower()
    return any(term in text for term in _REPORTED_LINE_ITEM_TERMS)


def _compact_basic_financials(payload: Any) -> Any:
    if not isinstance(payload, dict):
        return payload
    metric = payload.get("metric")
    compact_metric = (
        {key: value for key, value in metric.items() if _is_core_metric(key)}
        if isinstance(metric, dict)
        else metric
    )
    series = payload.get("series")
    compact_series: Any = series
    if isinstance(series, dict):
        compact_series = {}
        for frequency, metrics in series.items():
            if not isinstance(metrics, dict):
                compact_series[frequency] = metrics
                continue
            compact_series[frequency] = {
                key: value[-8:] if isinstance(value, list) else value
                for key, value in metrics.items()
                if _is_core_metric(key)
            }
    return {
        "symbol": payload.get("symbol"),
        "metricType": payload.get("metricType"),
        "metric": compact_metric,
        "series": compact_series,
    }


def _is_core_metric(name: str) -> bool:
    normalized = re.sub(r"[^a-z]", "", name.lower())
    return any(term in normalized for term in _FINNHUB_METRIC_TERMS)


def _select_analyst_evidence(
    evidence: list[sqlite3.Row], role: str
) -> list[sqlite3.Row]:
    selected = [row for row in evidence if _matches_role(row, role)]
    if role == "news_content":
        selected = [row for row in evidence if _is_news_evidence(row)]
    if role in {"news", "sentiment", "news_content"}:
        selected = _deduplicate_news(selected)
    if role in {"fundamentals", "sentiment"}:
        selected = _prefer_derived_snapshots(selected)
    return sorted(selected, key=_evidence_priority)


def _evidence_priority(row: sqlite3.Row) -> tuple[int, int]:
    """Place primary Taiwan disclosures ahead of convenience-source snapshots."""
    source = str(row["source"])
    if source.startswith(
        ("MOPS ", "TWSE Official", "TPEX Official", "TWSE/TPEX Official")
    ):
        return (0, row["id"])
    if source.startswith("FinMind"):
        return (2, row["id"])
    return (1, row["id"])


def _matches_role(row: sqlite3.Row, role: str) -> bool:
    source = str(row["source"]).lower()
    title = str(row["title"]).lower()
    text = f"{source} {title}"
    price_snapshot = title == "one-year price snapshot"
    if role == "news_content":
        return _is_news_evidence(row)
    if role == "technical":
        return price_snapshot or "technical" in text or "ohlcv" in text
    if role == "news":
        return price_snapshot or any(
            term in text
            for term in (
                "news",
                "mops announcement",
                "mops attachment",
            )
        )
    if role == "sentiment":
        return price_snapshot or any(
            term in text
            for term in (
                "news",
                "recommendation",
                "price target",
                "institutional",
                "margin purchase",
                "short sale",
                "insider",
                "form 4",
            )
        )
    return (
        any(
            term in text
            for term in (
                "fundamental",
                "financial",
                "revenue",
                "income statement",
                "balance sheet",
                "cash flow",
                "earnings",
                "company facts",
                "submissions",
                "eps estimate",
                "price target",
                "company profile",
                "mops attachment",
                "official valuation",
            )
        )
        or price_snapshot
    )


def _is_news_evidence(row: sqlite3.Row) -> bool:
    return "news" in str(row["source"]).lower()


def _latest_news_content_summary(
    contributions: list[sqlite3.Row],
) -> dict[str, Any]:
    for row in reversed(contributions):
        if row["stage"] == "analysis" and row["actor"] == "news_content":
            try:
                return validate_news_content_summary(row["summary_json"])
            except ContextSummaryError as exc:
                raise ContextSummaryError(f"news_content: {exc}") from exc
    raise ContextSummaryError("missing required analysis/news_content summary")


def news_content_summaries(
    contributions: list[sqlite3.Row],
) -> dict[str, dict[str, Any]]:
    """Return news-content summaries keyed by their original evidence ID."""
    summaries, _ = news_content_summary_status(contributions)
    return summaries


def news_content_summary_status(
    contributions: list[sqlite3.Row],
) -> tuple[dict[str, dict[str, Any]], str | None]:
    """Return article summaries and a user-facing reason when unavailable."""
    contribution = next(
        (
            row
            for row in reversed(contributions)
            if row["stage"] == "analysis" and row["actor"] == "news_content"
        ),
        None,
    )
    if not contribution:
        return {}, "尚未產生新聞內文總結"
    if not contribution["summary_json"]:
        return {}, (
            "此新聞內文總結缺少獨立的 Machine-readable summary JSON；"
            "這通常表示該記錄建立於摘要欄位啟用前"
        )
    try:
        summary = validate_news_content_summary(contribution["summary_json"])
    except ContextSummaryError as exc:
        return {}, f"新聞內文總結格式無效：{exc}"
    summaries = {
        item["evidence_id"]: item
        for item in summary["article_summaries"]
        if isinstance(item, dict) and isinstance(item.get("evidence_id"), str)
    }
    if not summaries:
        return {}, "新聞內文總結未提供可對應的文章摘要"
    return summaries, None


def _deduplicate_news(evidence: list[sqlite3.Row]) -> list[sqlite3.Row]:
    seen: set[str] = set()
    result = []
    for row in sorted(
        evidence,
        key=lambda item: (str(item["published_at"] or ""), item["id"]),
        reverse=True,
    ):
        if "news" not in str(row["source"]).lower():
            result.append(row)
            continue
        key = str(row["url"] or "").strip().lower() or _normalized_news_title(
            str(row["title"])
        )
        if key in seen:
            continue
        seen.add(key)
        result.append(row)
    return sorted(result, key=lambda item: item["id"])


def _normalized_news_title(title: str) -> str:
    headline = re.split(r"\s[-–—]\s", title, maxsplit=1)[0]
    return re.sub(r"\W+", "", headline.casefold())


def _prefer_derived_snapshots(evidence: list[sqlite3.Row]) -> list[sqlite3.Row]:
    compact_sources = {
        row["source"] for row in evidence if str(row["title"]).startswith("Latest ")
    }
    if not compact_sources:
        return evidence
    return [
        row
        for row in evidence
        if row["source"] not in compact_sources
        or str(row["title"]).startswith("Latest ")
        or not str(row["source"]).startswith("FinMind")
    ]


def _required_summaries(
    run: sqlite3.Row, contributions: list[sqlite3.Row], role: str
) -> list[dict[str, Any]]:
    required_stages = {"analysis", "debate"}
    rows = [row for row in contributions if row["stage"] in required_stages]
    summaries = []
    for row in rows:
        try:
            summary = parse_machine_summary(row["summary_json"])
        except ContextSummaryError as exc:
            label = f"{row['stage']}/{row['actor']}"
            if row["round_no"]:
                label += f"/round-{row['round_no']}"
            raise ContextSummaryError(f"{label}: {exc}") from exc
        _validate_contribution_summary(row, summary)
        if row["stage"] == "analysis" and row["actor"] == "news_content":
            try:
                validate_news_content_summary(row["summary_json"])
            except ContextSummaryError as exc:
                label = f"{row['stage']}/{row['actor']}"
                raise ContextSummaryError(f"{label}: {exc}") from exc
        _validate_summary_evidence_ids(summary)
        summaries.append(
            {
                "stage": row["stage"],
                "actor": row["actor"],
                "round": row["round_no"],
                "created_at": row["created_at"],
                "summary": summary,
            }
        )
    analysis_actors = {
        item["actor"] for item in summaries if item["stage"] == "analysis"
    }
    missing = {
        "fundamentals",
        "technical",
        "news_content",
        "news",
        "sentiment",
    } - analysis_actors
    if missing:
        raise ContextSummaryError(
            "missing analyst summaries: " + ", ".join(sorted(missing))
        )
    if role == "committee":
        expected = {
            (actor, round_no)
            for round_no in range(1, run["debate_rounds"] + 1)
            for actor in ("bull", "bear")
        }
        actual = {
            (item["actor"], item["round"])
            for item in summaries
            if item["stage"] == "debate"
        }
        if actual != expected:
            raise ContextSummaryError("committee context requires every debate summary")
    return summaries


def _validate_summary_evidence_ids(summary: dict[str, Any]) -> None:
    for key in ("evidence_ids", "critical_evidence_ids"):
        values = summary.get(key, [])
        if not isinstance(values, list) or not all(
            isinstance(item, str) and _EVIDENCE_ID_RE.fullmatch(item) for item in values
        ):
            raise ContextSummaryError(f"{key} must be a list of evidence IDs")


def _validate_contribution_summary(row: sqlite3.Row, summary: dict[str, Any]) -> None:
    try:
        summary_actor = normalize_contribution_actor(
            row["stage"], str(summary.get("actor", ""))
        )
    except ValueError as exc:
        raise ContextSummaryError("summary actor is missing or invalid") from exc
    if summary_actor != row["actor"]:
        raise ContextSummaryError("summary actor does not match persisted actor")
    if summary.get("confidence") not in {"low", "medium", "high"}:
        raise ContextSummaryError("summary confidence is missing or invalid")
    if row["stage"] == "analysis":
        if summary.get("stance") not in {"bullish", "neutral", "bearish"}:
            raise ContextSummaryError("analyst summary stance is missing or invalid")
        if not isinstance(summary.get("evidence_gaps"), list):
            raise ContextSummaryError("analyst evidence_gaps must be a list")
        return
    if summary.get("round") != row["round_no"]:
        raise ContextSummaryError("debate summary round does not match persisted round")
    required_lists = (
        "opposing_claims",
        "updated_claims",
        "unresolved_disagreements",
    )
    if any(not isinstance(summary.get(key), list) for key in required_lists):
        raise ContextSummaryError(
            "debate summary requires opposing, updated, and unresolved claim lists"
        )


def _summary_evidence_ids(summaries: Iterable[dict[str, Any]]) -> list[str]:
    ids: list[str] = []
    for item in summaries:
        summary = item["summary"]
        for key in ("evidence_ids", "critical_evidence_ids"):
            for evidence_id in summary.get(key, []):
                if evidence_id not in ids:
                    ids.append(evidence_id)
    return ids


def _debate_turn_context(
    run: sqlite3.Row, contributions: list[sqlite3.Row]
) -> dict[str, Any]:
    turns = [row for row in contributions if row["stage"] == "debate"]
    expected = [
        (actor, round_no)
        for round_no in range(1, run["debate_rounds"] + 1)
        for actor in ("bull", "bear")
    ]
    next_turn = expected[len(turns)] if len(turns) < len(expected) else None
    prior = None
    if turns:
        row = turns[-1]
        prior = {
            "actor": row["actor"],
            "round": row["round_no"],
            "content": row["content"],
        }
    return {
        "next_turn": (
            {"actor": next_turn[0], "round": next_turn[1]} if next_turn else None
        ),
        "previous_opposing_turn": prior,
    }


def _latest_full_debate_turns(
    contributions: list[sqlite3.Row],
) -> list[dict[str, Any]]:
    latest: dict[str, sqlite3.Row] = {}
    for row in contributions:
        if row["stage"] == "debate":
            latest[row["actor"]] = row
    return [
        {
            "actor": actor,
            "round": latest[actor]["round_no"],
            "content": latest[actor]["content"],
        }
        for actor in ("bull", "bear")
        if actor in latest
    ]
