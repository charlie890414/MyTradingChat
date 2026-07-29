"""External evidence connectors for the trading-debate package."""

from __future__ import annotations

from typing import Protocol

from ..models import EvidenceItem
from .alpha_vantage import fetch_alpha_vantage
from .finmind import fetch_finmind
from .finnhub import fetch_finnhub
from .reddit import fetch_reddit_summary
from .twse import fetch_twse_mops
from .yahoo import fetch_yahoo


class Connector(Protocol):
    """A source that returns evidence items for a run."""

    def __call__(
        self, run_id: str, symbol: str, news_limit: int
    ) -> list[EvidenceItem]: ...


CONNECTORS: dict[str, Connector] = {
    "Alpha Vantage": fetch_alpha_vantage,
    "Finnhub": fetch_finnhub,
    "FinMind": fetch_finmind,
    "TWSE OpenAPI / MOPS": fetch_twse_mops,
    "Reddit": fetch_reddit_summary,
}

__all__ = [
    "CONNECTORS",
    "Connector",
    "fetch_alpha_vantage",
    "fetch_finnhub",
    "fetch_finmind",
    "fetch_reddit_summary",
    "fetch_twse_mops",
    "fetch_yahoo",
]
