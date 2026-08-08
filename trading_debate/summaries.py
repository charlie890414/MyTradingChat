"""Pydantic models for persisted machine-readable research summaries."""

from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictBool,
    StrictInt,
    StrictStr,
    model_validator,
)

EvidenceId = Annotated[StrictStr, Field(pattern=r"^EVID-\d{4,}$")]
Confidence = Literal["low", "medium", "high"]
Stance = Literal["bullish", "neutral", "bearish"]
Materiality = Literal["high", "medium", "low"]


class SummaryModel(BaseModel):
    """Base model that preserves forward-compatible agent fields."""

    model_config = ConfigDict(strict=True, extra="allow")


class ContributionSummary(SummaryModel):
    actor: StrictStr
    confidence: Confidence
    evidence_ids: list[EvidenceId] = Field(default_factory=list)
    critical_evidence_ids: list[EvidenceId] = Field(default_factory=list)
    evidence_gaps: list[Any] = Field(default_factory=list)
    stance: Stance | None = None
    round: StrictInt | None = None
    opposing_claims: list[Any] | None = None
    updated_claims: list[Any] | None = None
    unresolved_disagreements: list[Any] | None = None


class NewsMergeMetadata(SummaryModel):
    batch_count: StrictInt = Field(ge=1)
    batch_numbers: list[StrictInt] = Field(min_length=1)
    unique_event_count: StrictInt | None = Field(default=None, ge=1)

    @model_validator(mode="after")
    def validate_batch_numbers(self) -> NewsMergeMetadata:
        if len(set(self.batch_numbers)) != len(self.batch_numbers):
            raise ValueError(
                "merge_metadata.batch_numbers must be unique positive integers"
            )
        if any(number < 1 for number in self.batch_numbers):
            raise ValueError(
                "merge_metadata.batch_numbers must be unique positive integers"
            )
        if max(self.batch_numbers) > self.batch_count:
            raise ValueError("merge_metadata.batch_numbers cannot exceed batch_count")
        return self


class ArticleSummary(SummaryModel):
    evidence_id: EvidenceId
    body_available: StrictBool
    event_date: StrictStr
    summary: StrictStr
    materiality: Materiality
    source_quality: StrictStr
    event_id: StrictStr | None = None
    source_language: StrictStr | None = None
    is_primary: StrictBool | None = None
    related_evidence_ids: list[EvidenceId] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_text(self) -> ArticleSummary:
        if not self.summary.strip():
            raise ValueError("summary must be a non-empty string")
        if not self.source_quality.strip():
            raise ValueError("source_quality must be a non-empty string")
        for field in ("event_id", "source_language"):
            value = getattr(self, field)
            if value is not None and not value.strip():
                raise ValueError(f"{field} must be a non-empty string")
        if self.evidence_id in self.related_evidence_ids:
            raise ValueError(
                "related_evidence_ids must not contain its own evidence_id"
            )
        return self


class NewsContentSummary(SummaryModel):
    actor: Literal["news_content"]
    stance: Literal["neutral"]
    confidence: Confidence
    evidence_ids: list[EvidenceId]
    evidence_gaps: list[Any]
    article_summaries: list[ArticleSummary] = Field(min_length=1)
    upside_catalysts: list[Any] = Field(default_factory=list)
    downside_risks: list[Any] = Field(default_factory=list)
    merge_metadata: NewsMergeMetadata | None = None

    @model_validator(mode="after")
    def validate_articles(self) -> NewsContentSummary:
        evidence_ids = set(self.evidence_ids)
        seen: set[str] = set()
        for index, article in enumerate(self.article_summaries):
            if article.evidence_id not in evidence_ids:
                raise ValueError(
                    f"article_summaries[{index}].evidence_id must also appear in "
                    "evidence_ids"
                )
            if article.evidence_id in seen:
                raise ValueError(
                    f"article_summaries[{index}].evidence_id is duplicated; "
                    "merge batch records by ID first"
                )
            seen.add(article.evidence_id)
            if any(
                related not in evidence_ids for related in article.related_evidence_ids
            ):
                raise ValueError(
                    f"article_summaries[{index}].related_evidence_ids must appear "
                    "in evidence_ids"
                )

        if self.merge_metadata is not None:
            events: dict[str, int] = {}
            for article in self.article_summaries:
                if article.event_id is None or article.is_primary is None:
                    raise ValueError(
                        "merged article summaries must mark event_id and is_primary"
                    )
                if article.is_primary:
                    events[article.event_id] = events.get(article.event_id, 0) + 1
                else:
                    events.setdefault(article.event_id, 0)
            if any(count != 1 for count in events.values()):
                raise ValueError("each merged event must have exactly one primary")
            unique_count = self.merge_metadata.unique_event_count
            if unique_count is not None and unique_count != len(events):
                raise ValueError(
                    "merge_metadata.unique_event_count does not match event_id groups"
                )
        return self


class VerdictSummary(SummaryModel):
    recommendation: Literal["buy", "hold", "reduce"]
    confidence: Confidence
    fetch_time: StrictStr
    critical_evidence_ids: list[EvidenceId] = Field(min_length=1)
