"""Dependency-free SQL query safety helpers."""

from __future__ import annotations

# Whitelisted column identifiers that may be interpolated into SQL.
# Anything outside this set gets rejected before reaching the database.
ALLOWED_FLOW_COLS = frozenset({
    "foreign_1d", "foreign_3d", "foreign_5d", "foreign_10d", "foreign_20d",
    "total_1d", "total_3d", "total_5d", "total_10d", "total_20d",
    "consecutive_foreign_buy_days",
})


def safe_flow_col(col: str, default: str) -> str:
    """Return `col` only if it is an allowed flow-column identifier."""
    return col if col in ALLOWED_FLOW_COLS else default
