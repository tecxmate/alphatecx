#!/usr/bin/env python3
"""Admin CLI for the paid connector — the manual/private flow.

Runs locally against the DB (owner via root .env DATABASE_URL). Rounds out
provision_customer.py so the wire-money-then-flip-access loop needs no raw SQL:

    python scripts/manage_customer.py list                        # everyone + usage this month
    python scripts/manage_customer.py suspend client@example.com  # non-payment / end of term
    python scripts/manage_customer.py activate client@example.com # money arrived -> back on
    python scripts/manage_customer.py set-risk niko@x.com conservative  # set risk profile

suspend/activate accept an email OR a cust_… id. A suspended customer is cut off
at the next session (within the access-token TTL, refresh included). See
docs/wiki/topics/paid-connector-deploy.md.
"""
import argparse
import sys
from pathlib import Path

from dotenv import load_dotenv

_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(_ROOT / ".env")
sys.path.insert(0, str(_ROOT / "mcp_server" / "api"))

import customers  # noqa: E402
import usage  # noqa: E402


def _resolve(ref: str) -> dict | None:
    """A cust_… ref is an id; anything else is treated as an email."""
    return customers.get(ref) if ref.startswith(customers.ID_PREFIX) \
        else customers.get_by_email(ref)


def _cmd_list() -> int:
    rows = customers.list_all()
    if not rows:
        print("No customers.")
        return 0
    month = usage.current_yyyymm()
    hdr = f"{'id':<20} {'email':<26} {'status':<10} {'risk':<12} {'quota':>7} {'calls/'+month:>11}"
    print(hdr)
    print("-" * len(hdr))
    for r in rows:
        calls = usage.calls_this_month(r["id"], month)
        quota = "∞" if r["monthly_quota"] is None else r["monthly_quota"]
        risk = r.get("risk_profile") or "-"
        print(f"{r['id']:<20} {r['email']:<26} {r['status']:<10} {risk:<12} {str(quota):>7} {calls:>11}")
    return 0


def _set(ref: str, status: str) -> int:
    customer = _resolve(ref)
    if not customer:
        print(f"No customer matches {ref!r}.")
        return 1
    if customers.set_status(customer["id"], status):
        print(f"{customer['email']} ({customer['id']}) → {status}")
        return 0
    print(f"Failed to update {customer['id']} (no row changed or DB error).")
    return 1


def _set_risk(ref: str, profile: str) -> int:
    customer = _resolve(ref)
    if not customer:
        print(f"No customer matches {ref!r}.")
        return 1
    if customers.set_risk_profile(customer["id"], profile):
        print(f"{customer['email']} ({customer['id']}) → risk: {profile}")
        return 0
    print(f"Failed to update {customer['id']}.")
    return 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("list", help="list all customers with this month's usage")
    for name in ("suspend", "activate"):
        p = sub.add_parser(name, help=f"{name} a customer by email or cust_ id")
        p.add_argument("ref")
    pr = sub.add_parser("set-risk", help="set a customer's risk profile")
    pr.add_argument("ref")
    pr.add_argument("profile", choices=sorted(customers.VALID_RISK))
    args = parser.parse_args()

    if args.cmd == "list":
        return _cmd_list()
    if args.cmd == "suspend":
        return _set(args.ref, "suspended")
    if args.cmd == "activate":
        return _set(args.ref, "active")
    if args.cmd == "set-risk":
        return _set_risk(args.ref, args.profile)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
