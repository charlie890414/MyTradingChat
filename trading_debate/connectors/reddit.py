"""Reddit public-discussion aggregate connector (RSS-first, anonymous)."""

from __future__ import annotations

import http.client
import logging
import time
import xml.etree.ElementTree as ET
from collections.abc import Iterable
from datetime import datetime
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from ..models import EvidenceItem
from ..symbols import taiwan_code

logger = logging.getLogger(__name__)

DEFAULT_SUBREDDITS = ("wallstreetbets", "stocks", "investing")
_ATOM_NS = {"atom": "http://www.w3.org/2005/Atom"}
_RSS = "https://www.reddit.com/r/{sub}/search.rss?{qs}"
_UA = "MyTradingChat/0.1 (+https://github.com/local/MyTradingChat)"


def _search_qs(symbol: str, limit: int) -> str:
    return urlencode(
        {
            "q": symbol,
            "restrict_sr": "on",
            "sort": "new",
            "t": "week",
            "limit": limit,
        }
    )


def _iso_to_timestamp(raw: str | None) -> float | None:
    if not raw:
        return None
    try:
        normalized = raw[:-1] + "+00:00" if raw.endswith("Z") else raw
        return datetime.fromisoformat(normalized).timestamp()
    except (TypeError, ValueError):
        return None


def _retry_after_seconds(exc: HTTPError) -> float | None:
    try:
        raw = exc.headers.get("Retry-After") if exc.headers else None
        return min(float(raw), 30.0) if raw else None
    except (AttributeError, TypeError, ValueError):
        return None


def _entry_url(entry: ET.Element) -> str | None:
    for link in entry.findall("atom:link", _ATOM_NS):
        href = link.attrib.get("href")
        if href and link.attrib.get("rel") in (None, "alternate"):
            return href
    return None


def _fetch_subreddit_rss(
    symbol: str,
    sub: str,
    limit: int,
    timeout: float = 10.0,
    *,
    retry: bool = True,
) -> list[dict[str, object]]:
    url = _RSS.format(sub=sub, qs=_search_qs(symbol, limit))
    request = Request(url, headers={"User-Agent": _UA})
    try:
        with urlopen(request, timeout=timeout) as response:  # nosec B310: fixed HTTPS provider URL
            root = ET.fromstring(response.read())
    except HTTPError as exc:
        if exc.code == 429 and retry:
            wait = _retry_after_seconds(exc) or 5.0
            logger.warning(
                "Reddit RSS 429 for r/%s · %s; retrying once after %.1fs",
                sub,
                symbol,
                wait,
            )
            time.sleep(wait)
            return _fetch_subreddit_rss(symbol, sub, limit, timeout, retry=False)
        logger.warning("Reddit RSS fetch failed for r/%s · %s: %s", sub, symbol, exc)
        return []
    except (OSError, http.client.HTTPException, ET.ParseError) as exc:
        logger.warning("Reddit RSS fetch failed for r/%s · %s: %s", sub, symbol, exc)
        return []

    posts: list[dict[str, object]] = []
    for entry in root.findall("atom:entry", _ATOM_NS)[:limit]:
        title_el = entry.find("atom:title", _ATOM_NS)
        published_el = entry.find("atom:published", _ATOM_NS)
        published = published_el.text if published_el is not None else None
        posts.append(
            {
                "subreddit": sub,
                "title": (title_el.text if title_el is not None else "") or "",
                "url": _entry_url(entry),
                "created_utc": _iso_to_timestamp(published),
                "published": published,
                "source": "rss",
            }
        )
    return posts


def _fetch_all_subreddits(
    symbol: str,
    subreddits: Iterable[str] = DEFAULT_SUBREDDITS,
    limit_per_sub: int = 5,
    timeout: float = 10.0,
    inter_request_delay: float = 1.0,
) -> list[dict[str, object]]:
    posts: list[dict[str, object]] = []
    for index, sub in enumerate(subreddits):
        if index > 0:
            time.sleep(inter_request_delay)
        posts.extend(_fetch_subreddit_rss(symbol, sub, limit_per_sub, timeout))
    return posts


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

    limit_per_sub = max(1, min(limit, 5))
    posts = _fetch_all_subreddits(symbol, limit_per_sub=limit_per_sub)[:limit]
    aggregate = {
        "query": symbol,
        "post_count": len(posts),
        "score_total": None,
        "comment_total": None,
        "sample_urls": [post["url"] for post in posts if post.get("url")],
        "sample_titles": [post["title"] for post in posts if post.get("title")],
        "subreddits": list(DEFAULT_SUBREDDITS),
        "source": "rss",
        "detail": "Reddit RSS does not provide score or comment counts.",
    }
    return [
        EvidenceItem(
            run_id=run_id,
            source="Reddit search aggregate",
            title="Reddit RSS search aggregate (no post bodies retained)",
            payload=aggregate,
        )
    ]
