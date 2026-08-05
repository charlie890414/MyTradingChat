"""External evidence connectors for the trading-debate package."""

from __future__ import annotations

from typing import Protocol

from ..models import EvidenceItem
from .bing_news import fetch_bing_news
from .finmind import fetch_finmind
from .finnhub import fetch_finnhub
from .google_news import fetch_google_news
from .market import fetch_official_valuation_data
from .mops import fetch_mops_documents
from .sec import fetch_sec
from .twse import fetch_twse_mops
from .yahoo import fetch_yahoo


class Connector(Protocol):
    """A source that returns evidence items for a run."""

    def __call__(
        self,
        run_id: str,
        symbol: str,
        news_limit: int,
        *,
        company_name: str | None = None,
    ) -> list[EvidenceItem]: ...


CONNECTORS: dict[str, Connector] = {
    "Google News RSS": fetch_google_news,
    "Bing News RSS": fetch_bing_news,
    "Finnhub": fetch_finnhub,
    "SEC EDGAR": fetch_sec,
    "FinMind": fetch_finmind,
    "TWSE OpenAPI / MOPS": fetch_twse_mops,
    "MOPS Official Documents": fetch_mops_documents,
    "TWSE Official Valuation Data": fetch_official_valuation_data,
}

__all__ = [
    "CONNECTORS",
    "Connector",
    "fetch_bing_news",
    "fetch_finnhub",
    "fetch_finmind",
    "fetch_google_news",
    "fetch_mops_documents",
    "fetch_official_valuation_data",
    "fetch_sec",
    "fetch_twse_mops",
    "fetch_yahoo",
]
