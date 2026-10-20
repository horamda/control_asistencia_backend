-- Reviewed preparation only; NOT automatically applied at application startup.
-- Snapshot/backup and inspect existing columns before running once.
ALTER TABLE configuracion_empresa
    ADD COLUMN facial_policy_draft JSON NULL,
    ADD COLUMN facial_policy_revision INT UNSIGNED NOT NULL DEFAULT 0;
-- Operational rollback: disable the draft UI / revert application code.
-- Keep these additive columns to preserve drafts and audit history.
-- Do not DROP columns as part of routine rollback.
