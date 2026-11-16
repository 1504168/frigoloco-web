-- ============================================================================
-- Migration 0019 - client contacts (one per role)
-- ============================================================================
-- Each client has up to three contacts: account management / finance, daily
-- operations and IT. One row per (client, role) instead of twelve columns on
-- clients: a fourth role later is a CHECK change, not four new columns.
--
-- Idempotent: re-running is a no-op.
-- ============================================================================

BEGIN;

CREATE TABLE IF NOT EXISTS client_contacts (
    client_id   INTEGER      NOT NULL REFERENCES clients(id) ON DELETE CASCADE,
    role        TEXT         NOT NULL,
    name        TEXT,
    job_title   TEXT,
    phone       TEXT,
    email       TEXT,
    updated_at  TIMESTAMPTZ  NOT NULL DEFAULT now(),
    PRIMARY KEY (client_id, role),
    CONSTRAINT chk_client_contacts_role
        CHECK (role IN ('account_finance', 'operations', 'it'))
);

COMMIT;
