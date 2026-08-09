-- alphatecx v2 — Customer risk profile (personalization)
--
-- Persists each user's risk tolerance so the AI tailors framing across every
-- conversation (conservative → capital preservation / dividends / downside;
-- aggressive → growth / momentum / higher risk-reward). Set at onboarding (a
-- user states it → the set_my_risk_profile tool) or at provision time.
--
-- risk_profile is one of 'conservative' | 'balanced' | 'aggressive' (enforced in
-- app code, not a CHECK, so tiers can evolve without a migration); risk_note is
-- optional free text ("dividends only, no small caps").
--
-- The set tool runs inside the read-only server, so mcp_viewer's existing
-- column-scoped UPDATE grant (sql/022) is EXTENDED to these columns. Like
-- 018/020/021/022 the grant is stripped by 003's blanket REVOKE, so
-- apply_schema.py re-appends this after 003. Columns are added first (base pass)
-- so the GRANT UPDATE(col) can reference them. Idempotent + role-guarded.

ALTER TABLE customers ADD COLUMN IF NOT EXISTS risk_profile TEXT;
ALTER TABLE customers ADD COLUMN IF NOT EXISTS risk_note TEXT;

DO $$
BEGIN
  IF EXISTS (SELECT FROM pg_catalog.pg_roles WHERE rolname = 'mcp_viewer')
     AND EXISTS (SELECT FROM information_schema.columns
                 WHERE table_schema = 'public' AND table_name = 'customers'
                   AND column_name = 'risk_profile') THEN
    EXECUTE 'GRANT UPDATE (status, updated_at, risk_profile, risk_note) '
            'ON customers TO mcp_viewer';
  END IF;
END$$;
