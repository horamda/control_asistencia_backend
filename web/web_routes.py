import datetime

from flask import Blueprint, render_template

from extensions import get_db
from web.auth.decorators import login_required

web_bp = Blueprint("web", __name__)


def _safe_count(cursor, query, params=None):
    try:
        cursor.execute(query, params or ())
        row = cursor.fetchone()
        return int(row[0] if row else 0)
    except Exception:
        return 0


def _dashboard_metrics():
    today = datetime.date.today().isoformat()
    stats = {
        "empleados_activos": 0,
        "asistencias_hoy": 0,
        "tardes_hoy": 0,
        "ausentes_hoy": 0,
        "excepciones_hoy": 0,
        "horarios_activos": 0,
        "asignaciones_vigentes": 0,
        "usuarios_activos": 0,
    }
    recent_events = []

    db = get_db()
    cursor = db.cursor()
    audit_cursor = None
    try:
        stats["empleados_activos"] = _safe_count(cursor, "SELECT COUNT(*) FROM empleados WHERE activo = 1")
        stats["asistencias_hoy"] = _safe_count(cursor, "SELECT COUNT(*) FROM asistencias WHERE fecha = %s", (today,))
        stats["tardes_hoy"] = _safe_count(
            cursor,
            "SELECT COUNT(*) FROM asistencias WHERE fecha = %s AND estado = 'tarde'",
            (today,),
        )
        stats["ausentes_hoy"] = _safe_count(
            cursor,
            "SELECT COUNT(*) FROM asistencias WHERE fecha = %s AND estado = 'ausente'",
            (today,),
        )
        stats["excepciones_hoy"] = _safe_count(
            cursor,
            "SELECT COUNT(*) FROM empleado_excepciones WHERE fecha = %s",
            (today,),
        )
        stats["horarios_activos"] = _safe_count(cursor, "SELECT COUNT(*) FROM horarios WHERE activo = 1")
        stats["asignaciones_vigentes"] = _safe_count(
            cursor,
            """
            SELECT COUNT(*)
            FROM empleado_horarios
            WHERE fecha_desde <= %s
              AND (fecha_hasta IS NULL OR fecha_hasta >= %s)
            """,
            (today, today),
        )
        stats["usuarios_activos"] = _safe_count(cursor, "SELECT COUNT(*) FROM usuarios WHERE activo = 1")

        audit_cursor = db.cursor(dictionary=True)
        audit_cursor.execute(
            """
            SELECT a.fecha, a.accion, a.tabla_afectada, a.registro_id, u.usuario AS usuario_nombre
            FROM auditoria a
            LEFT JOIN usuarios u ON u.id = a.usuario_id
            ORDER BY a.fecha DESC, a.id DESC
            LIMIT 8
            """
        )
        recent_events = audit_cursor.fetchall()
    except Exception:
        pass
    finally:
        cursor.close()
        if audit_cursor is not None:
            audit_cursor.close()
        db.close()

    return stats, recent_events


@web_bp.route("/dashboard")
@login_required
def dashboard():
    stats, recent_events = _dashboard_metrics()
    return render_template("dashboard.html", stats=stats, recent_events=recent_events)
