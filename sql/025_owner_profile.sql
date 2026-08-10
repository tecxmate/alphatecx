-- alphatecx v2 — Reserved `owner` customer row (personalization for the operator)
--
-- The risk-profile layer keys on `customers.id`, and the auth gate sets the token
-- subject as that id. Owner sessions had no id to key on: the URL-as-secret path
-- (/mcp/<token>/, what Claude Code and the Desktop bridge use) never set one at
-- all, and the OAuth owner login resolves to the literal subject "owner", which
-- the profile tools special-cased into "can't persist". So the whole onboarding
-- loop the server instructions lean on — call my_profile, ask, save, tailor —
-- was inert for the person who uses the connector most. Observed live 2026-08-10:
-- set_my_risk_profile returned saved:false on every attempt.
--
-- Rather than a second table, "owner" becomes a reserved customer id. get_risk /
-- set_risk_profile then work unchanged, and the column-scoped UPDATE grant from
-- 022/023 already covers the write.
--
-- secret_hash is the literal '-', which is NOT a 64-char sha256 hex string, so
-- customers.authenticate() — which looks the caller up BY that hash — can never
-- match this row no matter what secret is presented. The owner credential stays
-- the shared OAUTH_PASSWORD (checked before any DB lookup) and the URL secret.
-- status is 'suspended' for the same belt-and-braces reason: even if some future
-- code path did resolve to this row, it could not authorise a session with it.
-- Neither field gates the profile read/write, which is all this row is for.
--
-- Idempotent: ON CONFLICT DO NOTHING, so re-running never clobbers a profile the
-- operator has since set.

INSERT INTO customers (id, email, secret_hash, plan, status, note)
VALUES ('owner', 'owner@alphatecx.local', '-', 'owner', 'suspended',
        'Reserved row: carries the operator''s risk profile. Not a login — see sql/025.')
ON CONFLICT (id) DO NOTHING;
