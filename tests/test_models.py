"""Tests for shared data models."""

from __future__ import annotations

from trading_debate.models import EvidenceItem, YahooFetchResult


def test_evidence_item_generates_dedup_key_from_url_and_title():
    item = EvidenceItem(
        run_id="run-1",
        source="Yahoo Finance",
        title="Headline",
        payload={"x": 1},
        url="https://example.com",
        published_at="2026-01-01",
    )
    assert (
        item.dedup_key == "source:Yahoo Finance|https://example.com|2026-01-01|Headline"
    )


def test_evidence_item_uses_title_when_url_and_date_are_missing():
    item = EvidenceItem(
        run_id="run-1",
        source="Yahoo Finance",
        title="Fundamentals snapshot",
        payload={"x": 1},
    )
    assert item.dedup_key == "source:Yahoo Finance|||Fundamentals snapshot"


def test_evidence_item_respects_explicit_dedup_key():
    item = EvidenceItem(
        run_id="run-1",
        source="Yahoo Finance",
        title="Headline",
        payload={"x": 1},
        dedup_key="custom-key",
    )
    assert item.dedup_key == "custom-key"


def test_yahoo_fetch_result_fields():
    result = YahooFetchResult(
        items=[],
        fundamentals={"price": 100},
        price={"close": 100},
        technicals={"available": True},
        stored_news=5,
    )
    assert result.stored_news == 5
    assert result.fundamentals == {"price": 100}
