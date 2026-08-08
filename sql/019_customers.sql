-- alphatecx v2 — Customers (commercial productization, Layer 0)
--
-- Multi-tenant identity for the paid connector. The server was single-tenant:
-- every OAuth login became sub="owner" (see mcp_server/api/oauth.py). This
-- table gives each paying customer a distinct id so tokens can carry
-- sub=<customer_id> and (Layer 1) usage can be metered per customer.
-- See docs/wiki/topics/commercial-productization.md.
--
-- The stateless-OAuth "store nothing in Postgres" stance was justified by the
-- split database; the Zeabur cutover collapsed that to one instance, so a small
-- customers table is now safe. This is the deliberate reversal noted in the wiki.
--
-- Write path: provisioning runs as the DB owner (scripts/provision_customer.py).
-- The read-only mcp_viewer role gets SELECT only — it authenticates customers,
-- it never mutates them. secret_hash is a SHA-256 of a high-entropy token, so
-- exposing it to the read role reveals nothing usable.

CREATE TABLE IF NOT EXISTS customers (
    id            TEXT PRIMARY KEY,                 -- app-generated, non-enumerable (cust_…)
    email         TEXT NOT NULL,
    secret_hash   TEXT NOT NULL UNIQUE,             -- sha256 hex of the connector secret
    plan          TEXT NOT NULL DEFAULT 'private',
    status        TEXT NOT NULL DEFAULT 'active',   -- active | suspended | trial
    monthly_quota INTEGER,                          -- NULL = unlimited (Layer 1 enforces)
    note          TEXT,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Grant + RLS for the read role. Role-guarded so this file is safe to run
-- before 003_rls.sql creates mcp_viewer (first pass is a no-op; the real grant
-- lands on the pass after 003, which apply_schema.py sequences). SELECT alone
-- survives the blanket `REVOKE INSERT, UPDATE, DELETE` at the end of 003, so —
-- unlike 018 — this file needs no INSERT re-grant.
DO $$
BEGIN
  IF EXISTS (SELECT FROM pg_catalog.pg_roles WHERE rolname = 'mcp_viewer') THEN
    EXECUTE 'GRANT SELECT ON customers TO mcp_viewer';
    EXECUTE 'ALTER TABLE customers ENABLE ROW LEVEL SECURITY';
    EXECUTE 'DROP POLICY IF EXISTS "mcp_viewer_read_customers" ON customers';
    EXECUTE $POLICY$
      CREATE POLICY "mcp_viewer_read_customers"
        ON customers FOR SELECT TO mcp_viewer USING (true)
    $POLICY$;
  END IF;
END$$;
