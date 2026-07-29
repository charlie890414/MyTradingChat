"""Shared data models for the trading-debate package."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


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
            self.dedup_key = f"{self.url or ''}|{self.published_at or ''}|{self.title}"


@dataclass
class YahooFetchResult:
    """Yahoo Finance fetch result with both evidence items and summary data."""

    items: list[EvidenceItem]
    fundamentals: dict[str, Any]
    price: dict[str, Any]
    technicals: dict[str, Any]
    stored_news: int
