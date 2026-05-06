#!/usr/bin/env python3
"""Apply SQL schema to Neon Postgres.

Usage: python apply_schema.py
"""
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

SQL_FILES = [
    "sql/001_schema.sql",
    "sql/002_views.sql",
    # Skip 003_rls.sql for now — RLS config can be added later
]

print(f"Connecting to: {DATABASE_URL[:50]}...")

with psycopg.connect(DATABASE_URL, autocommit=True) as conn:
    print("Connected ✓\n")
    for sql_file in SQL_FILES:
        p = Path(sql_file)
        if not p.exists():
            print(f"SKIP: {sql_file} not found")
            continue
        sql = p.read_text()
        print(f"Applying {sql_file} ({len(sql)} bytes)...", end=" ")
        try:
            conn.execute(sql)
            print("✅")
        except Exception as e:
            print(f"❌ {e}")
            # Try statement by statement
            print("  Retrying statement-by-statement...")
            ok = err = 0
            # Simple split on semicolons, handling $$ blocks
            stmts = []
            current = []
            in_dollar = False
            for line in sql.split("\n"):
                if "$$" in line:
                    in_dollar = not in_dollar
                current.append(line)
                if not in_dollar and line.rstrip().endswith(";"):
                    s = "\n".join(current).strip()
                    code = [l for l in s.split("\n") if l.strip() and not l.strip().startswith("--")]
                    if code:
                        stmts.append(s)
                    current = []

            for i, stmt in enumerate(stmts):
                try:
                    conn.execute(stmt)
                    ok += 1
                except Exception as e2:
                    print(f"    [{i+1}] ❌ {str(e2)[:100]}")
                    err += 1
            print(f"  {ok} ok, {err} errors")

print("\nSchema applied. ✓")
