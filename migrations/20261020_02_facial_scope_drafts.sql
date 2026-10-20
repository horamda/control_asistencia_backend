-- Preparation only; not applied automatically. Review and back up first.
ALTER TABLE sucursales
    ADD COLUMN facial_policy_draft JSON NULL,
    ADD COLUMN facial_policy_revision INT UNSIGNED NOT NULL DEFAULT 0;
ALTER TABLE empleados
    ADD COLUMN facial_policy_draft JSON NULL,
    ADD COLUMN facial_policy_revision INT UNSIGNED NOT NULL DEFAULT 0;
-- MySQL DDL is not a multi-statement transaction. If interrupted, inspect
-- columns and apply only the missing ALTER. Do not rerun blindly.
-- Operational rollback: revert UI/code, retain drafts and audit records.
