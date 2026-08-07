"""Shared data models for the trading-debate package."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .utils import canonical_evidence_key


@dataclass
class EvidenceItem:
    """A single piece of evidence to be persisted for a research run."""

    run_id: str
    source: str
    title: str
    payload: Any
    url: str | None = None
    published_at: str | None = None
    dedup_key: str = field(default="", compare=True)

    def __post_init__(self) -> None:
        if not self.dedup_key:
            self.dedup_key = canonical_evidence_key(
                self.source, self.title, self.url, self.published_at
            )


@dataclass
class YahooFetchResult:
    """Yahoo Finance fetch result with both evidence items and summary data."""

    items: list[EvidenceItem]
    fundamentals: dict[str, Any]
    price: dict[str, Any]
    technicals: dict[str, Any]
    stored_news: int
