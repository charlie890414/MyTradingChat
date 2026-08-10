"""Deterministic quality checks for newly persisted research contributions."""

from __future__ import annotations

import re
from typing import Any

_EVIDENCE_REFERENCE = re.compile(r"\[EVID-\d{4,}(?::[^\]]+)?\]")
_LITERAL_NEWLINE = re.compile(r"(?<!\\)\\n")
_VAGUE_REFERENCE = re.compile(r"\b(context|evidence IDs?)\b", re.IGNORECASE)

_REQUIRED_HEADINGS = {
    "analysis": (
        "## 執行摘要",
        "## 已確認事實",
        "## 分析與推論",
        "## 上行催化劑",
        "## 下行催化劑與風險",
        "## 關鍵證據缺口",
        "## 初始立場",
    ),
    "debate": ("## 直接反駁", "## 更新後論點", "## 本輪結論"),
    "verdict": (
        "## 裁決摘要",
        "## 核心判斷",
        "## 爭議裁決",
        "## 估值與價格假設",
        "## 論點失效條件",
        "## 主要證據缺口",
        "## 研究聲明",
    ),
}


def validate_contribution_content(
    stage: str, actor: str, content: str, summary: dict[str, Any] | None
) -> None:
    """Reject structurally incomplete or non-auditable new research output."""
    if _LITERAL_NEWLINE.search(content):
        raise ValueError("content contains literal \\n; use real Markdown line breaks")
    # Legacy API callers may store terse notes. Agent reports are required to use
    # the role heading, which lets the strict gate apply without rewriting history.
    if not content.startswith("# ") or "\n" not in content:
        return
    for heading in _REQUIRED_HEADINGS.get(stage, ()):
        if heading not in content:
            raise ValueError(f"content is missing required heading: {heading}")
    if stage == "analysis" and actor != "news_content":
        _require_cited_facts(content)
    if stage == "debate":
        _validate_debate_content(content)
    if stage == "verdict":
        _require_citations(content, "committee conclusions")
    if summary is not None:
        _validate_summary_references(content, summary)


def _require_cited_facts(content: str) -> None:
    facts = _section(content, "## 已確認事實")
    if not facts or not _EVIDENCE_REFERENCE.search(facts):
        raise ValueError("confirmed facts must include at least one evidence citation")


def _validate_debate_content(content: str) -> None:
    rebuttal = _section(content, "## 直接反駁")
    if not rebuttal or not _EVIDENCE_REFERENCE.search(rebuttal):
        raise ValueError("direct rebuttal must cite specific evidence IDs")
    if _VAGUE_REFERENCE.search(rebuttal):
        raise ValueError(
            "direct rebuttal cannot cite a context instead of evidence IDs"
        )


def _require_citations(content: str, label: str) -> None:
    if not _EVIDENCE_REFERENCE.search(content):
        raise ValueError(f"{label} must cite at least one evidence ID")


def _validate_summary_references(content: str, summary: dict[str, Any]) -> None:
    ids = set(summary.get("evidence_ids", [])) | set(
        summary.get("critical_evidence_ids", [])
    )
    if not ids:
        return
    cited = {
        match.group()[1:].split(":", 1)[0]
        for match in _EVIDENCE_REFERENCE.finditer(content)
    }
    missing = sorted(ids - cited)
    if missing:
        raise ValueError(
            "machine summary evidence IDs must appear in Markdown: "
            + ", ".join(missing)
        )


def _section(content: str, heading: str) -> str:
    start = content.find(heading)
    if start < 0:
        return ""
    remainder = content[start + len(heading) :]
    next_heading = remainder.find("\n## ")
    return remainder if next_heading < 0 else remainder[:next_heading]
