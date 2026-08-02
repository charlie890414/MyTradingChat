"""Technical indicators and OHLCV record conversion."""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd


def _series(series: pd.Series | None) -> pd.Series:
    if series is None:
        return pd.Series(dtype=float)
    return pd.to_numeric(series, errors="coerce").dropna()


def _ema(series: pd.Series, span: int) -> pd.Series:
    return series.ewm(span=span, adjust=False).mean()


def _rsi(closes: pd.Series, period: int = 14) -> float | None:
    if len(closes) <= period:
        return None
    delta = closes.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1 / period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / period, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    rsi = 100 - 100 / (1 + rs)
    return float(rsi.iloc[-1])


def _support_resistance(
    closes: pd.Series, highs: pd.Series, lows: pd.Series, window: int = 20
) -> dict[str, Any]:
    if len(closes) < window * 2:
        return {"support": None, "resistance": None}
    recent_highs = highs.tail(window).max()
    recent_lows = lows.tail(window).min()
    pivots = closes.rolling(window).mean().dropna()
    if pivots.empty:
        return {"support": None, "resistance": None}
    return {
        "support": float(recent_lows),
        "resistance": float(recent_highs),
        "pivot_avg": float(pivots.iloc[-1]),
    }


def compute_technicals(history: pd.DataFrame) -> dict[str, Any]:
    """Derive common technical indicators from a daily OHLCV frame.

    The frame is the raw output of ``yfinance.Ticker.history(...)`` and must
    contain ``Open``, ``High``, ``Low``, ``Close`` and ``Volume`` columns.
    """
    if history is None or history.empty:
        return {"available": False, "reason": "no daily OHLCV returned"}

    closes = _series(history.get("Close"))
    highs = _series(history.get("High"))
    lows = _series(history.get("Low"))
    volumes = _series(history.get("Volume"))

    if closes.empty:
        return {"available": False, "reason": "Close column empty"}

    ema12 = _ema(closes, 12)
    ema26 = _ema(closes, 26)
    macd_line = ema12 - ema26
    macd_signal = _ema(macd_line, 9)
    macd_hist = macd_line - macd_signal

    sma20 = closes.rolling(20).mean()
    std20 = closes.rolling(20).std()

    indicators: dict[str, Any] = {
        "available": True,
        "bars": int(len(closes)),
        "as_of": str(closes.index[-1].date()),
        "close": float(closes.iloc[-1]),
        "ma_50": float(closes.tail(50).mean()) if len(closes) >= 50 else None,
        "ma_200": float(closes.tail(200).mean()) if len(closes) >= 200 else None,
        "ema_20": float(closes.ewm(span=20, adjust=False).mean().iloc[-1]),
        "rsi_14": _rsi(closes, 14),
        "macd": {
            "line": float(macd_line.iloc[-1]) if len(macd_line) else None,
            "signal": float(macd_signal.iloc[-1]) if len(macd_signal) else None,
            "histogram": float(macd_hist.iloc[-1]) if len(macd_hist) else None,
        },
        "bollinger_20_2": {
            "middle": float(sma20.iloc[-1]) if len(sma20) else None,
            "upper": float((sma20 + 2 * std20).iloc[-1]) if len(sma20) else None,
            "lower": float((sma20 - 2 * std20).iloc[-1]) if len(sma20) else None,
        },
        "high_52w": float(highs.tail(252).max()) if len(highs) else None,
        "low_52w": float(lows.tail(252).min()) if len(lows) else None,
        "avg_volume_20d": (
            float(volumes.tail(20).mean()) if len(volumes) >= 20 else None
        ),
        "volume_trend_20d_vs_60d": (
            float(volumes.tail(20).mean() / volumes.tail(60).mean())
            if len(volumes) >= 60 and volumes.tail(60).mean() > 0
            else None
        ),
        "kdj_k": None,
        "kdj_d": None,
        "kdj_j": None,
        "volume_price_structure": {
            "up_days_20d": int(((closes.diff().tail(20)) > 0).sum()),
            "down_days_20d": int(((closes.diff().tail(20)) < 0).sum()),
            "avg_range_pct_20d": (
                float(((highs - lows) / closes).tail(20).mean())
                if len(closes) >= 20 and (highs > 0).all()
                else None
            ),
        },
    }

    if len(highs) >= 9 and len(lows) >= 9:
        low_n = lows.rolling(9).min()
        high_n = highs.rolling(9).max()
        rsv = ((closes - low_n) / (high_n - low_n).replace(0, np.nan)) * 100
        k = rsv.ewm(alpha=1 / 3, adjust=False).mean()
        d = k.ewm(alpha=1 / 3, adjust=False).mean()
        j = 3 * k - 2 * d
        indicators["kdj_k"] = float(k.iloc[-1])
        indicators["kdj_d"] = float(d.iloc[-1])
        indicators["kdj_j"] = float(j.iloc[-1])

    support_resistance = _support_resistance(closes, highs, lows)
    indicators["support_resistance"] = support_resistance
    return indicators


def history_to_records(history: pd.DataFrame) -> list[dict[str, Any]]:
    """Convert the OHLCV frame into a JSON-friendly list of daily bars."""
    if history is None or history.empty:
        return []
    frame = history.reset_index()
    date_col = frame.columns[0]
    records = []
    for record in frame.to_dict("records"):
        row: dict[str, Any] = {"date": str(record[date_col].date())}
        for col in ("Open", "High", "Low", "Close", "Volume"):
            if col in record:
                value = record[col]
                row[col.lower()] = None if pd.isna(value) else float(value)
        records.append(row)
    return records


def resample_ohlcv(history: pd.DataFrame, frequency: str) -> pd.DataFrame:
    """Resample daily OHLCV bars into weekly or monthly bars.

    The input is expected to use adjusted prices when corporate-action-adjusted
    analysis is requested.  Volume is summed while prices retain standard OHLC
    semantics.
    """
    if history is None or history.empty:
        return pd.DataFrame()

    columns = [
        column
        for column in ("Open", "High", "Low", "Close", "Volume")
        if column in history
    ]
    if not columns:
        return pd.DataFrame()
    aggregations = {
        "Open": "first",
        "High": "max",
        "Low": "min",
        "Close": "last",
        "Volume": "sum",
    }
    return (
        history[columns]
        .resample(frequency)
        .agg({column: aggregations[column] for column in columns})
        .dropna(subset=["Close"] if "Close" in columns else None)
    )
