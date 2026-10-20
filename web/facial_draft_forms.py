"""Shared adapter for existing branch/employee forms; no biometric activation."""
import json

from flask import abort, request, session, redirect
from repositories.usuarios_app_repository import get_by_id as get_panel_user
from repositories.configuracion_empresa_repository import save_facial_draft
from services.facial_policy_context import form_preview
from services.facial_policy_service import FacialPolicyError, validate_override


def parse_draft_form(form, current=None):
    """Absent inputs preserve old clients' fields; blank inputs explicitly inherit."""
    values = dict(current or {})
    for field in ("mode", "on_entry", "on_exit", "max_attempts", "timeout_seconds"):
        name = "facial_" + field
        if name not in form:
            continue
        raw = form[name]
        if raw in ("", "inherit"):
            values.pop(field, None)
        elif field in ("on_entry", "on_exit"):
            if raw not in ("true", "false"):
                raise FacialPolicyError("Entrada/salida: seleccione heredar, si o no.")
            values[field] = raw == "true"
        elif field in ("max_attempts", "timeout_seconds"):
            try:
                values[field] = int(raw)
            except (ValueError, TypeError):
                raise FacialPolicyError("Intentos y tiempo deben ser numeros enteros.")
        else:
            values[field] = raw
    return validate_override(values)


def prepare_facial_form(record, *, scope, return_url):
    is_save = request.method == "POST" and request.form.get("action") == "save_facial_draft"
    # Old schemas/forms continue without any extra user query.
    if "facial_policy_revision" not in record and not is_save:
        return None
    user = get_panel_user(session.get("user_id"))
    allowed = bool(user and user.get("activo") and user.get("rol") == "admin"
                   and user.get("empresa_id") in (None, record.get("empresa_id")))
    record["facial_allowed"] = allowed
    record["facial_ready"] = allowed and "facial_policy_revision" in record
    raw = record.get("facial_policy_draft")
    try:
        draft = json.loads(raw) if isinstance(raw, str) else raw
    except (ValueError, TypeError):
        draft = None
    record["facial_draft_mode"] = draft.get("mode", "inherit") if isinstance(draft, dict) else "inherit"
    record["facial_draft_values"] = draft if isinstance(draft, dict) else {}
    if not is_save:
        if allowed:
            try:
                record["facial_preview"] = form_preview(record, scope)
            except FacialPolicyError as exc:
                record["facial_error"] = str(exc)
        return None
    if not allowed:
        abort(403)
    try:
        save_facial_draft(
            record["empresa_id"], parse_draft_form(request.form, record["facial_draft_values"]),
            revision=int(request.form.get("facial_revision", "")),
            actor_id=int(session["user_id"]), scope=scope, record_id=record["id"],
        )
    except (ValueError, RuntimeError) as exc:
        # Return to the existing form without falling into normal entity editing.
        record["facial_error"] = str(exc)
        return False
    return redirect(return_url + "?facial_saved=1")
