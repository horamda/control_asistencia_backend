import datetime

from flask import Blueprint, current_app, render_template

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


def _safe_fetchall(cursor, query, params=None):
    try:
        cursor.execute(query, params or ())
        return cursor.fetchall() or []
    except Exception:
        return []


def _to_int(value):
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _to_float(value):
    try:
        return float(value or 0.0)
    except (TypeError, ValueError):
        return 0.0


def _to_date(value):
    if isinstance(value, datetime.date):
        return value
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return datetime.date.fromisoformat(text[:10])
    except ValueError:
        return None


def _daterange(start_date: datetime.date, end_date: datetime.date):
    current = start_date
    while current <= end_date:
        yield current
        current += datetime.timedelta(days=1)


def _calc_expected_minutes_from_planillas(db, start_date: datetime.date, end_date: datetime.date):
    if start_date > end_date:
        return 0, set()

    dict_cursor = db.cursor(dictionary=True)
    try:
        plan_rows = _safe_fetchall(
            dict_cursor,
            """
            SELECT
                eh.empleado_id,
                eh.fecha_desde,
                eh.fecha_hasta,
                hd.dia_semana,
                COALESCE(
                    SUM(
                        CASE
                            WHEN hdb.hora_entrada IS NULL OR hdb.hora_salida IS NULL THEN 0
                            WHEN TIME_TO_SEC(hdb.hora_salida) >= TIME_TO_SEC(hdb.hora_entrada)
                                THEN (TIME_TO_SEC(hdb.hora_salida) - TIME_TO_SEC(hdb.hora_entrada)) / 60
                            ELSE ((TIME_TO_SEC(hdb.hora_salida) + 86400) - TIME_TO_SEC(hdb.hora_entrada)) / 60
                        END
                    ),
                    0
                ) AS minutos_planilla
            FROM empleado_horarios eh
            JOIN horario_dias hd ON hd.horario_id = eh.horario_id
            LEFT JOIN horario_dia_bloques hdb ON hdb.horario_dia_id = hd.id
            WHERE eh.fecha_desde <= %s
              AND (eh.fecha_hasta IS NULL OR eh.fecha_hasta >= %s)
            GROUP BY eh.empleado_id, eh.fecha_desde, eh.fecha_hasta, hd.dia_semana
            """,
            (end_date.isoformat(), start_date.isoformat()),
        )

        expected_by_employee_day = {}
        planned_employee_ids = set()
        raw_days = {_to_int(row.get("dia_semana")) for row in plan_rows}
        use_zero_based_weekday = (
            bool(raw_days)
            and 0 in raw_days
            and 7 not in raw_days
            and all(0 <= d <= 6 for d in raw_days)
        )
        for row in plan_rows:
            empleado_id = _to_int(row.get("empleado_id"))
            raw_dia_semana = _to_int(row.get("dia_semana"))
            dia_semana = raw_dia_semana
            # Compatibilidad de datos legacy con weekday 0..6 (lunes..domingo).
            if use_zero_based_weekday and 0 <= raw_dia_semana <= 6:
                dia_semana = raw_dia_semana + 1
            minutos_planilla = _to_int(row.get("minutos_planilla"))
            if empleado_id <= 0 or dia_semana < 1 or dia_semana > 7 or minutos_planilla <= 0:
                continue
            planned_employee_ids.add(empleado_id)

            fecha_desde = _to_date(row.get("fecha_desde")) or start_date
            fecha_hasta = _to_date(row.get("fecha_hasta")) or end_date
            rango_desde = max(start_date, fecha_desde)
            rango_hasta = min(end_date, fecha_hasta)
            if rango_desde > rango_hasta:
                continue

            offset = (dia_semana - rango_desde.isoweekday()) % 7
            cursor_date = rango_desde + datetime.timedelta(days=offset)
            while cursor_date <= rango_hasta:
                key = (empleado_id, cursor_date.isoformat())
                # Si hay solapamientos de asignaciones por dato sucio, tomamos el mayor esperado diario.
                expected_by_employee_day[key] = max(expected_by_employee_day.get(key, 0), minutos_planilla)
                cursor_date += datetime.timedelta(days=7)

        if not planned_employee_ids:
            return 0, set()

        employee_ids = sorted(planned_employee_ids)
        placeholders = ",".join(["%s"] * len(employee_ids))

        vacation_rows = _safe_fetchall(
            dict_cursor,
            f"""
            SELECT empleado_id, fecha_desde, fecha_hasta
            FROM vacaciones
            WHERE empleado_id IN ({placeholders})
              AND fecha_desde <= %s
              AND fecha_hasta >= %s
            """,
            (*employee_ids, end_date.isoformat(), start_date.isoformat()),
        )
        for row in vacation_rows:
            empleado_id = _to_int(row.get("empleado_id"))
            fecha_desde = _to_date(row.get("fecha_desde"))
            fecha_hasta = _to_date(row.get("fecha_hasta"))
            if empleado_id <= 0 or fecha_desde is None or fecha_hasta is None:
                continue
            for fecha in _daterange(max(start_date, fecha_desde), min(end_date, fecha_hasta)):
                expected_by_employee_day[(empleado_id, fecha.isoformat())] = 0

        franco_rows = _safe_fetchall(
            dict_cursor,
            f"""
            SELECT empleado_id, fecha
            FROM francos
            WHERE empleado_id IN ({placeholders})
              AND fecha BETWEEN %s AND %s
            """,
            (*employee_ids, start_date.isoformat(), end_date.isoformat()),
        )
        for row in franco_rows:
            empleado_id = _to_int(row.get("empleado_id"))
            fecha = _to_date(row.get("fecha"))
            if empleado_id <= 0 or fecha is None:
                continue
            expected_by_employee_day[(empleado_id, fecha.isoformat())] = 0

        exception_rows = _safe_fetchall(
            dict_cursor,
            f"""
            SELECT
                ex.id,
                ex.empleado_id,
                ex.fecha,
                ex.tipo,
                ex.anula_horario,
                COALESCE(SUM(TIMESTAMPDIFF(MINUTE, eb.hora_entrada, eb.hora_salida)), 0) AS minutos_cambio
            FROM empleado_excepciones ex
            LEFT JOIN excepcion_bloques eb ON eb.excepcion_id = ex.id
            WHERE ex.empleado_id IN ({placeholders})
              AND ex.fecha BETWEEN %s AND %s
            GROUP BY ex.id, ex.empleado_id, ex.fecha, ex.tipo, ex.anula_horario
            ORDER BY ex.fecha ASC, ex.id ASC
            """,
            (*employee_ids, start_date.isoformat(), end_date.isoformat()),
        )

        tipos_anula = {"FRANCO", "VACACIONES", "FERIADO", "LICENCIA"}
        blocked_days = set()
        for row in exception_rows:
            empleado_id = _to_int(row.get("empleado_id"))
            fecha = _to_date(row.get("fecha"))
            if empleado_id <= 0 or fecha is None:
                continue

            key = (empleado_id, fecha.isoformat())
            tipo = str(row.get("tipo") or "").strip().upper()
            anula_horario = _to_int(row.get("anula_horario")) == 1 or tipo in tipos_anula

            if anula_horario:
                expected_by_employee_day[key] = 0
                blocked_days.add(key)
                continue

            if tipo == "CAMBIO_HORARIO" and key not in blocked_days:
                expected_by_employee_day[key] = max(0, _to_int(row.get("minutos_cambio")))

        return int(sum(expected_by_employee_day.values())), planned_employee_ids
    finally:
        dict_cursor.close()


def _calc_registered_minutes_for_employees(cursor, start_iso: str, end_iso: str, employee_ids: set[int]):
    if not employee_ids:
        return 0
    ordered_ids = sorted(employee_ids)
    placeholders = ",".join(["%s"] * len(ordered_ids))
    return _safe_count(
        cursor,
        f"""
        SELECT COALESCE(SUM(GREATEST(TIMESTAMPDIFF(MINUTE, hora_entrada, hora_salida), 0)), 0)
        FROM asistencias
        WHERE fecha BETWEEN %s AND %s
          AND hora_entrada IS NOT NULL
          AND hora_salida IS NOT NULL
          AND empleado_id IN ({placeholders})
        """,
        (start_iso, end_iso, *ordered_ids),
    )


def _dashboard_metrics():
    today_dt = datetime.date.today()
    today = today_dt.isoformat()
    since_7 = (today_dt - datetime.timedelta(days=6)).isoformat()
    since_30 = (today_dt - datetime.timedelta(days=29)).isoformat()
    next_30 = (today_dt + datetime.timedelta(days=30)).isoformat()
    month_start = today_dt.replace(day=1).isoformat()
    quarter_month = ((today_dt.month - 1) // 3) * 3 + 1
    quarter_start = today_dt.replace(month=quarter_month, day=1).isoformat()
    year_start = today_dt.replace(month=1, day=1).isoformat()
    month_days_elapsed = max(1, today_dt.day)
    reincidencia_umbral = 3
    stats = {
        "empleados_activos": 0,
        "empleados_con_fichada_hoy": 0,
        "presentismo_hoy_pct": 0.0,
        "asistencias_hoy": 0,
        "fichadas_mes": 0,
        "ok_fichadas_mes": 0,
        "puntualidad_mes_pct": 0.0,
        "asistencias_30d": 0,
        "tardes_hoy": 0,
        "tardes_30d": 0,
        "ausentes_hoy": 0,
        "ausentes_30d": 0,
        "asistencias_mes": 0,
        "tardes_mes": 0,
        "ausentes_mes": 0,
        "ausentismo_mes_pct": 0.0,
        "asistencias_anio": 0,
        "tardes_anio": 0,
        "ausentes_anio": 0,
        "ausentismo_anual_pct": 0.0,
        "ausentes_trimestre": 0,
        "frecuencia_ausencias_mes": 0.0,
        "frecuencia_ausencias_trimestre": 0.0,
        "ausentes_sin_justificacion_mes": 0,
        "no_show_mes_pct": 0.0,
        "justificaciones_mes_total": 0,
        "justificaciones_mes_pendientes": 0,
        "justificaciones_mes_aprobadas": 0,
        "justificaciones_mes_rechazadas": 0,
        "tasa_aprobacion_justificaciones_mes_pct": 0.0,
        "justificaciones_pendientes_total": 0,
        "jornadas_completas_mes": 0,
        "cumplimiento_jornada_mes_pct": 0.0,
        "salida_anticipada_mes": 0,
        "tasa_salida_anticipada_mes_pct": 0.0,
        "vacaciones_en_curso_hoy": 0,
        "vacaciones_proximas_30d": 0,
        "vacaciones_dias_mes": 0,
        "vacaciones_dias_anio": 0,
        "horas_registradas_mes": 0.0,
        "horas_esperadas_mes": 0.0,
        "desvio_horas_mes": 0.0,
        "cumplimiento_horas_mes_pct": 0.0,
        "empleados_con_planilla_mes": 0,
        "asignaciones_con_planilla_mes": 0,
        "incidentes_regularizados_mes": 0,
        "incidentes_sin_regularizar_mes": 0,
        "lead_time_regularizacion_horas_mes": 0.0,
        "reincidencia_umbral": reincidencia_umbral,
        "excepciones_hoy": 0,
        "horarios_activos": 0,
        "asignaciones_vigentes": 0,
        "usuarios_activos": 0,
    }
    charts = {
        "daily_7d": [],
        "max_daily": 1,
        "status_30d": [],
        "empresa_top_30d": [],
        "max_empresa": 1,
        "justificaciones_estado_mes": [],
        "persona_top_ausencias_anio": [],
        "top_reincidencia_mes": [],
        "streak_top_empleados": [],
        "streak_top_equipos": [],
        "ausentismo_rank_empresa": [],
        "ausentismo_rank_sector": [],
        "ausentismo_rank_sucursal": [],
        "vacaciones_proximas_detalle": [],
        "vacaciones_top_dias_anio": [],
    }
    recent_events = []

    db = get_db()
    cursor = db.cursor()
    dict_cursor = None
    try:
        stats["empleados_activos"] = _safe_count(cursor, "SELECT COUNT(*) FROM empleados WHERE activo = 1")
        stats["empleados_con_fichada_hoy"] = _safe_count(
            cursor,
            """
            SELECT COUNT(DISTINCT empleado_id)
            FROM asistencias
            WHERE fecha = %s
              AND (hora_entrada IS NOT NULL OR hora_salida IS NOT NULL)
            """,
            (today,),
        )
        if stats["empleados_activos"] > 0:
            stats["presentismo_hoy_pct"] = round(
                (stats["empleados_con_fichada_hoy"] * 100.0) / stats["empleados_activos"],
                1,
            )
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
        stats["asistencias_30d"] = _safe_count(
            cursor,
            "SELECT COUNT(*) FROM asistencias WHERE fecha BETWEEN %s AND %s",
            (since_30, today),
        )
        stats["tardes_30d"] = _safe_count(
            cursor,
            "SELECT COUNT(*) FROM asistencias WHERE fecha BETWEEN %s AND %s AND estado = 'tarde'",
            (since_30, today),
        )
        stats["ausentes_30d"] = _safe_count(
            cursor,
            "SELECT COUNT(*) FROM asistencias WHERE fecha BETWEEN %s AND %s AND estado = 'ausente'",
            (since_30, today),
        )
        stats["fichadas_mes"] = _safe_count(
            cursor,
            """
            SELECT COUNT(*)
            FROM asistencias
            WHERE fecha BETWEEN %s AND %s
              AND (hora_entrada IS NOT NULL OR hora_salida IS NOT NULL)
            """,
            (month_start, today),
        )
        stats["ok_fichadas_mes"] = _safe_count(
            cursor,
            """
            SELECT COUNT(*)
            FROM asistencias
            WHERE fecha BETWEEN %s AND %s
              AND (hora_entrada IS NOT NULL OR hora_salida IS NOT NULL)
              AND estado = 'ok'
            """,
            (month_start, today),
        )
        if stats["fichadas_mes"] > 0:
            stats["puntualidad_mes_pct"] = round((stats["ok_fichadas_mes"] * 100.0) / stats["fichadas_mes"], 1)

        stats["asistencias_mes"] = _safe_count(
            cursor,
            "SELECT COUNT(*) FROM asistencias WHERE fecha BETWEEN %s AND %s",
            (month_start, today),
        )
        stats["tardes_mes"] = _safe_count(
            cursor,
            "SELECT COUNT(*) FROM asistencias WHERE fecha BETWEEN %s AND %s AND estado = 'tarde'",
            (month_start, today),
        )
        stats["ausentes_mes"] = _safe_count(
            cursor,
            "SELECT COUNT(*) FROM asistencias WHERE fecha BETWEEN %s AND %s AND estado = 'ausente'",
            (month_start, today),
        )
        if stats["asistencias_mes"] > 0:
            stats["ausentismo_mes_pct"] = round((stats["ausentes_mes"] * 100.0) / stats["asistencias_mes"], 1)
        stats["ausentes_sin_justificacion_mes"] = _safe_count(
            cursor,
            """
            SELECT COUNT(*)
            FROM asistencias a
            WHERE a.fecha BETWEEN %s AND %s
              AND a.estado = 'ausente'
              AND NOT EXISTS (
                  SELECT 1
                  FROM justificaciones j
                  WHERE j.asistencia_id = a.id
                    AND j.estado = 'aprobada'
              )
            """,
            (month_start, today),
        )
        if stats["ausentes_mes"] > 0:
            stats["no_show_mes_pct"] = round(
                (stats["ausentes_sin_justificacion_mes"] * 100.0) / stats["ausentes_mes"],
                1,
            )
        stats["justificaciones_mes_total"] = _safe_count(
            cursor,
            """
            SELECT COUNT(*)
            FROM justificaciones
            WHERE DATE(created_at) BETWEEN %s AND %s
            """,
            (month_start, today),
        )
        stats["justificaciones_mes_pendientes"] = _safe_count(
            cursor,
            """
            SELECT COUNT(*)
            FROM justificaciones
            WHERE DATE(created_at) BETWEEN %s AND %s
              AND LOWER(COALESCE(estado, 'pendiente')) = 'pendiente'
            """,
            (month_start, today),
        )
        stats["justificaciones_mes_aprobadas"] = _safe_count(
            cursor,
            """
            SELECT COUNT(*)
            FROM justificaciones
            WHERE DATE(created_at) BETWEEN %s AND %s
              AND LOWER(COALESCE(estado, 'pendiente')) = 'aprobada'
            """,
            (month_start, today),
        )
        stats["justificaciones_mes_rechazadas"] = _safe_count(
            cursor,
            """
            SELECT COUNT(*)
            FROM justificaciones
            WHERE DATE(created_at) BETWEEN %s AND %s
              AND LOWER(COALESCE(estado, 'pendiente')) = 'rechazada'
            """,
            (month_start, today),
        )
        stats["justificaciones_pendientes_total"] = _safe_count(
            cursor,
            """
            SELECT COUNT(*)
            FROM justificaciones
            WHERE LOWER(COALESCE(estado, 'pendiente')) = 'pendiente'
            """,
        )
        if stats["justificaciones_mes_total"] > 0:
            stats["tasa_aprobacion_justificaciones_mes_pct"] = round(
                (stats["justificaciones_mes_aprobadas"] * 100.0) / stats["justificaciones_mes_total"],
                1,
            )

        stats["ausentes_trimestre"] = _safe_count(
            cursor,
            "SELECT COUNT(*) FROM asistencias WHERE fecha BETWEEN %s AND %s AND estado = 'ausente'",
            (quarter_start, today),
        )
        if stats["empleados_activos"] > 0:
            stats["frecuencia_ausencias_mes"] = round(stats["ausentes_mes"] / stats["empleados_activos"], 2)
            stats["frecuencia_ausencias_trimestre"] = round(
                stats["ausentes_trimestre"] / stats["empleados_activos"],
                2,
            )

        stats["asistencias_anio"] = _safe_count(
            cursor,
            "SELECT COUNT(*) FROM asistencias WHERE fecha BETWEEN %s AND %s",
            (year_start, today),
        )
        stats["tardes_anio"] = _safe_count(
            cursor,
            "SELECT COUNT(*) FROM asistencias WHERE fecha BETWEEN %s AND %s AND estado = 'tarde'",
            (year_start, today),
        )
        stats["ausentes_anio"] = _safe_count(
            cursor,
            "SELECT COUNT(*) FROM asistencias WHERE fecha BETWEEN %s AND %s AND estado = 'ausente'",
            (year_start, today),
        )
        if stats["asistencias_anio"] > 0:
            stats["ausentismo_anual_pct"] = round((stats["ausentes_anio"] * 100.0) / stats["asistencias_anio"], 1)

        stats["jornadas_completas_mes"] = _safe_count(
            cursor,
            """
            SELECT COUNT(*)
            FROM asistencias
            WHERE fecha BETWEEN %s AND %s
              AND hora_entrada IS NOT NULL
              AND hora_salida IS NOT NULL
            """,
            (month_start, today),
        )
        if stats["fichadas_mes"] > 0:
            stats["cumplimiento_jornada_mes_pct"] = round(
                (stats["jornadas_completas_mes"] * 100.0) / stats["fichadas_mes"],
                1,
            )
        stats["salida_anticipada_mes"] = _safe_count(
            cursor,
            """
            SELECT COUNT(*)
            FROM asistencias
            WHERE fecha BETWEEN %s AND %s
              AND estado = 'salida_anticipada'
            """,
            (month_start, today),
        )
        if stats["fichadas_mes"] > 0:
            stats["tasa_salida_anticipada_mes_pct"] = round(
                (stats["salida_anticipada_mes"] * 100.0) / stats["fichadas_mes"],
                1,
            )

        minutos_esperados_mes, planned_employee_ids = _calc_expected_minutes_from_planillas(
            db, today_dt.replace(day=1), today_dt
        )
        stats["empleados_con_planilla_mes"] = len(planned_employee_ids)
        stats["asignaciones_con_planilla_mes"] = _safe_count(
            cursor,
            """
            SELECT COUNT(*)
            FROM empleado_horarios
            WHERE fecha_desde <= %s
              AND (fecha_hasta IS NULL OR fecha_hasta >= %s)
            """,
            (today, month_start),
        )
        if planned_employee_ids:
            minutos_registrados_mes = _calc_registered_minutes_for_employees(
                cursor, month_start, today, planned_employee_ids
            )
        else:
            minutos_registrados_mes = _safe_count(
                cursor,
                """
                SELECT COALESCE(SUM(GREATEST(TIMESTAMPDIFF(MINUTE, hora_entrada, hora_salida), 0)), 0)
                FROM asistencias
                WHERE fecha BETWEEN %s AND %s
                  AND hora_entrada IS NOT NULL
                  AND hora_salida IS NOT NULL
                """,
                (month_start, today),
            )
        stats["horas_registradas_mes"] = round(minutos_registrados_mes / 60.0, 1)
        stats["horas_esperadas_mes"] = round(minutos_esperados_mes / 60.0, 1)
        stats["desvio_horas_mes"] = round(stats["horas_registradas_mes"] - stats["horas_esperadas_mes"], 1)
        if minutos_esperados_mes > 0:
            stats["cumplimiento_horas_mes_pct"] = round((minutos_registrados_mes * 100.0) / minutos_esperados_mes, 1)
        else:
            current_app.logger.warning(
                "dashboard_expected_hours_zero",
                extra={
                    "extra": {
                        "month_start": month_start,
                        "today": today,
                        "asignaciones_vigentes_mes": stats["asignaciones_con_planilla_mes"],
                        "empleados_con_planilla_mes": stats["empleados_con_planilla_mes"],
                    }
                },
            )
        current_app.logger.info(
            "dashboard_hours_metrics",
            extra={
                "extra": {
                    "month_start": month_start,
                    "today": today,
                    "minutos_registrados_mes": int(minutos_registrados_mes or 0),
                    "minutos_esperados_mes": int(minutos_esperados_mes or 0),
                    "horas_registradas_mes": stats["horas_registradas_mes"],
                    "horas_esperadas_mes": stats["horas_esperadas_mes"],
                    "desvio_horas_mes": stats["desvio_horas_mes"],
                    "cumplimiento_horas_mes_pct": stats["cumplimiento_horas_mes_pct"],
                    "empleados_con_planilla_mes": stats["empleados_con_planilla_mes"],
                    "asignaciones_vigentes_mes": stats["asignaciones_con_planilla_mes"],
                }
            },
        )
        stats["vacaciones_en_curso_hoy"] = _safe_count(
            cursor,
            """
            SELECT COUNT(*)
            FROM vacaciones
            WHERE fecha_desde <= %s
              AND fecha_hasta >= %s
            """,
            (today, today),
        )
        stats["vacaciones_proximas_30d"] = _safe_count(
            cursor,
            """
            SELECT COUNT(*)
            FROM vacaciones
            WHERE fecha_desde > %s
              AND fecha_desde <= %s
            """,
            (today, next_30),
        )
        stats["vacaciones_dias_mes"] = _safe_count(
            cursor,
            """
            SELECT COALESCE(
                SUM(
                    GREATEST(
                        0,
                        DATEDIFF(LEAST(v.fecha_hasta, %s), GREATEST(v.fecha_desde, %s)) + 1
                    )
                ),
                0
            )
            FROM vacaciones v
            WHERE v.fecha_desde <= %s
              AND v.fecha_hasta >= %s
            """,
            (today, month_start, today, month_start),
        )
        stats["vacaciones_dias_anio"] = _safe_count(
            cursor,
            """
            SELECT COALESCE(
                SUM(
                    GREATEST(
                        0,
                        DATEDIFF(LEAST(v.fecha_hasta, %s), GREATEST(v.fecha_desde, %s)) + 1
                    )
                ),
                0
            )
            FROM vacaciones v
            WHERE v.fecha_desde <= %s
              AND v.fecha_hasta >= %s
            """,
            (today, year_start, today, year_start),
        )

        dict_cursor = db.cursor(dictionary=True)

        lead_row = _safe_fetchall(
            dict_cursor,
            """
            SELECT
                COUNT(*) AS incidentes,
                SUM(CASE WHEN j.first_created_at IS NULL THEN 1 ELSE 0 END) AS sin_regularizar,
                AVG(
                    CASE
                        WHEN j.first_created_at IS NULL THEN NULL
                        ELSE TIMESTAMPDIFF(
                            HOUR,
                            TIMESTAMP(a.fecha, COALESCE(a.hora_entrada, a.hora_salida, '00:00:00')),
                            j.first_created_at
                        )
                    END
                ) AS lead_horas
            FROM asistencias a
            LEFT JOIN (
                SELECT asistencia_id, MIN(created_at) AS first_created_at
                FROM justificaciones
                WHERE asistencia_id IS NOT NULL
                GROUP BY asistencia_id
            ) j ON j.asistencia_id = a.id
            WHERE a.fecha BETWEEN %s AND %s
              AND a.estado IN ('ausente', 'tarde', 'salida_anticipada')
            """,
            (month_start, today),
        )
        lead_data = lead_row[0] if lead_row else {}
        incidentes_mes = _to_int(lead_data.get("incidentes"))
        stats["incidentes_sin_regularizar_mes"] = _to_int(lead_data.get("sin_regularizar"))
        stats["incidentes_regularizados_mes"] = max(0, incidentes_mes - stats["incidentes_sin_regularizar_mes"])
        stats["lead_time_regularizacion_horas_mes"] = round(_to_float(lead_data.get("lead_horas")), 1)
        just_rows = _safe_fetchall(
            dict_cursor,
            """
            SELECT
                LOWER(COALESCE(estado, 'pendiente')) AS estado,
                COUNT(*) AS total
            FROM justificaciones
            WHERE DATE(created_at) BETWEEN %s AND %s
            GROUP BY LOWER(COALESCE(estado, 'pendiente'))
            """,
            (month_start, today),
        )
        just_totals = {}
        for row in just_rows:
            key = str(row.get("estado") or "pendiente").strip().lower()
            just_totals[key] = just_totals.get(key, 0) + _to_int(row.get("total"))
        known_just_states = [
            ("pendiente", "Pendiente", "warning"),
            ("aprobada", "Aprobada", "ok"),
            ("rechazada", "Rechazada", "danger"),
        ]
        used_just_keys = {key for key, _, _ in known_just_states}
        for key, label, tone in known_just_states:
            total = just_totals.get(key, 0)
            pct = round((total * 100.0) / stats["justificaciones_mes_total"], 1) if stats["justificaciones_mes_total"] > 0 else 0.0
            charts["justificaciones_estado_mes"].append(
                {"key": key, "label": label, "tone": tone, "total": total, "pct": pct}
            )
        otros_just_total = sum(value for key, value in just_totals.items() if key not in used_just_keys)
        if otros_just_total > 0:
            pct = (
                round((otros_just_total * 100.0) / stats["justificaciones_mes_total"], 1)
                if stats["justificaciones_mes_total"] > 0
                else 0.0
            )
            charts["justificaciones_estado_mes"].append(
                {"key": "otros", "label": "Otros", "tone": "neutral", "total": otros_just_total, "pct": pct}
            )

        vac_rows = _safe_fetchall(
            dict_cursor,
            """
            SELECT
                v.id,
                v.fecha_desde,
                v.fecha_hasta,
                e.apellido,
                e.nombre,
                COALESCE(emp.razon_social, 'Sin empresa') AS empresa,
                DATEDIFF(v.fecha_hasta, v.fecha_desde) + 1 AS dias
            FROM vacaciones v
            JOIN empleados e ON e.id = v.empleado_id
            LEFT JOIN empresas emp ON emp.id = e.empresa_id
            WHERE v.fecha_desde > %s
              AND v.fecha_desde <= %s
            ORDER BY v.fecha_desde ASC, e.apellido ASC, e.nombre ASC
            LIMIT 12
            """,
            (today, next_30),
        )
        charts["vacaciones_proximas_detalle"] = [
            {
                "id": _to_int(row.get("id")),
                "fecha_desde": str(row.get("fecha_desde") or ""),
                "fecha_hasta": str(row.get("fecha_hasta") or ""),
                "apellido": str(row.get("apellido") or "").strip(),
                "nombre": str(row.get("nombre") or "").strip(),
                "empresa": str(row.get("empresa") or "Sin empresa"),
                "dias": max(0, _to_int(row.get("dias"))),
            }
            for row in vac_rows
        ]
        vac_top_rows = _safe_fetchall(
            dict_cursor,
            """
            SELECT
                e.id AS empleado_id,
                e.apellido,
                e.nombre,
                COALESCE(emp.razon_social, 'Sin empresa') AS empresa,
                SUM(
                    GREATEST(
                        0,
                        DATEDIFF(LEAST(v.fecha_hasta, %s), GREATEST(v.fecha_desde, %s)) + 1
                    )
                ) AS dias
            FROM vacaciones v
            JOIN empleados e ON e.id = v.empleado_id
            LEFT JOIN empresas emp ON emp.id = e.empresa_id
            WHERE v.fecha_desde <= %s
              AND v.fecha_hasta >= %s
            GROUP BY e.id, e.apellido, e.nombre, emp.razon_social
            HAVING dias > 0
            ORDER BY dias DESC, e.apellido ASC, e.nombre ASC
            LIMIT 10
            """,
            (today, year_start, today, year_start),
        )
        charts["vacaciones_top_dias_anio"] = [
            {
                "empleado_id": _to_int(row.get("empleado_id")),
                "apellido": str(row.get("apellido") or "").strip(),
                "nombre": str(row.get("nombre") or "").strip(),
                "empresa": str(row.get("empresa") or "Sin empresa"),
                "dias": max(0, _to_int(row.get("dias"))),
            }
            for row in vac_top_rows
        ]
        max_vac_dias = max([1] + [item["dias"] for item in charts["vacaciones_top_dias_anio"]])
        for item in charts["vacaciones_top_dias_anio"]:
            item["dias_pct"] = round((item["dias"] * 100.0) / max_vac_dias, 1)

        daily_rows = _safe_fetchall(
            dict_cursor,
            """
            SELECT
                fecha,
                COUNT(*) AS asistencias,
                SUM(CASE WHEN estado = 'tarde' THEN 1 ELSE 0 END) AS tardes,
                SUM(CASE WHEN estado = 'ausente' THEN 1 ELSE 0 END) AS ausentes
            FROM asistencias
            WHERE fecha BETWEEN %s AND %s
            GROUP BY fecha
            ORDER BY fecha ASC
            """,
            (since_7, today),
        )
        by_date = {str(row.get("fecha")): row for row in daily_rows}
        day_cursor = today_dt - datetime.timedelta(days=6)
        for _ in range(7):
            iso = day_cursor.isoformat()
            row = by_date.get(iso, {})
            charts["daily_7d"].append(
                {
                    "fecha": iso,
                    "dia": day_cursor.strftime("%d/%m"),
                    "asistencias": _to_int(row.get("asistencias")),
                    "tardes": _to_int(row.get("tardes")),
                    "ausentes": _to_int(row.get("ausentes")),
                }
            )
            day_cursor += datetime.timedelta(days=1)
        charts["max_daily"] = max(
            [1]
            + [
                max(item["asistencias"], item["tardes"], item["ausentes"])
                for item in charts["daily_7d"]
            ]
        )

        status_rows = _safe_fetchall(
            dict_cursor,
            """
            SELECT COALESCE(estado, 'sin_estado') AS estado, COUNT(*) AS total
            FROM asistencias
            WHERE fecha BETWEEN %s AND %s
            GROUP BY COALESCE(estado, 'sin_estado')
            """,
            (since_30, today),
        )
        state_totals = {}
        for row in status_rows:
            key = str(row.get("estado") or "sin_estado").strip().lower()
            state_totals[key] = state_totals.get(key, 0) + _to_int(row.get("total"))

        known_states = [
            ("ok", "OK", "ok"),
            ("tarde", "Tarde", "warning"),
            ("ausente", "Ausente", "danger"),
            ("salida_anticipada", "Salida anticipada", "neutral"),
        ]
        used_keys = {k for k, _, _ in known_states}
        for key, label, tone in known_states:
            total = state_totals.get(key, 0)
            pct = round((total * 100.0) / stats["asistencias_30d"], 1) if stats["asistencias_30d"] > 0 else 0.0
            charts["status_30d"].append({"key": key, "label": label, "tone": tone, "total": total, "pct": pct})

        otros_total = sum(v for k, v in state_totals.items() if k not in used_keys)
        if otros_total > 0:
            pct = round((otros_total * 100.0) / stats["asistencias_30d"], 1) if stats["asistencias_30d"] > 0 else 0.0
            charts["status_30d"].append(
                {"key": "otros", "label": "Otros", "tone": "neutral", "total": otros_total, "pct": pct}
            )

        empresa_rows = _safe_fetchall(
            dict_cursor,
            """
            SELECT
                emp.razon_social AS empresa,
                COUNT(*) AS total,
                SUM(CASE WHEN a.estado = 'ausente' THEN 1 ELSE 0 END) AS ausentes,
                SUM(CASE WHEN a.estado = 'tarde' THEN 1 ELSE 0 END) AS tardes
            FROM asistencias a
            JOIN empresas emp ON emp.id = a.empresa_id
            WHERE a.fecha BETWEEN %s AND %s
            GROUP BY emp.id, emp.razon_social
            ORDER BY ausentes DESC, tardes DESC, total DESC
            LIMIT 8
            """,
            (since_30, today),
        )
        charts["empresa_top_30d"] = [
            {
                "empresa": str(row.get("empresa") or "Sin empresa"),
                "total": _to_int(row.get("total")),
                "ausentes": _to_int(row.get("ausentes")),
                "tardes": _to_int(row.get("tardes")),
            }
            for row in empresa_rows
        ]
        charts["max_empresa"] = max(
            [1] + [max(item["ausentes"], item["tardes"]) for item in charts["empresa_top_30d"]]
        )

        for item in charts["empresa_top_30d"]:
            item["ausentes_pct"] = round((item["ausentes"] * 100.0) / charts["max_empresa"], 1)
            item["tardes_pct"] = round((item["tardes"] * 100.0) / charts["max_empresa"], 1)

        reincidencia_rows = _safe_fetchall(
            dict_cursor,
            """
            SELECT
                e.id AS empleado_id,
                e.apellido,
                e.nombre,
                e.dni,
                emp.razon_social AS empresa,
                SUM(CASE WHEN a.estado = 'ausente' THEN 1 ELSE 0 END) AS ausencias,
                SUM(CASE WHEN a.estado = 'tarde' THEN 1 ELSE 0 END) AS tardanzas,
                SUM(CASE WHEN a.estado = 'salida_anticipada' THEN 1 ELSE 0 END) AS salidas_anticipadas,
                SUM(CASE WHEN a.estado IN ('ausente', 'tarde', 'salida_anticipada') THEN 1 ELSE 0 END) AS incidentes
            FROM asistencias a
            JOIN empleados e ON e.id = a.empleado_id
            JOIN empresas emp ON emp.id = a.empresa_id
            WHERE a.fecha BETWEEN %s AND %s
            GROUP BY e.id, e.apellido, e.nombre, e.dni, emp.razon_social
            HAVING incidentes >= %s
            ORDER BY incidentes DESC, ausencias DESC, tardanzas DESC
            LIMIT 12
            """,
            (month_start, today, reincidencia_umbral),
        )
        charts["top_reincidencia_mes"] = [
            {
                "empleado_id": _to_int(row.get("empleado_id")),
                "apellido": str(row.get("apellido") or "").strip(),
                "nombre": str(row.get("nombre") or "").strip(),
                "dni": str(row.get("dni") or "").strip(),
                "empresa": str(row.get("empresa") or "Sin empresa"),
                "ausencias": _to_int(row.get("ausencias")),
                "tardanzas": _to_int(row.get("tardanzas")),
                "salidas_anticipadas": _to_int(row.get("salidas_anticipadas")),
                "incidentes": _to_int(row.get("incidentes")),
            }
            for row in reincidencia_rows
        ]

        persona_rows = _safe_fetchall(
            dict_cursor,
            """
            SELECT
                e.id AS empleado_id,
                e.apellido,
                e.nombre,
                e.dni,
                emp.razon_social AS empresa,
                SUM(CASE WHEN a.estado = 'ausente' THEN 1 ELSE 0 END) AS ausencias,
                SUM(CASE WHEN a.estado = 'tarde' THEN 1 ELSE 0 END) AS tardanzas,
                COUNT(*) AS total
            FROM asistencias a
            JOIN empleados e ON e.id = a.empleado_id
            JOIN empresas emp ON emp.id = a.empresa_id
            WHERE a.fecha BETWEEN %s AND %s
            GROUP BY e.id, e.apellido, e.nombre, e.dni, emp.razon_social
            HAVING SUM(CASE WHEN a.estado = 'ausente' THEN 1 ELSE 0 END) > 0
            ORDER BY ausencias DESC, tardanzas DESC, total DESC
            LIMIT 12
            """,
            (year_start, today),
        )
        charts["persona_top_ausencias_anio"] = [
            {
                "empleado_id": _to_int(row.get("empleado_id")),
                "apellido": str(row.get("apellido") or "").strip(),
                "nombre": str(row.get("nombre") or "").strip(),
                "dni": str(row.get("dni") or "").strip(),
                "empresa": str(row.get("empresa") or "Sin empresa"),
                "ausencias": _to_int(row.get("ausencias")),
                "tardanzas": _to_int(row.get("tardanzas")),
                "total": _to_int(row.get("total")),
            }
            for row in persona_rows
        ]

        streak_rows = _safe_fetchall(
            dict_cursor,
            """
            SELECT
                a.empleado_id,
                a.fecha,
                a.estado,
                a.hora_entrada,
                a.hora_salida,
                e.apellido,
                e.nombre,
                e.dni,
                emp.razon_social AS empresa,
                sec.nombre AS sector,
                suc.nombre AS sucursal
            FROM asistencias a
            JOIN empleados e ON e.id = a.empleado_id
            JOIN empresas emp ON emp.id = e.empresa_id
            LEFT JOIN sectores sec ON sec.id = e.sector_id
            LEFT JOIN sucursales suc ON suc.id = e.sucursal_id
            WHERE a.fecha BETWEEN %s AND %s
            ORDER BY a.empleado_id ASC, a.fecha DESC, a.id DESC
            """,
            (year_start, today),
        )

        streak_state = {}
        for row in streak_rows:
            empleado_id = _to_int(row.get("empleado_id"))
            if empleado_id <= 0:
                continue
            fecha = _to_date(row.get("fecha"))
            if fecha is None:
                continue
            state = streak_state.get(empleado_id)
            if state is None:
                state = {
                    "streak": 0,
                    "closed": False,
                    "prev_date": None,
                    "seen_days": set(),
                    "meta": {
                        "empleado_id": empleado_id,
                        "apellido": str(row.get("apellido") or "").strip(),
                        "nombre": str(row.get("nombre") or "").strip(),
                        "dni": str(row.get("dni") or "").strip(),
                        "empresa": str(row.get("empresa") or "Sin empresa"),
                        "sector": str(row.get("sector") or "Sin sector"),
                        "sucursal": str(row.get("sucursal") or "Sin sucursal"),
                    },
                }
                streak_state[empleado_id] = state

            if state["closed"] or fecha in state["seen_days"]:
                continue
            state["seen_days"].add(fecha)

            is_perfect = (
                str(row.get("estado") or "").strip().lower() == "ok"
                and row.get("hora_entrada") is not None
                and row.get("hora_salida") is not None
            )

            if state["streak"] == 0:
                if is_perfect:
                    state["streak"] = 1
                    state["prev_date"] = fecha
                else:
                    state["closed"] = True
                continue

            prev_date = state["prev_date"]
            delta_days = (prev_date - fecha).days if prev_date else -1
            if is_perfect and delta_days == 1:
                state["streak"] += 1
                state["prev_date"] = fecha
            else:
                state["closed"] = True

        streak_items = []
        for state in streak_state.values():
            streak_value = _to_int(state.get("streak"))
            if streak_value <= 0:
                continue
            item = dict(state.get("meta") or {})
            item["streak"] = streak_value
            streak_items.append(item)
        streak_items.sort(key=lambda x: (x.get("streak", 0), x.get("apellido", ""), x.get("nombre", "")), reverse=True)
        charts["streak_top_empleados"] = streak_items[:12]

        streak_teams = {}
        for item in streak_items:
            team = str(item.get("empresa") or "Sin empresa")
            bucket = streak_teams.setdefault(team, {"empresa": team, "sum": 0, "count": 0, "max": 0})
            streak_value = _to_int(item.get("streak"))
            bucket["sum"] += streak_value
            bucket["count"] += 1
            if streak_value > bucket["max"]:
                bucket["max"] = streak_value
        team_list = []
        for bucket in streak_teams.values():
            avg_value = round(bucket["sum"] / bucket["count"], 2) if bucket["count"] > 0 else 0.0
            team_list.append(
                {
                    "equipo": bucket["empresa"],
                    "promedio_racha": avg_value,
                    "max_racha": bucket["max"],
                    "empleados_con_racha": bucket["count"],
                }
            )
        team_list.sort(
            key=lambda x: (x.get("promedio_racha", 0.0), x.get("max_racha", 0), x.get("equipo", "")),
            reverse=True,
        )
        charts["streak_top_equipos"] = team_list[:8]

        def _normalize_rank(rows):
            items = []
            for row in rows:
                dotacion = _to_int(row.get("dotacion"))
                ausentes = _to_int(row.get("ausentes"))
                if dotacion <= 0:
                    continue
                indice = round(ausentes / dotacion, 2)
                tasa_pct = round((ausentes * 100.0) / (dotacion * month_days_elapsed), 2)
                items.append(
                    {
                        "nombre": str(row.get("nombre") or "Sin nombre").strip(),
                        "dotacion": dotacion,
                        "ausentes": ausentes,
                        "indice_ausencias_por_empleado": indice,
                        "tasa_pct": tasa_pct,
                    }
                )
            items.sort(
                key=lambda x: (
                    x.get("indice_ausencias_por_empleado", 0.0),
                    x.get("ausentes", 0),
                    x.get("nombre", ""),
                ),
                reverse=True,
            )
            return items[:8]

        aus_emp_rows = _safe_fetchall(
            dict_cursor,
            """
            SELECT
                emp.razon_social AS nombre,
                COALESCE(a.ausentes, 0) AS ausentes,
                COALESCE(d.dotacion, 0) AS dotacion
            FROM empresas emp
            LEFT JOIN (
                SELECT empresa_id, COUNT(*) AS ausentes
                FROM asistencias
                WHERE fecha BETWEEN %s AND %s
                  AND estado = 'ausente'
                GROUP BY empresa_id
            ) a ON a.empresa_id = emp.id
            LEFT JOIN (
                SELECT empresa_id, COUNT(*) AS dotacion
                FROM empleados
                WHERE activo = 1
                GROUP BY empresa_id
            ) d ON d.empresa_id = emp.id
            WHERE COALESCE(d.dotacion, 0) > 0
            ORDER BY (COALESCE(a.ausentes, 0) / NULLIF(d.dotacion, 0)) DESC, COALESCE(a.ausentes, 0) DESC
            LIMIT 20
            """,
            (month_start, today),
        )
        charts["ausentismo_rank_empresa"] = _normalize_rank(aus_emp_rows)

        aus_sector_rows = _safe_fetchall(
            dict_cursor,
            """
            SELECT
                COALESCE(sec.nombre, 'Sin sector') AS nombre,
                COALESCE(a.ausentes, 0) AS ausentes,
                COALESCE(d.dotacion, 0) AS dotacion
            FROM (
                SELECT COALESCE(sector_id, 0) AS gid, COUNT(*) AS dotacion
                FROM empleados
                WHERE activo = 1
                GROUP BY COALESCE(sector_id, 0)
            ) d
            LEFT JOIN (
                SELECT COALESCE(e.sector_id, 0) AS gid, COUNT(*) AS ausentes
                FROM asistencias a
                JOIN empleados e ON e.id = a.empleado_id
                WHERE a.fecha BETWEEN %s AND %s
                  AND a.estado = 'ausente'
                GROUP BY COALESCE(e.sector_id, 0)
            ) a ON a.gid = d.gid
            LEFT JOIN sectores sec ON sec.id = NULLIF(d.gid, 0)
            ORDER BY (COALESCE(a.ausentes, 0) / NULLIF(d.dotacion, 0)) DESC, COALESCE(a.ausentes, 0) DESC
            LIMIT 20
            """,
            (month_start, today),
        )
        charts["ausentismo_rank_sector"] = _normalize_rank(aus_sector_rows)

        aus_sucursal_rows = _safe_fetchall(
            dict_cursor,
            """
            SELECT
                COALESCE(suc.nombre, 'Sin sucursal') AS nombre,
                COALESCE(a.ausentes, 0) AS ausentes,
                COALESCE(d.dotacion, 0) AS dotacion
            FROM (
                SELECT COALESCE(sucursal_id, 0) AS gid, COUNT(*) AS dotacion
                FROM empleados
                WHERE activo = 1
                GROUP BY COALESCE(sucursal_id, 0)
            ) d
            LEFT JOIN (
                SELECT COALESCE(e.sucursal_id, 0) AS gid, COUNT(*) AS ausentes
                FROM asistencias a
                JOIN empleados e ON e.id = a.empleado_id
                WHERE a.fecha BETWEEN %s AND %s
                  AND a.estado = 'ausente'
                GROUP BY COALESCE(e.sucursal_id, 0)
            ) a ON a.gid = d.gid
            LEFT JOIN sucursales suc ON suc.id = NULLIF(d.gid, 0)
            ORDER BY (COALESCE(a.ausentes, 0) / NULLIF(d.dotacion, 0)) DESC, COALESCE(a.ausentes, 0) DESC
            LIMIT 20
            """,
            (month_start, today),
        )
        charts["ausentismo_rank_sucursal"] = _normalize_rank(aus_sucursal_rows)

        recent_events = _safe_fetchall(
            dict_cursor,
            """
            SELECT a.fecha, a.accion, a.tabla_afectada, a.registro_id, u.usuario AS usuario_nombre
            FROM auditoria a
            LEFT JOIN usuarios u ON u.id = a.usuario_id
            ORDER BY a.fecha DESC, a.id DESC
            LIMIT 8
            """,
        )
    except Exception:
        try:
            current_app.logger.exception("Error calculando metricas del dashboard")
        except Exception:
            pass
    finally:
        cursor.close()
        if dict_cursor is not None:
            dict_cursor.close()
        db.close()

    return stats, recent_events, charts


@web_bp.route("/dashboard")
@login_required
def dashboard():
    stats, recent_events, charts = _dashboard_metrics()
    return render_template("dashboard.html", stats=stats, recent_events=recent_events, charts=charts)
