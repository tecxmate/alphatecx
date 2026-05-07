"""Pure-function indicator library — Polars Series in, Series out.

Each function is deterministic and side-effect-free. Callers (signals.py
and backtest.py) feed in raw OHLCV columns and get back computed values
aligned to the same index.

Indicator naming follows the canonical literature:
- RSI: Wilder's 14, alpha = 1/period
- MACD: 12/26/9 EMAs, no zero-lag variant
- Bollinger %B: 20-period mean ± 2σ, expressed as (close-lower)/(upper-lower)
- ATR: Wilder smoothing of True Range, period 14
- Relative strength: ticker return / benchmark return over `period` days
"""
from __future__ import annotations

import polars as pl


def sma(close: pl.Series, period: int) -> pl.Series:
    """Simple moving average. Returns NaN until `period` bars accumulate."""
    return close.rolling_mean(window_size=period)


def rsi(close: pl.Series, period: int = 14) -> pl.Series:
    """Wilder's RSI. Uses EMA with alpha=1/period for smoothing.

    Result is in [0, 100]. Convention: < 30 oversold, > 70 overbought.
    """
    delta = close.diff()
    gain = delta.clip(lower_bound=0).fill_null(0.0)
    loss = (-delta).clip(lower_bound=0).fill_null(0.0)

    alpha = 1.0 / period
    avg_gain = gain.ewm_mean(alpha=alpha, adjust=False)
    avg_loss = loss.ewm_mean(alpha=alpha, adjust=False)

    # Avoid division by zero when there's been no loss in the window.
    rs = avg_gain / avg_loss.replace(0.0, float("nan"))
    return 100.0 - (100.0 / (1.0 + rs))


def macd(
    close: pl.Series,
    fast: int = 12,
    slow: int = 26,
    signal: int = 9,
) -> tuple[pl.Series, pl.Series, pl.Series]:
    """MACD = EMA(fast) - EMA(slow); signal = EMA(MACD, signal); hist = MACD - signal.

    Returns (macd_line, signal_line, histogram).
    """
    ema_fast = close.ewm_mean(span=fast, adjust=False)
    ema_slow = close.ewm_mean(span=slow, adjust=False)
    macd_line = ema_fast - ema_slow
    signal_line = macd_line.ewm_mean(span=signal, adjust=False)
    histogram = macd_line - signal_line
    return macd_line, signal_line, histogram


def bollinger_pct_b(
    close: pl.Series,
    period: int = 20,
    std_mult: float = 2.0,
) -> pl.Series:
    """Bollinger Bands %B: (close - lower) / (upper - lower).

    < 0 means below lower band; > 1 means above upper band; 0.5 is the mean.
    """
    mid = close.rolling_mean(window_size=period)
    sd = close.rolling_std(window_size=period)
    upper = mid + std_mult * sd
    lower = mid - std_mult * sd
    band_width = upper - lower
    # Replace zero band_width (degenerate flat-line case) with NaN to avoid div-by-zero.
    return (close - lower) / band_width.replace(0.0, float("nan"))


def atr(
    high: pl.Series,
    low: pl.Series,
    close: pl.Series,
    period: int = 14,
) -> pl.Series:
    """Average True Range — Wilder smoothing of True Range over `period`.

    True Range = max(high-low, |high - prev_close|, |low - prev_close|)
    """
    prev_close = close.shift(1)
    df = pl.DataFrame({
        "tr1": high - low,
        "tr2": (high - prev_close).abs(),
        "tr3": (low - prev_close).abs(),
    })
    true_range = df.select(
        pl.max_horizontal("tr1", "tr2", "tr3").alias("tr")
    )["tr"]
    return true_range.ewm_mean(alpha=1.0 / period, adjust=False)


def relative_strength(
    ticker_close: pl.Series,
    benchmark_close: pl.Series,
    period: int = 60,
) -> pl.Series:
    """RS = ticker_return(period) / benchmark_return(period). >1 = outperforming.

    Both inputs must be aligned by date (caller's job).
    """
    ticker_ret = ticker_close / ticker_close.shift(period)
    bench_ret = benchmark_close / benchmark_close.shift(period)
    return ticker_ret / bench_ret.replace(0.0, float("nan"))


def pct_below_52w_high(close: pl.Series, period: int = 252) -> pl.Series:
    """Distance from rolling-period high, as a percentage.

    Returns 0.0 at the high, -10.0 means 10% below the high. Negative
    values are normal — the metric tracks how deep into a drawdown the
    name is. Period defaults to 252 (≈ 1 trading year).
    """
    rolling_high = close.rolling_max(window_size=period)
    return (close / rolling_high - 1.0) * 100.0


def zscore(series: pl.Series, period: int = 20) -> pl.Series:
    """Rolling z-score: (value - rolling_mean) / rolling_std.

    Magnitude > 2 means a meaningful deviation from recent baseline.
    Useful for "is today's foreign net flow unusual?" — feed it the
    foreign_net column directly.
    """
    mean = series.rolling_mean(window_size=period)
    std = series.rolling_std(window_size=period)
    return (series - mean) / std.replace(0.0, float("nan"))


def rolling_sum(series: pl.Series, period: int) -> pl.Series:
    """Plain rolling sum — used to materialize N-day flow accumulation."""
    return series.rolling_sum(window_size=period)
