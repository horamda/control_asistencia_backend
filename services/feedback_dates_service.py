"""Correcciones administrativas sin eventos ni notificaciones de feedback."""
import datetime as dt
import hashlib
import json

from extensions import get_db
from services.feedback_service import _feedback_due_datetime


FIELDS = ("created_at", "resuelto_at", "fecha_limite", "fecha_vencimiento", "resuelto_en_sla")


def date_version(row):
    values = [str(row.get(key)) for key in (*FIELDS, "estado", "updated_at")]
    return hashlib.sha256(json.dumps(values).encode()).hexdigest()


def parse_date(value):
    try:
        value = dt.datetime.fromisoformat(value or "")
        if value.tzinfo is not None:
            raise ValueError()
        return value
    except (TypeError, ValueError):
        raise ValueError("Ingresá una fecha y hora válidas, sin zona horaria.") from None


def calculate_dates(row, motivo, form):
    created = parse_date(form.get("created_at"))
    resolved = parse_date(form.get("resuelto_at")) if row["estado"] == "resuelto" else None
    if row["estado"] != "resuelto" and form.get("resuelto_at"):
        raise ValueError("Solo se puede editar la resolución de un feedback resuelto.")
    if resolved and resolved < created:
        raise ValueError("La resolución no puede ser anterior a la carga.")
    if created != row["created_at"]:
        if not motivo or int(motivo.get("tiempo_resolucion_valor") or motivo.get("sla_dias") or 0) <= 0:
            raise ValueError("El motivo no tiene un plazo válido para recalcular el vencimiento.")
        limit = _feedback_due_datetime(motivo, now=created)
    else:
        limit = row.get("fecha_limite") or dt.datetime.combine(row["fecha_vencimiento"], dt.time(23, 59, 59))
    return dict(created_at=created, resuelto_at=resolved, fecha_limite=limit,
                fecha_vencimiento=limit.date(), resuelto_en_sla=int(resolved <= limit) if resolved else None)


def correct_dates(feedback_id, form, user_id):
    reason = (form.get("motivo_correccion") or "").strip()
    if not reason or len(reason) > 160:
        raise ValueError("Indicá el motivo de corrección (hasta 160 caracteres).")
    db = get_db()
    cursor = db.cursor(dictionary=True)
    try:
        cursor.execute("SELECT * FROM feedbacks WHERE id = %s FOR UPDATE", (feedback_id,))
        row = cursor.fetchone()
        if not row:
            raise ValueError("Feedback no encontrado.")
        # La consulta pública normaliza fecha_limite y resuelto_en_sla.
        version_row = dict(row)
        version_row["fecha_limite"] = row.get("fecha_limite") or dt.datetime.combine(row["fecha_vencimiento"], dt.time(23, 59, 59))
        version_row["resuelto_en_sla"] = row.get("resuelto_en_sla") or 0
        if form.get("version") != date_version(version_row):
            raise ValueError("El feedback cambió mientras lo editabas. Recargá la página antes de guardar.")
        cursor.execute("SELECT * FROM feedback_motivos WHERE id = %s", (row["motivo_id"],))
        changes = calculate_dates(row, cursor.fetchone(), form)
        changed = [key for key in FIELDS if row.get(key) != changes[key]]
        if not changed:
            raise ValueError("No hay cambios para guardar.")
        cursor.execute("""UPDATE feedbacks SET created_at=%s, resuelto_at=%s, fecha_limite=%s,
                          fecha_vencimiento=%s, resuelto_en_sla=%s, updated_at=NOW() WHERE id=%s""",
                       tuple(changes[key] for key in FIELDS) + (feedback_id,))
        # Cada acción cabe en auditoria.accion VARCHAR(255). Misma transacción.
        actions = ["Corrección de fechas. Motivo: " + reason]
        actions += [f"{key}: {row.get(key)} -> {changes[key]}" for key in changed]
        for action in actions:
            cursor.execute("""INSERT INTO auditoria (usuario_id, accion, tabla_afectada, registro_id)
                              VALUES (%s, %s, %s, %s)""",
                           (user_id, action, "feedback_fechas", feedback_id))
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        cursor.close()
        db.close()
