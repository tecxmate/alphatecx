"""Centralized config loaded from .env (or process env)."""

import os
from pathlib import Path
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")

# Neon Postgres (same pattern as v1)
DATABASE_URL = os.getenv("DATABASE_URL", "")

# Telegram (reuse from v1)
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

# TWSE rate limiting
TWSE_REQUEST_DELAY = float(os.getenv("TWSE_REQUEST_DELAY", "3.0"))
TWSE_BACKFILL_DAYS = int(os.getenv("TWSE_BACKFILL_DAYS", "90"))

# HTTP
HTTP_TIMEOUT = int(os.getenv("HTTP_TIMEOUT", "20"))
USER_AGENT = "Mozilla/5.0 alphatecx/0.2"

# FinMind open financial data API (free tier = 600 req/hr). Empty ⇒ FinMind
# enrichment (dividend split / 填息 / news) is simply skipped by the harvester.
FINMIND_TOKEN = os.getenv("FINMIND_TOKEN", "")
FINMIND_REQUEST_DELAY = float(os.getenv("FINMIND_REQUEST_DELAY", "0.35"))


def telegram_configured() -> bool:
    return (
        bool(TELEGRAM_TOKEN)
        and bool(TELEGRAM_CHAT_ID)
        and not TELEGRAM_TOKEN.startswith("your_")
    )


def db_configured() -> bool:
    return bool(DATABASE_URL)
