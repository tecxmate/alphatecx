#!/usr/bin/env python3
"""Apply SQL schema to Neon Postgres.

Usage:
    python apply_schema.py            # schema + views
    python apply_schema.py --rls      # also apply 003_rls.sql

Each SQL file is executed as a single batch against autocommit; if you need
the file to be one transaction, use `BEGIN; ... COMMIT;` inside the file
itself. The previous version had an ad-hoc `;`/`$$` splitter that misparsed
strings containing semicolons — relying on the driver instead is safer.
"""
import argparse
import os
import sys
from pathlib import Path

import psycopg
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent / ".env")
DATABASE_URL = os.getenv("DATABASE_URL", "")

if not DATABASE_URL:
    print("ERROR: DATABASE_URL not set")
    sys.exit(1)

parser = argparse.ArgumentParser()
parser.add_argument(
    "--rls",
    action="store_true",
    help="Also apply sql/003_rls.sql. Requires MCP_VIEWER_PASSWORD env var; "
         "the role's password is set via the mcp_viewer.password GUC.",
)
args = parser.parse_args()

sql_files = [
    "sql/001_schema.sql",
    "sql/002_views.sql",
    "sql/004_quant.sql",
    "sql/005_news.sql",
    "sql/006_digests.sql",
    "sql/007_watchlist.sql",
    "sql/008_universe.sql",
    "sql/009_sc_revamp.sql",
    "sql/010_leadlag.sql",
    "sql/011_valuation_indexes.sql",
    "sql/012_gemini_additions.sql",
    "sql/013_more_classifications.sql",
    "sql/015_market_calendar.sql",
    "sql/016_dividends.sql",
    "sql/017_finmind.sql",
    "sql/018_riskguard.sql",
    "sql/019_customers.sql",
    "sql/020_usage.sql",
    "sql/022_customers_status_grant.sql",
]
if args.rls:
    pw = os.getenv("MCP_VIEWER_PASSWORD")
    if not pw:
        print("ERROR: --rls requires MCP_VIEWER_PASSWORD in env")
        sys.exit(1)
    sql_files.append("sql/003_rls.sql")
    # 014 GRANTs to mcp_viewer, so it can only run once 003 has created the role.
    # Keeping it out of the default list is deliberate, not an omission.
    sql_files.append("sql/014_dim_ticker_classify.sql")
    # 018 again, LAST. 003 ends with a blanket
    # `REVOKE INSERT, UPDATE, DELETE ON ALL TABLES ... FROM mcp_viewer`, which
    # strips the INSERT 018 grants on rg_journal — so the earlier pass is undone
    # the moment 003 runs. 018's own comment says "run this file after any --rls
    # run"; appending it here is what makes that possible, since this script
    # owns the order. Without it `rg_journal_add` fails live with
    # `permission denied for table rg_journal` (observed 2026-07-31), and
    # nothing in the apply output hints at why.
    #
    # Safe twice: every statement in 018 is CREATE TABLE IF NOT EXISTS or a
    # role-guarded DO $$ GRANT.
    sql_files.append("sql/018_riskguard.sql")
    # 019 grants mcp_viewer SELECT on customers behind a role guard, so on the
    # base pass (before 003 creates the role) the grant is skipped. Re-run it
    # here, after 003, so the grant actually lands. SELECT survives 003's
    # blanket REVOKE, so — unlike 018 — no INSERT re-grant is needed.
    sql_files.append("sql/019_customers.sql")
    # 020 grants mcp_viewer INSERT+UPDATE on usage_monthly (metering writes from
    # the read role). That write grant IS stripped by 003's blanket REVOKE, so
    # like 018 it must run last. Re-append here.
    sql_files.append("sql/020_usage.sql")
    # 021 re-grants mcp_viewer INSERT+UPDATE on watchlist. 003 grants it (line
    # 119) then strips it with the same blanket REVOKE (line 154) — with no
    # re-append, w_add/w_remove fail `permission denied` after any --rls run.
    # Grant-only (RLS policies from 003 survive the REVOKE), role/table-guarded.
    sql_files.append("sql/021_watchlist_grant.sql")
    # 022 grants mcp_viewer a column-scoped UPDATE(status) on customers for the
    # billing webhook. Same REVOKE trap → re-append after 003.
    sql_files.append("sql/022_customers_status_grant.sql")

print(f"Connecting to: {DATABASE_URL[:50]}...")

with psycopg.connect(DATABASE_URL, autocommit=True) as conn:
    print("Connected ✓\n")
    if args.rls:
        # Pass the viewer password into the session so 003_rls.sql can read it
        # via current_setting('mcp_viewer.password', true).
        conn.execute("SELECT set_config('mcp_viewer.password', %s, false)",
                     (os.environ["MCP_VIEWER_PASSWORD"],))
    for sql_file in sql_files:
        p = Path(sql_file)
        if not p.exists():
            print(f"SKIP: {sql_file} not found")
            continue
        sql = p.read_text()
        print(f"Applying {sql_file} ({len(sql)} bytes)...", end=" ")
        conn.execute(sql)
        print("✅")

print("\nSchema applied. ✓")
