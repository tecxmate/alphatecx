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
from dotenv import load_dotenv
import psycopg

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

sql_files = ["sql/001_schema.sql", "sql/002_views.sql", "sql/004_quant.sql"]
if args.rls:
    pw = os.getenv("MCP_VIEWER_PASSWORD")
    if not pw:
        print("ERROR: --rls requires MCP_VIEWER_PASSWORD in env")
        sys.exit(1)
    sql_files.append("sql/003_rls.sql")

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
