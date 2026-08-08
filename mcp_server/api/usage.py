"""Per-customer usage metering (productization Layer 1).

Counts metered tool calls per customer per month and answers "how many this
month?" for quota enforcement. The MCP server runs as the read-only mcp_viewer
role but MUST write here — the count is a side effect of a read — so
usage_monthly carries a narrow INSERT+UPDATE grant (sql/020_usage.sql), the same
scoped-write pattern as watchlist.

Both calls are resilient by design:
  - record() never raises into a tool response — a metering blip must not break
    a paying customer's query.
  - calls_this_month() fails OPEN (returns 0) so a read error can't wrongly lock
    a customer out. The quota is a soft ceiling; hard account state (active vs
    suspended) is the auth gate's job, not this counter's.

Months are Asia/Taipei calendar months, matching the data's wall clock (TWSE
publishes on Taipei time; the rest of the server stamps _as_of the same way).
"""
from __future__ import annotations

import logging
from datetime import datetime
from zoneinfo import ZoneInfo

try:
    import db_v2 as db
except ModuleNotFoundError:      # package import path used by local tests
    from . import db_v2 as db

log = logging.getLogger("usage")
_TPE = ZoneInfo("Asia/Taipei")


def current_yyyymm() -> str:
    return datetime.now(_TPE).strftime("%Y-%m")


def record(customer_id: str, yyyymm: str | None = None) -> None:
    """Increment this customer's call count for the month. Best-effort — a
    failure is logged and swallowed so it can never surface in a tool response."""
    if not customer_id:
        return
    month = yyyymm or current_yyyymm()
    try:
        with db.pool().connection() as conn:
            conn.execute(
                "INSERT INTO usage_monthly (customer_id, yyyymm, calls) "
                "VALUES (%s, %s, 1) "
                "ON CONFLICT (customer_id, yyyymm) DO UPDATE "
                "SET calls = usage_monthly.calls + 1, updated_at = now()",
                (customer_id, month),
            )
            conn.commit()
    except Exception:               # noqa: BLE001 — metering must not break a read
        log.exception("usage.record failed for %s", customer_id)


def calls_this_month(customer_id: str, yyyymm: str | None = None) -> int:
    """This customer's metered call count for the month; 0 on any error (fail
    open, so a read blip cannot wrongly deny a customer at the quota gate)."""
    if not customer_id:
        return 0
    month = yyyymm or current_yyyymm()
    try:
        rows = db._fetch(
            "SELECT calls FROM usage_monthly WHERE customer_id = %s AND yyyymm = %s",
            (customer_id, month),
        )
    except Exception:               # noqa: BLE001 — fail open, never lock out on a read error
        log.exception("usage.calls_this_month failed for %s", customer_id)
        return 0
    return int(rows[0]["calls"]) if rows else 0
