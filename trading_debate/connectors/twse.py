"""TWSE OpenAPI / MOPS official disclosure connector."""

from __future__ import annotations

import ssl

from ..models import EvidenceItem
from ..symbols import taiwan_code
from ..utils import request_json


def fetch_twse_mops(run_id: str, symbol: str, limit: int = 0) -> list[EvidenceItem]:
    code = taiwan_code(symbol)
    if not code:
        detail = "Official disclosures are only queried for Taiwan ticker codes."
        return [
            EvidenceItem(
                run_id=run_id,
                source="TWSE OpenAPI / MOPS",
                title="Connector skipped",
                payload={"state": "skipped", "detail": detail},
            )
        ]
    _unverified_ctx = ssl._create_unverified_context()
    records = request_json(
        "https://openapi.twse.com.tw/v1/opendata/t187ap04_L",
        ssl_context=_unverified_ctx,
    )
    profile = next(
        (item for item in records if str(item.get("公司代號", "")).strip() == code),
        None,
    )
    if not profile:
        return [
            EvidenceItem(
                run_id=run_id,
                source="TWSE OpenAPI / MOPS",
                title="Connector empty",
                payload={
                    "state": "empty",
                    "detail": f"No listed-company profile found for {code}.",
                },
            )
        ]
    return [
        EvidenceItem(
            run_id=run_id,
            source="TWSE OpenAPI / MOPS",
            title="Official listed-company disclosure profile",
            payload=profile,
            url="https://openapi.twse.com.tw/v1/opendata/t187ap04_L",
        )
    ]
