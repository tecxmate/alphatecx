#!/usr/bin/env python3
"""Provision a customer for the paid connector — Phase 0 hand-provisioning.

Runs as the DB owner (uses DATABASE_URL), NOT the read-only server role. Prints
the connector secret ONCE; it is never stored in plaintext. Hand the secret to
the customer — they paste it as the password in the OAuth authorize screen.

    python scripts/provision_customer.py --email investor@example.com
    python scripts/provision_customer.py --email x@y.com --plan pro --quota 5000

See docs/wiki/topics/commercial-productization.md.
"""
import argparse
import sys
from pathlib import Path

from dotenv import load_dotenv

_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(_ROOT / ".env")
# customers.py lives under mcp_server/api and imports db_v2 as a sibling.
sys.path.insert(0, str(_ROOT / "mcp_server" / "api"))

import customers  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--email", required=True)
    parser.add_argument("--plan", default="private")
    parser.add_argument("--quota", type=int, default=None,
                        help="monthly tool-call quota; omit for unlimited")
    parser.add_argument("--risk", choices=sorted(customers.VALID_RISK), default=None,
                        help="optional risk profile (else the AI asks at onboarding)")
    args = parser.parse_args()

    customer_id, secret = customers.provision(
        args.email, plan=args.plan, monthly_quota=args.quota,
    )
    if args.risk:
        customers.set_risk_profile(customer_id, args.risk)

    print("Customer provisioned ✓")
    print(f"  id     : {customer_id}")
    print(f"  email  : {args.email}")
    print(f"  plan   : {args.plan}")
    print(f"  quota  : {args.quota if args.quota is not None else 'unlimited'}")
    print(f"  risk   : {args.risk or '(unset — AI will ask at onboarding)'}")
    print()
    print("  CONNECTOR SECRET (shown once — copy it now):")
    print(f"    {secret}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
