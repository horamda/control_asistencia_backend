"""Policy preparation only. No capture, database access or attendance enforcement.

Activation is deliberately unavailable until a provider and the authorization
flow have been validated. Never use this resolver as biometric evidence.
"""
from dataclasses import dataclass
from typing import Mapping


MODES = frozenset({"disabled", "trial", "required", "risk"})
FIELDS = frozenset({"mode", "on_entry", "on_exit", "max_attempts", "timeout_seconds"})
DEFAULTS = {
    "mode": "disabled",
    "on_entry": True,
    "on_exit": True,
    "max_attempts": 3,
    "timeout_seconds": 30,
}


class FacialPolicyError(ValueError):
    pass


@dataclass(frozen=True)
class PolicyScope:
    """Identity comes from server-side records, never from mobile payloads."""

    company_id: int
    branch_id: int | None = None
    employee_id: int | None = None


def _positive_id(value):
    return type(value) is int and value > 0


def validate_override(values: Mapping | None) -> dict:
    """Missing/null fields inherit; explicit disabled overrides the parent."""
    if values is None:
        return {}
    if not isinstance(values, Mapping):
        raise FacialPolicyError("La politica debe ser un objeto.")
    if set(values) - FIELDS:
        raise FacialPolicyError("La politica contiene campos no permitidos.")
    result = {}
    for key, value in values.items():
        if value is None:
            continue
        if key == "mode":
            if not isinstance(value, str) or value not in MODES:
                raise FacialPolicyError("Modo facial invalido.")
        elif key in {"on_entry", "on_exit"}:
            if type(value) is not bool:
                raise FacialPolicyError("Entrada y salida requieren booleanos.")
        else:
            low, high = (1, 5) if key == "max_attempts" else (10, 120)
            if type(value) is not int or not low <= value <= high:
                raise FacialPolicyError(f"{key} fuera de los limites permitidos.")
        result[key] = value
    return result


def resolve_policy(
    *,
    subject: PolicyScope,
    company: tuple[PolicyScope, Mapping] | None = None,
    branch: tuple[PolicyScope, Mapping] | None = None,
    employee: tuple[PolicyScope, Mapping] | None = None,
) -> dict:
    """Resolve a draft and expose an independently locked effective mode.

    Numeric limits are initial server safety bounds, not biometric thresholds.
    Authorization to edit/view scopes must additionally be checked by callers.
    """
    if not _positive_id(subject.company_id) or not _positive_id(subject.employee_id):
        raise FacialPolicyError("Empresa y empleado requeridos.")
    if subject.branch_id is not None and not _positive_id(subject.branch_id):
        raise FacialPolicyError("Sucursal invalida.")
    resolved = dict(DEFAULTS)
    origins = dict.fromkeys(DEFAULTS, "default")
    expected = {
        "company": PolicyScope(subject.company_id),
        "branch": PolicyScope(subject.company_id, subject.branch_id),
        "employee": subject,
    }
    for level, record in (("company", company), ("branch", branch), ("employee", employee)):
        if record is None:
            continue
        scope, values = record
        if (
            not isinstance(scope, PolicyScope)
            or not _positive_id(scope.company_id)
            or (scope.branch_id is not None and not _positive_id(scope.branch_id))
            or (scope.employee_id is not None and not _positive_id(scope.employee_id))
        ):
            raise FacialPolicyError("Alcance de politica invalido.")
        if level == "branch" and subject.branch_id is None:
            raise FacialPolicyError("El empleado no tiene sucursal.")
        if scope != expected[level]:
            raise FacialPolicyError("La politica no pertenece al alcance solicitado.")
        changes = validate_override(values)
        resolved.update(changes)
        origins.update(dict.fromkeys(changes, level))
    return {
        "schema_version": 1,
        "requested": resolved,
        "origins": origins,
        "effective_mode": "disabled",
        "capture_enabled": False,
        "activation_available": False,
        "activation_block_reason": "provider_and_authorization_not_validated",
    }


def require_activation_available(mode: str) -> None:
    """Reject activation instead of silently pretending a requested mode works."""
    validate_override({"mode": mode})
    if mode != "disabled":
        raise FacialPolicyError(
            "Activacion bloqueada: proveedor y autorizacion facial sin validar."
        )
