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


# Explicit kill switch for every outbound Telegram message: alerts, briefs, the
# daily summary, Risk Guard stop warnings and the news poller's watchlist pushes.
# Set TELEGRAM_ENABLED=false (or 0/no/off) to silence them.
#
# This exists as its own flag rather than "just unset the token" because those
# two situations look identical at the send site and are not the same thing at
# all. An unset token in a system that expects to alert is a BREAKAGE — it is
# how every Risk Guard alert sat at pushed:false for weeks (2026-08-10), with
# the notify-on-failure path silently dead because it depended on the same
# token. A deliberate "off" should be legible as deliberate, in the logs and in
# the workflow preflight, so nobody spends another afternoon diagnosing it.
def _flag_on(name: str) -> bool:
    return os.getenv(name, "true").strip().lower() not in ("false", "0", "no", "off")


def telegram_enabled() -> bool:
    return _flag_on("TELEGRAM_ENABLED")


# Category switches under the master flag. "Off" proved too blunt in practice:
# the first time TELEGRAM_ENABLED went false (2026-08-16) the reason was noise,
# and total silence also cost the stop alerts and the morning brief — the
# messages the noise was drowning out. One switch per kind of message means the
# channel can carry signal without carrying everything.
#
# Categories, and who sends under each:
#   briefs — pre-market/intraday/post-close briefs, thesis heartbeat, the
#            daily harvest summary
#   alerts — Risk Guard: stop-line breaches, light changes, settlement checks,
#            and the intraday quote watcher
#   news   — the news poller's watchlist pushes
#   ops    — harvest error alerts (workflow-level 🔴 FAILED curls are gated
#            separately in the YAML, on the master flag only)
#
# All default ON so that setting nothing behaves exactly as before this
# existed: the master flag alone decides.
TELEGRAM_CATEGORIES = ("briefs", "alerts", "news", "ops")


def telegram_category_enabled(category: str) -> bool:
    """Master flag AND the category's own flag (TELEGRAM_BRIEFS etc.).

    Unknown categories are ON rather than off: this gate exists to reduce
    noise, not to fail closed — a typo at a send site must degrade to "message
    delivered" (the pre-switch behaviour), never to another silent channel.
    """
    if not telegram_enabled():
        return False
    if category not in TELEGRAM_CATEGORIES:
        return True
    return _flag_on(f"TELEGRAM_{category.upper()}")


def telegram_configured() -> bool:
    return (
        telegram_enabled()
        and bool(TELEGRAM_TOKEN)
        and bool(TELEGRAM_CHAT_ID)
        and not TELEGRAM_TOKEN.startswith("your_")
    )


def db_configured() -> bool:
    return bool(DATABASE_URL)
