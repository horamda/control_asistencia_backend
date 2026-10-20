"""Read-only projection of stored drafts. Never authorizes a clock event."""
import json

from repositories.configuracion_empresa_repository import get_by_empresa_id
from repositories.sucursal_repository import get_by_id as get_branch
from services.facial_policy_service import (
    FacialPolicyError, PolicyScope, resolve_policy, validate_override, DEFAULTS,
)


def decode_draft(record):
    raw = record.get("facial_policy_draft") if record else None
    try:
        return validate_override(json.loads(raw) if isinstance(raw, str) else raw)
    except (ValueError, TypeError) as exc:
        raise FacialPolicyError("Borrador facial invalido; requiere revision administrativa.") from exc


def employee_policy(employee, company=None):
    company_id = employee["empresa_id"]
    config = get_by_empresa_id(company_id) if company is None else company
    branch_id = employee.get("sucursal_id")
    # Before migration, avoid a new branch query in the existing mobile flow.
    migrated = "facial_policy_revision" in (config or {}) or "facial_policy_revision" in employee
    branch = get_branch(branch_id) if branch_id and migrated else None
    if branch and branch.get("empresa_id") != company_id:
        raise FacialPolicyError("Sucursal fuera de la empresa del empleado.")
    if branch_id and migrated and branch is None:
        raise FacialPolicyError("Sucursal del empleado no disponible.")
    subject = PolicyScope(company_id, branch_id, employee["id"])
    result = resolve_policy(
        subject=subject,
        company=(PolicyScope(company_id), decode_draft(config)),
        branch=(PolicyScope(company_id, branch_id), decode_draft(branch)) if branch else None,
        employee=(subject, decode_draft(employee)),
    )
    result["revisions"] = {
        "company": (config or {}).get("facial_policy_revision", 0),
        "branch": (branch or {}).get("facial_policy_revision", 0),
        "employee": employee.get("facial_policy_revision", 0),
    }
    return result


def mobile_policy(employee, company):
    try:
        result = employee_policy(employee, company)
        result["configuration_status"] = "ok"
        return result
    except FacialPolicyError:
        # Invalid drafts must not break legacy QR/GPS while activation is locked.
        return {
            "schema_version": 1, "effective_mode": "disabled",
            "capture_enabled": False, "activation_available": False,
            "activation_block_reason": "provider_and_authorization_not_validated",
            "configuration_status": "invalid",
        }


def form_preview(record, scope):
    if scope == "employee":
        return employee_policy(record)
    company = get_by_empresa_id(record["empresa_id"]) or {}
    inherited = decode_draft(company)
    local = decode_draft(record)
    return {
        "requested": {**DEFAULTS, **inherited, **local},
        "origins": {key: "branch" if key in local else "company" if key in inherited else "default" for key in DEFAULTS},
        "effective_mode": "disabled",
    }
