"""Reddit public-discussion aggregate connector (anonymous)."""

from __future__ import annotations

from ..models import EvidenceItem
from ..symbols import taiwan_code
from ..utils import request_json


def fetch_reddit_summary(run_id: str, symbol: str, limit: int) -> list[EvidenceItem]:
    if taiwan_code(symbol):
        return [
            EvidenceItem(
                run_id=run_id,
                source="Reddit",
                title="Connector skipped",
                payload={
                    "state": "skipped",
                    "detail": "Reddit search only supports US tickers.",
                },
            )
        ]
    listing = request_json(
        "https://www.reddit.com/search.json",
        {"q": symbol, "sort": "new", "limit": limit, "type": "link"},
        headers={"User-Agent": "MyTradingChat/0.1 (anonymous)"},
    )
    posts = listing.get("data", {}).get("children", [])
    aggregate = {
        "query": symbol,
        "post_count": len(posts),
        "score_total": sum(item.get("data", {}).get("score", 0) for item in posts),
        "comment_total": sum(
            item.get("data", {}).get("num_comments", 0) for item in posts
        ),
        "sample_urls": [
            "https://reddit.com" + item.get("data", {}).get("permalink", "")
            for item in posts
        ],
    }
    return [
        EvidenceItem(
            run_id=run_id,
            source="Reddit search aggregate",
            title="Reddit search aggregate (no post bodies retained)",
            payload=aggregate,
        )
    ]
