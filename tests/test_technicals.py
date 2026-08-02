"""Tests for technical indicator calculations and OHLCV conversion."""

from __future__ import annotations

import pandas as pd

import trading_debate as td
from trading_debate.connectors.technicals import resample_ohlcv

from .conftest import make_history


def test_compute_technicals_returns_full_indicator_set():
    history = make_history(250)
    indicators = td.compute_technicals(history)
    assert indicators["available"] is True
    assert indicators["bars"] == 250
    assert indicators["ma_50"] is not None
    assert indicators["ma_200"] is not None
    assert indicators["rsi_14"] is not None
    assert 0 <= indicators["rsi_14"] <= 100
    assert indicators["macd"]["line"] is not None
    assert indicators["macd"]["signal"] is not None
    assert indicators["macd"]["histogram"] is not None
    bb = indicators["bollinger_20_2"]
    assert bb["middle"] is not None
    assert bb["upper"] > bb["middle"] > bb["lower"]
    assert indicators["kdj_k"] is not None
    assert indicators["kdj_d"] is not None
    assert indicators["kdj_j"] is not None
    assert indicators["high_52w"] is not None
    assert indicators["low_52w"] is not None
    assert indicators["avg_volume_20d"] is not None
    assert indicators["volume_trend_20d_vs_60d"] is not None
    sr = indicators["support_resistance"]
    assert sr["support"] is not None
    assert sr["resistance"] is not None


def test_compute_technicals_handles_short_history():
    history = make_history(5)
    indicators = td.compute_technicals(history)
    assert indicators["available"] is True
    assert indicators["ma_50"] is None
    assert indicators["ma_200"] is None
    assert indicators["kdj_k"] is None


def test_compute_technicals_handles_empty_history():
    empty = pd.DataFrame()
    indicators = td.compute_technicals(empty)
    assert indicators["available"] is False


def test_compute_technicals_handles_zero_volume_mean():
    history = make_history(70)
    history.loc[:, "Volume"] = 0.0
    indicators = td.compute_technicals(history)
    assert indicators["volume_trend_20d_vs_60d"] is None


def test_history_to_records_round_trips():
    history = make_history(3)
    records = td.history_to_records(history)
    assert len(records) == 3
    for record in records:
        assert "date" in record
        for col in ("open", "high", "low", "close", "volume"):
            assert col in record


def test_resample_ohlcv_returns_weekly_bars():
    history = make_history(10)
    weekly = resample_ohlcv(history, "W-FRI")
    assert not weekly.empty
    assert weekly["Open"].iloc[0] == history["Open"].iloc[0]
    assert weekly["Volume"].sum() == history["Volume"].sum()
