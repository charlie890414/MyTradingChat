"""Bing News RSS connector."""

from __future__ import annotations

from datetime import UTC
from email.utils import parsedate_to_datetime
from urllib.parse import quote

import feedparser

from ..models import EvidenceItem

_QUERY = "+stock"
_URL = "https://www.bing.com/news/search?q={q}&format=rss"


def _parse_rss_date(raw: str | None) -> str | None:
    if not raw:
        return None
    parsed = parsedate_to_datetime(raw)
    if parsed.tzinfo is not None:
        return parsed.isoformat()
    return parsed.replace(tzinfo=UTC).isoformat()


def fetch_bing_news(run_id: str, symbol: str, limit: int) -> list[EvidenceItem]:
    query = quote(f"{symbol}{_QUERY}")
    feed = feedparser.parse(
        _URL.format(q=query), agent="MyTradingChat/0.1", request_headers={}
    )
    items: list[EvidenceItem] = []
    for entry in feed.entries[:limit]:
        published_at = entry.get("published") or entry.get("updated", "")
        items.append(
            EvidenceItem(
                run_id=run_id,
                source="Bing News RSS",
                title=entry.get("title", "Untitled"),
                payload={
                    "title": entry.get("title", ""),
                    "link": entry.get("link", ""),
                    "published": published_at,
                    "summary": entry.get("summary", ""),
                },
                url=entry.get("link"),
                published_at=_parse_rss_date(published_at),
            )
        )
    return items
