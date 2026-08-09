#!/usr/bin/env python3
"""Apply ONLY the paid-connector delta migrations to a target database.

apply_schema.py re-runs every file from 001 and rebuilds views — fine for a
fresh DB, but heavy and easy to trip on a populated one. For deploying the
connector to the live Zeabur Postgres we only need the additive, idempotent
connector migrations (all `CREATE ... IF NOT EXISTS` + role-guarded grants):

    ZEABUR_DATABASE_URL='postgres://…public-host…/zeabur' python apply_delta.py
    python apply_delta.py --dsn 'postgres://…' --yes

Prints only the target HOST (never the credentials) so you can confirm you're
hitting the right database. The `mcp_viewer` role must already exist (it does on
Zeabur) — the role-guarded grants in these files land against it.
"""
import argparse
import os
from pathlib import Path

import psycopg
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent / ".env")

# Order matters only in that grants must survive; each file is self-contained and
# idempotent, and none re-runs 003's blanket REVOKE, so this order is safe.
DELTA_FILES = [
    "sql/019_customers.sql",
    "sql/020_usage.sql",
    "sql/021_watchlist_grant.sql",
    "sql/022_customers_status_grant.sql",
    "sql/023_customers_risk_profile.sql",
]


def _host(dsn: str) -> str:
    """Host[:port]/db from a DSN — no credentials."""
    return dsn.split("@")[-1] if "@" in dsn else dsn


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dsn",
        default=os.getenv("ZEABUR_DATABASE_URL") or os.getenv("DATABASE_URL", ""),
        help="target DSN; defaults to $ZEABUR_DATABASE_URL then $DATABASE_URL",
    )
    parser.add_argument("--yes", action="store_true", help="skip the confirmation prompt")
    args = parser.parse_args()

    if not args.dsn:
        print("ERROR: no DSN. Set ZEABUR_DATABASE_URL or pass --dsn.")
        return 1

    host = _host(args.dsn)
    print(f"Target: {host}")
    if "neon.tech" in host:
        print("WARNING: this DSN points at Neon (legacy rollback). The live DB is Zeabur.")
    if not args.yes:
        if input("Apply connector migrations 019–023 here? [y/N] ").strip().lower() != "y":
            print("Aborted.")
            return 0

    with psycopg.connect(args.dsn, autocommit=True) as conn:
        for f in DELTA_FILES:
            p = Path(f)
            if not p.exists():
                print(f"SKIP {f} (missing)")
                continue
            print(f"Applying {f} …", end=" ")
            conn.execute(p.read_text())
            print("✅")

    # Verify the target actually has what the server needs.
    print("\nVerifying:")
    with psycopg.connect(args.dsn, autocommit=True) as conn:
        for tbl in ("customers", "usage_monthly"):
            n = conn.execute(f"SELECT count(*) FROM {tbl}").fetchone()[0]
            print(f"  {tbl}: exists ({n} rows)")
        cols = conn.execute(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name='customers' "
            "AND column_name IN ('status','risk_profile','risk_note','secret_hash')"
        ).fetchall()
        print(f"  customers columns present: {sorted(c[0] for c in cols)}")
    print("\nDelta applied ✓")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
