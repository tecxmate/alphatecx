"""Multi-tenant customer identity for the paid connector (productization Layer 0).

The MCP server was single-tenant: every OAuth login became sub="owner"
(see oauth.py). This module gives each paying customer a distinct identity so
tokens can carry sub=<customer_id> and, later, usage can be metered per
customer. See docs/wiki/topics/commercial-productization.md.

Responsibility split mirrors the read-only security model:
  - authenticate()/get() only SELECT, so they are safe for the mcp_viewer role
    the server connects as.
  - provision() INSERTs and must run as the DB owner (the harvester's
    DATABASE_URL), never from the read-only server — use
    scripts/provision_customer.py.

Secrets are high-entropy random tokens, so a fast SHA-256 hash is sufficient:
there is no low-entropy password to brute-force. The plaintext secret is shown
once at provision time and never stored.
"""
from __future__ import annotations

import hashlib
import hmac
import logging
import os
import secrets

try:
    import db_v2 as db
except ModuleNotFoundError:      # package import path used by local tests
    from . import db_v2 as db

log = logging.getLogger("customers")

STATUS_ACTIVE = "active"
SECRET_PREFIX = "atx_"          # recognisable in logs/support without revealing the secret
ID_PREFIX = "cust_"


# ── Pure helpers (no DB) ─────────────────────────────────────────────────────

def new_secret() -> str:
    """A fresh connector secret. High-entropy, URL-safe, shown to the customer once."""
    return SECRET_PREFIX + secrets.token_urlsafe(32)


def new_id() -> str:
    """A non-enumerable customer id. Used as the token `sub`, so it must not leak
    a customer count the way a serial would."""
    return ID_PREFIX + secrets.token_urlsafe(9)


def hash_secret(secret: str) -> str:
    """SHA-256 hex of a connector secret. The only form stored."""
    return hashlib.sha256(secret.encode()).hexdigest()


def secret_matches(secret: str, stored_hash: str) -> bool:
    """Constant-time comparison of a presented secret against a stored hash."""
    return hmac.compare_digest(hash_secret(secret), stored_hash or "")


# ── DB access ────────────────────────────────────────────────────────────────

def _row_by_hash(secret_hash: str) -> dict | None:
    """SELECT a customer by secret hash. Read-only; runs as mcp_viewer."""
    rows = db._fetch(
        "SELECT id, email, plan, status, monthly_quota "
        "FROM customers WHERE secret_hash = %s LIMIT 1",
        (secret_hash,),
    )
    return rows[0] if rows else None


def _row_by_id(customer_id: str) -> dict | None:
    rows = db._fetch(
        "SELECT id, email, plan, status, monthly_quota "
        "FROM customers WHERE id = %s LIMIT 1",
        (customer_id,),
    )
    return rows[0] if rows else None


def authenticate(secret: str) -> dict | None:
    """Return the active customer for a connector secret, or None.

    Fails closed: an unreachable DB (or any error) yields None rather than a 500
    on the auth path, so a database blip can never mint a token. The owner login
    is checked before this in the authorize handler and needs no DB, so owner
    access survives a customers-table outage.

    A non-active (suspended/trial-expired) customer is refused a fresh login
    here. Revocation of an *already-issued* token still lags by up to the token
    TTL — that gap closes in Layer 1, where the session gate re-checks status.
    """
    if not secret:
        return None
    try:
        row = _row_by_hash(hash_secret(secret))
    except Exception:               # noqa: BLE001 — auth path must not 500
        log.exception("customer authenticate lookup failed")
        return None
    if row is None or row.get("status") != STATUS_ACTIVE:
        return None
    return row


def get(customer_id: str) -> dict | None:
    """Fetch a customer by id (no status filter). Read-only."""
    if not customer_id:
        return None
    try:
        return _row_by_id(customer_id)
    except Exception:               # noqa: BLE001
        log.exception("customer get failed")
        return None


# ── Provisioning (owner-only write path) ─────────────────────────────────────

def provision(
    email: str,
    plan: str = "private",
    monthly_quota: int | None = None,
    *,
    conn_url: str | None = None,
) -> tuple[str, str]:
    """Create a customer and return (customer_id, plaintext_secret).

    Writes, so it must run as the DB owner: pass conn_url or set DATABASE_URL.
    The returned secret is the ONLY time it exists in plaintext — hand it to the
    customer, store nothing. Import psycopg lazily so importing this module on
    the read-only server never pulls a writable connection into scope.
    """
    import psycopg

    url = conn_url or os.getenv("DATABASE_URL", "")
    if not url:
        raise RuntimeError("provision needs a writable DATABASE_URL (owner role).")

    secret = new_secret()
    customer_id = new_id()
    with psycopg.connect(url, autocommit=True) as conn:
        conn.execute(
            "INSERT INTO customers (id, email, secret_hash, plan, monthly_quota) "
            "VALUES (%s, %s, %s, %s, %s)",
            (customer_id, email, hash_secret(secret), plan, monthly_quota),
        )
    return customer_id, secret
