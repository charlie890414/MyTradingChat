"""GDELT DOC API connector for recent global news discovery."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from ..models import EvidenceItem
from ..utils import NEWS_MAX_AGE_DAYS, is_recent_news, request_json

_URL = "https://api.gdeltproject.org/api/v2/doc/doc"


def _status(run_id: str, state: str, detail: str) -> EvidenceItem:
    return EvidenceItem(
        run_id=run_id,
        source="GDELT",
        title=f"Connector {state}",
        payload={"state": state, "detail": detail},
    )


def _published_at(value: Any) -> str | None:
    """Normalize GDELT's compact timestamp without treating invalid values as news."""
    if not value:
        return None
    text = str(value)
    try:
        return datetime.strptime(text, "%Y%m%dT%H%M%SZ").replace(tzinfo=UTC).isoformat()
    except ValueError:
        try:
            parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError:
            return None
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=UTC)
        return parsed.isoformat()


def fetch_gdelt_news(
    run_id: str, symbol: str, limit: int, *, company_name: str | None = None
) -> list[EvidenceItem]:
    """Return recent article metadata; bodies are fetched by the shared pipeline."""
    if limit <= 0:
        return [_status(run_id, "empty", "GDELT news limit is zero.")]
    term = company_name or f"{symbol} stock"
    try:
        response = request_json(
            _URL,
            {
                "query": f'"{term}"',
                "mode": "artlist",
                "format": "json",
                "maxrecords": min(limit, 250),
                "timespan": f"{NEWS_MAX_AGE_DAYS}d",
                "sort": "datedesc",
            },
        )
    except Exception as exc:
        return [_status(run_id, "error", str(exc))]

    articles = response.get("articles", []) if isinstance(response, dict) else []
    if not isinstance(articles, list):
        return [
            _status(run_id, "error", "GDELT returned an unexpected response format.")
        ]

    items: list[EvidenceItem] = []
    for article in articles:
        if not isinstance(article, dict):
            continue
        published_at = _published_at(article.get("seendate"))
        if not is_recent_news(published_at):
            continue
        title = str(article.get("title") or "Untitled article")
        url = article.get("url")
        items.append(
            EvidenceItem(
                run_id=run_id,
                source="GDELT News",
                title=title,
                payload={
                    "title": title,
                    "url": url,
                    "seendate": article.get("seendate"),
                    "domain": article.get("domain"),
                    "language": article.get("language"),
                    "source_country": article.get("sourcecountry"),
                    "social_image": article.get("socialimage"),
                },
                url=str(url) if url else None,
                published_at=published_at,
            )
        )
        if len(items) >= limit:
            break
    return items or [_status(run_id, "empty", "GDELT returned no recent articles.")]
