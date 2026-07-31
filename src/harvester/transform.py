"""Polars-based data transformation.

Converts raw dicts from twse.py into clean Polars DataFrames ready for
Supabase upsert. Handles type coercion, deduplication, and validation.
"""

from __future__ import annotations

import logging

import polars as pl

log = logging.getLogger("transform")


def t86_to_frame(rows: list[dict]) -> pl.DataFrame:
    """Convert T86 institutional flow rows to a typed Polars DataFrame."""
    if not rows:
        return pl.DataFrame(schema={
            "date": pl.Date, "ticker_id": pl.Utf8, "company_name": pl.Utf8,
            "market": pl.Utf8, "foreign_net": pl.Int64, "trust_net": pl.Int64,
            "dealer_net": pl.Int64, "total_net": pl.Int64,
        })
    df = pl.DataFrame(rows)
    df = df.with_columns(pl.col("date").str.to_date("%Y-%m-%d"))
    df = df.unique(subset=["date", "ticker_id"], keep="last")
    return df


def holdings_to_frame(rows: list[dict]) -> pl.DataFrame:
    """Convert MI_QFIIS / TPEX QFII rows to a typed Polars DataFrame."""
    if not rows:
        return pl.DataFrame(schema={
            "date": pl.Date, "ticker_id": pl.Utf8, "company_name": pl.Utf8,
            "market": pl.Utf8, "shares_outstanding": pl.Int64,
            "foreign_held_shares": pl.Int64, "foreign_held_pct": pl.Float64,
            "foreign_room_pct": pl.Float64,
        })
    df = pl.DataFrame(rows)
    df = df.with_columns(pl.col("date").str.to_date("%Y-%m-%d"))
    df = df.unique(subset=["date", "ticker_id"], keep="last")
    return df


def margin_to_frame(rows: list[dict]) -> pl.DataFrame:
    """Convert margin balance rows to a typed Polars DataFrame."""
    if not rows:
        return pl.DataFrame(schema={
            "date": pl.Date, "ticker_id": pl.Utf8, "company_name": pl.Utf8,
            "market": pl.Utf8, "margin_balance": pl.Int64,
            "margin_change": pl.Int64, "margin_limit": pl.Int64,
            "short_balance": pl.Int64, "short_change": pl.Int64,
            "short_limit": pl.Int64,
        })
    df = pl.DataFrame(rows)
    df = df.with_columns(pl.col("date").str.to_date("%Y-%m-%d"))
    df = df.unique(subset=["date", "ticker_id"], keep="last")
    return df


def ohlcv_to_frame(rows: list[dict]) -> pl.DataFrame:
    """Convert OHLCV bar rows to a typed Polars DataFrame."""
    if not rows:
        return pl.DataFrame(schema={
            "date": pl.Date, "ticker_id": pl.Utf8, "market": pl.Utf8,
            "open": pl.Float64, "high": pl.Float64, "low": pl.Float64,
            "close": pl.Float64, "volume_shares": pl.Int64,
            "turnover_twd": pl.Int64,
        })
    df = pl.DataFrame(rows)
    df = df.with_columns(pl.col("date").str.to_date("%Y-%m-%d"))
    df = df.unique(subset=["date", "ticker_id"], keep="last")
    return df


def revenue_to_frame(rows: list[dict]) -> pl.DataFrame:
    """Convert MOPS monthly revenue rows to a typed Polars DataFrame."""
    if not rows:
        return pl.DataFrame(schema={
            "ym": pl.Utf8, "ticker_id": pl.Utf8, "company_name": pl.Utf8,
            "market": pl.Utf8, "industry": pl.Utf8,
            "revenue_k_twd": pl.Int64, "mom_pct": pl.Float64,
            "yoy_pct": pl.Float64, "ytd_revenue": pl.Int64,
            "ytd_prev_year": pl.Int64, "ytd_yoy_pct": pl.Float64,
        })
    df = pl.DataFrame(rows)
    df = df.unique(subset=["ym", "ticker_id"], keep="last")
    return df


def extract_supply_chain_tickers(t86_df: pl.DataFrame) -> pl.DataFrame:
    """Extract unique tickers from T86 data for dim_supply_chain seeding.

    Returns a DataFrame with ticker_id, company_name, market — ready to
    upsert into dim_supply_chain (ai_pillar and node will be NULL initially).
    """
    if t86_df.is_empty():
        return pl.DataFrame(schema={
            "ticker_id": pl.Utf8, "company_name": pl.Utf8, "market": pl.Utf8,
        })
    return (
        t86_df
        .select(["ticker_id", "company_name", "market"])
        .unique(subset=["ticker_id"], keep="last")
        .sort("ticker_id")
    )


def valuation_to_frame(rows: list[dict]) -> pl.DataFrame:
    """Convert BWIBBU_d valuation rows to a typed Polars DataFrame."""
    if not rows:
        return pl.DataFrame(schema={
            "date": pl.Date, "ticker_id": pl.Utf8, "company_name": pl.Utf8,
            "market": pl.Utf8, "close": pl.Float64,
            "dividend_yield": pl.Float64, "dividend_year": pl.Int64,
            "pe_ratio": pl.Float64, "pb_ratio": pl.Float64,
            "fiscal_period": pl.Utf8,
        })
    df = pl.DataFrame(rows)
    df = df.with_columns(pl.col("date").str.to_date("%Y-%m-%d"))
    df = df.unique(subset=["date", "ticker_id"], keep="last")
    return df


def indices_to_frame(rows: list[dict]) -> pl.DataFrame:
    """Convert MI_INDEX rows to a typed Polars DataFrame."""
    if not rows:
        return pl.DataFrame(schema={
            "date": pl.Date, "index_name": pl.Utf8,
            "close": pl.Float64, "change_pts": pl.Float64,
            "change_pct": pl.Float64, "direction": pl.Utf8,
        })
    df = pl.DataFrame(rows)
    df = df.with_columns(pl.col("date").str.to_date("%Y-%m-%d"))
    df = df.unique(subset=["date", "index_name"], keep="last")
    return df
