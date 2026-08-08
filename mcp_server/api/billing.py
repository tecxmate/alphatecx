"""Merchant-of-Record billing webhook logic (Lemon Squeezy).

Pure, DB-free helpers so the HTTP glue in index.py stays thin and this is fully
unit-testable. Lemon Squeezy is the chosen MoR (Stripe-owned, simple HMAC-SHA256
webhook) — it is the legal seller, handles tax, and pays out to a VN/TW bank,
sidestepping the "Stripe can't be the merchant from VN/TW" block. See
docs/wiki/topics/commercial-productization.md.

Flow: LS posts a signed JSON body to /billing/lemonsqueezy; the signature is an
HMAC-SHA256 of the RAW body under LEMONSQUEEZY_WEBHOOK_SECRET, in the
`X-Signature` header. On a valid subscription event we flip customers.status.

Customer resolution: pass our own `customer_id` as `custom_data` when creating
the LS checkout — it comes back at `meta.custom_data.customer_id`. We fall back
to the subscriber email (`data.attributes.user_email`) so a checkout created
without custom_data can still be matched to a provisioned customer.
"""
from __future__ import annotations

import hashlib
import hmac

# LS subscription statuses that mean "may use the service".
_ACTIVE_LS_STATUSES = frozenset({"active", "on_trial"})


def verify_signature(raw_body: bytes, signature: str, secret: str) -> bool:
    """Whether `signature` is a valid HMAC-SHA256 of the raw body under `secret`.

    Fails closed: an empty secret (unset env) or empty signature is invalid, so
    the webhook refuses everything rather than trusting unsigned input."""
    if not secret or not signature:
        return False
    digest = hmac.new(secret.encode(), raw_body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(digest, signature)


def event_to_status(payload: dict) -> tuple[str | None, str | None, str] | None:
    """Map an LS webhook payload to (customer_id, email, status), or None if the
    payload carries no subscription status we act on (e.g. an order-only event).

    status is our own value: "active" for LS active/on_trial, else "suspended"
    (past_due, unpaid, paused, cancelled, expired all suspend access)."""
    attrs = (payload.get("data") or {}).get("attributes") or {}
    ls_status = attrs.get("status")
    if not ls_status:
        return None
    status = "active" if ls_status in _ACTIVE_LS_STATUSES else "suspended"
    custom = (payload.get("meta") or {}).get("custom_data") or {}
    customer_id = custom.get("customer_id")
    email = attrs.get("user_email")
    return customer_id, email, status
