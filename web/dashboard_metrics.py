import datetime

from flask import current_app, request

from extensions import get_db


def _safe_count(cursor, query, params=None):
    try:
        cursor.execute(query, params or ())
        row = cursor.fetchone()
        return int(row[0] if row else 0)
    except Exception:
        current_app.logger.warning("dashboard_safe_count_error", exc_info=True)
        return 0


def _safe_fetchall(cursor, query, params=None):
    try:
        cursor.execute(query, params or ())
        return cursor.fetchall() or []
    except Exception:
        current_app.logger.warning("dashboard_safe_fetchall_error", exc_info=True)
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


def _parse_optional_int(value):
    try:
        parsed = int(value)
        return parsed if parsed > 0 else None
    except (TypeError, ValueError):
        return None


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


def _calc_expected_minutes_from_planillas(
    db,
    start_date: datetime.date,
    end_date: datetime.date,
    empresa_id: int | None = None,
    sucursal_id: int | None = None,
):
    if start_date > end_date:
        return 0, set(), {}

    dict_cursor = db.cursor(dictionary=True)
    try:
        scope_where = []
        scope_params = []
        if empresa_id:
            scope_where.append("e.empresa_id = %s")
            scope_params.append(int(empresa_id))
        if sucursal_id:
            scope_where.append("e.sucursal_id = %s")
            scope_params.append(int(sucursal_id))
        scope_sql = (" AND " + " AND ".join(scope_where)) if scope_where else ""

        plan_rows = _safe_fetchall(
            dict_cursor,
            f"""
            SELECT
                eh.empleado_id,
                eh.horario_id,
                h.nombre AS horario_nombre,
                e.empresa_id,
                COALESCE(emp.razon_social, 'Sin empresa') AS empresa_nombre,
                e.sucursal_id,
                COALESCE(suc.nombre, 'Sin sucursal') AS sucursal_nombre,
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
            JOIN empleados e ON e.id = eh.empleado_id
            JOIN horarios h ON h.id = eh.horario_id
            LEFT JOIN empresas emp ON emp.id = e.empresa_id
            LEFT JOIN sucursales suc ON suc.id = e.sucursal_id
            JOIN horario_dias hd ON hd.horario_id = eh.horario_id
            LEFT JOIN horario_dia_bloques hdb ON hdb.horario_dia_id = hd.id
            WHERE eh.fecha_desde <= %s
              AND (eh.fecha_hasta IS NULL OR eh.fecha_hasta >= %s)
              {scope_sql}
            GROUP BY
                eh.empleado_id,
                eh.horario_id,
                h.nombre,
                e.empresa_id,
                emp.razon_social,
                e.sucursal_id,
                suc.nombre,
                eh.fecha_desde,
                eh.fecha_hasta,
                hd.dia_semana
            """,
            (end_date.isoformat(), start_date.isoformat(), *scope_params),
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
                payload = {
                    "minutos": minutos_planilla,
                    "horario_id": _to_int(row.get("horario_id")),
                    "horario_nombre": str(row.get("horario_nombre") or "Sin plantilla").strip(),
                    "empresa_id": _to_int(row.get("empresa_id")),
                    "empresa_nombre": str(row.get("empresa_nombre") or "Sin empresa").strip(),
                    "sucursal_id": _to_int(row.get("sucursal_id")),
                    "sucursal_nombre": str(row.get("sucursal_nombre") or "Sin sucursal").strip(),
                }
                prev = expected_by_employee_day.get(key)
                # Si hay solapamientos de asignaciones por dato sucio, tomamos el mayor esperado diario.
                if prev is None or payload["minutos"] > _to_int(prev.get("minutos")):
                    expected_by_employee_day[key] = payload
                cursor_date += datetime.timedelta(days=7)

        if not planned_employee_ids:
            return 0, set(), {}

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
                key = (empleado_id, fecha.isoformat())
                if key in expected_by_employee_day:
                    expected_by_employee_day[key]["minutos"] = 0

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
            key = (empleado_id, fecha.isoformat())
            if key in expected_by_employee_day:
                expected_by_employee_day[key]["minutos"] = 0

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
            if key not in expected_by_employee_day:
                continue
            tipo = str(row.get("tipo") or "").strip().upper()
            anula_horario = _to_int(row.get("anula_horario")) == 1 or tipo in tipos_anula

            if anula_horario:
                expected_by_employee_day[key]["minutos"] = 0
                blocked_days.add(key)
                continue

            if tipo == "CAMBIO_HORARIO" and key not in blocked_days:
                expected_by_employee_day[key]["minutos"] = max(0, _to_int(row.get("minutos_cambio")))

        total_expected = int(sum(_to_int(item.get("minutos")) for item in expected_by_employee_day.values()))
        return total_expected, planned_employee_ids, expected_by_employee_day
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


def _calc_registered_minutes_map_for_employees(db, start_iso: str, end_iso: str, employee_ids: set[int]):
    if not employee_ids:
        return {}
    ordered_ids = sorted(employee_ids)
    placeholders = ",".join(["%s"] * len(ordered_ids))
    dict_cursor = db.cursor(dictionary=True)
    try:
        rows = _safe_fetchall(
            dict_cursor,
            f"""
            SELECT
                empleado_id,
                fecha,
                COALESCE(SUM(GREATEST(TIMESTAMPDIFF(MINUTE, hora_entrada, hora_salida), 0)), 0) AS minutos
            FROM asistencias
            WHERE fecha BETWEEN %s AND %s
              AND hora_entrada IS NOT NULL
              AND hora_salida IS NOT NULL
              AND empleado_id IN ({placeholders})
            GROUP BY empleado_id, fecha
            """,
            (start_iso, end_iso, *ordered_ids),
        )
        result = {}
        for row in rows:
            empleado_id = _to_int(row.get("empleado_id"))
            fecha = _to_date(row.get("fecha"))
            if empleado_id <= 0 or fecha is None:
                continue
            result[(empleado_id, fecha.isoformat())] = _to_int(row.get("minutos"))
        return result
    finally:
        dict_cursor.close()


def _build_hours_breakdowns(expected_by_employee_day: dict, registered_by_employee_day: dict):
    by_plantilla = {}
    by_sucursal = {}

    for key, payload in expected_by_employee_day.items():
        empleado_id = _to_int(key[0] if isinstance(key, tuple) and len(key) == 2 else 0)
        minutos_esperados = _to_int(payload.get("minutos"))
        minutos_registrados = _to_int(registered_by_employee_day.get(key))
        horario_id = _to_int(payload.get("horario_id"))
        horario_nombre = str(payload.get("horario_nombre") or "Sin plantilla").strip()
        empresa_id = _to_int(payload.get("empresa_id"))
        empresa_nombre = str(payload.get("empresa_nombre") or "Sin empresa").strip()
        sucursal_id = _to_int(payload.get("sucursal_id"))
        sucursal_nombre = str(payload.get("sucursal_nombre") or "Sin sucursal").strip()

        # La plantilla debe segmentarse por empresa/sucursal para no mezclar
        # horas cuando una misma plantilla se usa en distintos alcances.
        plantilla_key = (
            (horario_id, empresa_id, sucursal_id)
            if horario_id > 0
            else f"legacy::{horario_nombre}::{empresa_id}::{sucursal_id}"
        )
        plantilla = by_plantilla.setdefault(
            plantilla_key,
            {
                "horario_id": horario_id,
                "horario_nombre": horario_nombre,
                "empresa_id": empresa_id,
                "empresa_nombre": empresa_nombre,
                "sucursal_id": sucursal_id,
                "sucursal_nombre": sucursal_nombre,
                "minutos_esperados": 0,
                "minutos_registrados": 0,
                "_empleados": set(),
            },
        )
        plantilla["minutos_esperados"] += minutos_esperados
        plantilla["minutos_registrados"] += minutos_registrados
        if empleado_id > 0:
            plantilla["_empleados"].add(empleado_id)

        sucursal_key = (empresa_id, sucursal_id)
        sucursal = by_sucursal.setdefault(
            sucursal_key,
            {
                "empresa_id": empresa_id,
                "empresa_nombre": empresa_nombre,
                "sucursal_id": sucursal_id,
                "sucursal_nombre": sucursal_nombre,
                "minutos_esperados": 0,
                "minutos_registrados": 0,
                "_empleados": set(),
                "_plantillas": set(),
            },
        )
        sucursal["minutos_esperados"] += minutos_esperados
        sucursal["minutos_registrados"] += minutos_registrados
        if empleado_id > 0:
            sucursal["_empleados"].add(empleado_id)
        if plantilla_key:
            sucursal["_plantillas"].add(plantilla_key)

    def _finalize(rows, with_templates=False):
        items = []
        for row in rows.values():
            minutos_esperados = _to_int(row.get("minutos_esperados"))
            minutos_registrados = _to_int(row.get("minutos_registrados"))
            horas_esperadas = round(minutos_esperados / 60.0, 1)
            horas_registradas = round(minutos_registrados / 60.0, 1)
            cumplimiento_pct = round((minutos_registrados * 100.0) / minutos_esperados, 1) if minutos_esperados > 0 else 0.0
            item = {k: v for k, v in row.items() if not k.startswith("_")}
            item.update(
                {
                    "empleados_con_planilla": len(row.get("_empleados") or []),
                    "horas_esperadas": horas_esperadas,
                    "horas_registradas": horas_registradas,
                    "desvio_horas": round(horas_registradas - horas_esperadas, 1),
                    "cumplimiento_pct": cumplimiento_pct,
                }
            )
            if with_templates:
                item["plantillas_activas"] = len(row.get("_plantillas") or [])
            items.append(item)
        items.sort(
            key=lambda x: (
                x.get("horas_esperadas", 0.0),
                x.get("horas_registradas", 0.0),
                x.get("sucursal_nombre", ""),
                x.get("horario_nombre", ""),
            ),
            reverse=True,
        )
        return items[:20]

    return _finalize(by_plantilla), _finalize(by_sucursal, with_templates=True)


def _dashboard_metrics():
    empresa_id = _parse_optional_int(request.args.get("empresa_id"))
    sucursal_id = _parse_optional_int(request.args.get("sucursal_id"))
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
        "legajo_eventos_total": 0,
        "legajo_eventos_mes": 0,
        "legajo_eventos_vigentes": 0,
        "legajo_eventos_anulados_mes": 0,
        "resumen_asistencias_mes": 0,
        "resumen_ausentes_mes": 0,
        "resumen_tardes_mes": 0,
        "resumen_ausentismo_mes_pct": 0.0,
        "global_asistencias_mes": 0,
        "global_ausentes_mes": 0,
        "global_ausentismo_mes_pct": 0.0,
        "global_horas_registradas_mes": 0.0,
        "global_horas_esperadas_mes": 0.0,
        "global_desvio_horas_mes": 0.0,
        "global_cumplimiento_horas_mes_pct": 0.0,
        "scope_kind": "general",
        "scope_label": "General",
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
        "resumen_sucursal_mes": [],
        "vacaciones_proximas_detalle": [],
        "vacaciones_top_dias_anio": [],
        "horas_por_plantilla_mes": [],
        "horas_por_sucursal_mes": [],
    }
    recent_events = []

    db = get_db()
    cursor = db.cursor()
    dict_cursor = None
    try:
        scope_where = []
        scope_params = []
        if empresa_id:
            scope_where.append("e.empresa_id = %s")
            scope_params.append(int(empresa_id))
        if sucursal_id:
            scope_where.append("e.sucursal_id = %s")
            scope_params.append(int(sucursal_id))
        scope_sql = (" AND " + " AND ".join(scope_where)) if scope_where else ""

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
        stats["legajo_eventos_total"] = _safe_count(
            cursor,
            f"""
            SELECT COUNT(*)
            FROM legajo_eventos le
            JOIN empleados e ON e.id = le.empleado_id
            WHERE 1 = 1
            {scope_sql}
            """,
            tuple(scope_params),
        )
        stats["legajo_eventos_mes"] = _safe_count(
            cursor,
            f"""
            SELECT COUNT(*)
            FROM legajo_eventos le
            JOIN empleados e ON e.id = le.empleado_id
            WHERE le.fecha_evento BETWEEN %s AND %s
            {scope_sql}
            """,
            (month_start, today, *scope_params),
        )
        stats["legajo_eventos_vigentes"] = _safe_count(
            cursor,
            f"""
            SELECT COUNT(*)
            FROM legajo_eventos le
            JOIN empleados e ON e.id = le.empleado_id
            WHERE le.estado = 'vigente'
            {scope_sql}
            """,
            tuple(scope_params),
        )
        stats["legajo_eventos_anulados_mes"] = _safe_count(
            cursor,
            f"""
            SELECT COUNT(*)
            FROM legajo_eventos le
            JOIN empleados e ON e.id = le.empleado_id
            WHERE le.fecha_evento BETWEEN %s AND %s
              AND le.estado = 'anulado'
            {scope_sql}
            """,
            (month_start, today, *scope_params),
        )
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
        resumen_cursor = db.cursor(dictionary=True)
        try:
            resumen_rows = _safe_fetchall(
                resumen_cursor,
                f"""
                SELECT
                    COUNT(*) AS asistencias_mes,
                    SUM(CASE WHEN a.estado = 'ausente' THEN 1 ELSE 0 END) AS ausentes_mes,
                    SUM(CASE WHEN a.estado = 'tarde' THEN 1 ELSE 0 END) AS tardes_mes
                FROM asistencias a
                JOIN empleados e ON e.id = a.empleado_id
                WHERE a.fecha BETWEEN %s AND %s
                {scope_sql}
                """,
                (month_start, today, *scope_params),
            )
        finally:
            resumen_cursor.close()
        resumen = resumen_rows[0] if resumen_rows else {}
        stats["resumen_asistencias_mes"] = _to_int(resumen.get("asistencias_mes"))
        stats["resumen_ausentes_mes"] = _to_int(resumen.get("ausentes_mes"))
        stats["resumen_tardes_mes"] = _to_int(resumen.get("tardes_mes"))
        if stats["resumen_asistencias_mes"] > 0:
            stats["resumen_ausentismo_mes_pct"] = round(
                (stats["resumen_ausentes_mes"] * 100.0) / stats["resumen_asistencias_mes"],
                1,
            )
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

        def _calc_hours_scope_summary(scope_empresa_id: int | None = None, scope_sucursal_id: int | None = None):
            minutos_esperados, employee_ids, expected_by_employee_day = _calc_expected_minutes_from_planillas(
                db,
                today_dt.replace(day=1),
                today_dt,
                empresa_id=scope_empresa_id,
                sucursal_id=scope_sucursal_id,
            )
            if employee_ids:
                registered_by_employee_day = _calc_registered_minutes_map_for_employees(
                    db,
                    month_start,
                    today,
                    employee_ids,
                )
                minutos_registrados = int(sum(registered_by_employee_day.values()))
            else:
                registered_by_employee_day = {}
                raw_where = []
                raw_params = [month_start, today]
                if scope_empresa_id:
                    raw_where.append("e.empresa_id = %s")
                    raw_params.append(int(scope_empresa_id))
                if scope_sucursal_id:
                    raw_where.append("e.sucursal_id = %s")
                    raw_params.append(int(scope_sucursal_id))
                raw_scope_sql = (" AND " + " AND ".join(raw_where)) if raw_where else ""
                minutos_registrados = _safe_count(
                    cursor,
                    f"""
                    SELECT COALESCE(SUM(GREATEST(TIMESTAMPDIFF(MINUTE, a.hora_entrada, a.hora_salida), 0)), 0)
                    FROM asistencias a
                    JOIN empleados e ON e.id = a.empleado_id
                    WHERE a.fecha BETWEEN %s AND %s
                      AND a.hora_entrada IS NOT NULL
                      AND a.hora_salida IS NOT NULL
                      {raw_scope_sql}
                    """,
                    tuple(raw_params),
                )
            horas_por_plantilla, horas_por_sucursal = _build_hours_breakdowns(
                expected_by_employee_day,
                registered_by_employee_day,
            )
            asig_where = []
            asig_params = [today, month_start]
            if scope_empresa_id:
                asig_where.append("e.empresa_id = %s")
                asig_params.append(int(scope_empresa_id))
            if scope_sucursal_id:
                asig_where.append("e.sucursal_id = %s")
                asig_params.append(int(scope_sucursal_id))
            asig_scope_sql = (" AND " + " AND ".join(asig_where)) if asig_where else ""
            asignaciones_con_planilla = _safe_count(
                cursor,
                f"""
                SELECT COUNT(*)
                FROM empleado_horarios eh
                JOIN empleados e ON e.id = eh.empleado_id
                WHERE eh.fecha_desde <= %s
                  AND (eh.fecha_hasta IS NULL OR eh.fecha_hasta >= %s)
                  {asig_scope_sql}
                """,
                tuple(asig_params),
            )
            horas_registradas = round(minutos_registrados / 60.0, 1)
            horas_esperadas = round(minutos_esperados / 60.0, 1)
            cumplimiento_horas_pct = (
                round((minutos_registrados * 100.0) / minutos_esperados, 1)
                if minutos_esperados > 0
                else 0.0
            )
            return {
                "minutos_registrados": int(minutos_registrados or 0),
                "minutos_esperados": int(minutos_esperados or 0),
                "horas_registradas": horas_registradas,
                "horas_esperadas": horas_esperadas,
                "desvio_horas": round(horas_registradas - horas_esperadas, 1),
                "cumplimiento_horas_pct": cumplimiento_horas_pct,
                "empleados_con_planilla": len(employee_ids),
                "asignaciones_con_planilla": int(asignaciones_con_planilla or 0),
                "horas_por_plantilla": horas_por_plantilla,
                "horas_por_sucursal": horas_por_sucursal,
            }

        global_hours = _calc_hours_scope_summary()
        stats["global_horas_registradas_mes"] = global_hours["horas_registradas"]
        stats["global_horas_esperadas_mes"] = global_hours["horas_esperadas"]
        stats["global_desvio_horas_mes"] = global_hours["desvio_horas"]
        stats["global_cumplimiento_horas_mes_pct"] = global_hours["cumplimiento_horas_pct"]

        stats["horas_registradas_mes"] = global_hours["horas_registradas"]
        stats["horas_esperadas_mes"] = global_hours["horas_esperadas"]
        stats["desvio_horas_mes"] = global_hours["desvio_horas"]
        stats["cumplimiento_horas_mes_pct"] = global_hours["cumplimiento_horas_pct"]
        stats["empleados_con_planilla_mes"] = global_hours["empleados_con_planilla"]
        stats["asignaciones_con_planilla_mes"] = global_hours["asignaciones_con_planilla"]
        charts["horas_por_plantilla_mes"] = global_hours["horas_por_plantilla"]
        charts["horas_por_sucursal_mes"] = global_hours["horas_por_sucursal"]

        if global_hours["minutos_esperados"] <= 0:
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

        stats["global_asistencias_mes"] = stats["asistencias_mes"]
        stats["global_ausentes_mes"] = stats["ausentes_mes"]
        stats["global_ausentismo_mes_pct"] = stats["ausentismo_mes_pct"]
        stats["scope_kind"] = "general"
        stats["scope_label"] = "General (todas las empresas y sucursales)"

        if scope_params:
            scoped_params = tuple(scope_params)
            stats["scope_kind"] = "sucursal" if sucursal_id else "empresa"
            if sucursal_id:
                stats["scope_label"] = f"Sucursal #{int(sucursal_id)}"
            else:
                stats["scope_label"] = f"Empresa #{int(empresa_id)}"

            stats["empleados_activos"] = _safe_count(
                cursor,
                f"""
                SELECT COUNT(*)
                FROM empleados e
                WHERE e.activo = 1
                {scope_sql}
                """,
                scoped_params,
            )
            stats["empleados_con_fichada_hoy"] = _safe_count(
                cursor,
                f"""
                SELECT COUNT(DISTINCT a.empleado_id)
                FROM asistencias a
                JOIN empleados e ON e.id = a.empleado_id
                WHERE 1 = 1
                {scope_sql}
                  AND a.fecha = %s
                  AND (a.hora_entrada IS NOT NULL OR a.hora_salida IS NOT NULL)
                """,
                (*scoped_params, today),
            )
            if stats["empleados_activos"] > 0:
                stats["presentismo_hoy_pct"] = round(
                    (stats["empleados_con_fichada_hoy"] * 100.0) / stats["empleados_activos"],
                    1,
                )
            else:
                stats["presentismo_hoy_pct"] = 0.0

            stats["asistencias_hoy"] = _safe_count(
                cursor,
                f"""
                SELECT COUNT(*)
                FROM asistencias a
                JOIN empleados e ON e.id = a.empleado_id
                WHERE 1 = 1
                {scope_sql}
                  AND a.fecha = %s
                """,
                (*scoped_params, today),
            )
            stats["tardes_hoy"] = _safe_count(
                cursor,
                f"""
                SELECT COUNT(*)
                FROM asistencias a
                JOIN empleados e ON e.id = a.empleado_id
                WHERE 1 = 1
                {scope_sql}
                  AND a.fecha = %s
                  AND a.estado = 'tarde'
                """,
                (*scoped_params, today),
            )
            stats["ausentes_hoy"] = _safe_count(
                cursor,
                f"""
                SELECT COUNT(*)
                FROM asistencias a
                JOIN empleados e ON e.id = a.empleado_id
                WHERE 1 = 1
                {scope_sql}
                  AND a.fecha = %s
                  AND a.estado = 'ausente'
                """,
                (*scoped_params, today),
            )
            stats["excepciones_hoy"] = _safe_count(
                cursor,
                f"""
                SELECT COUNT(*)
                FROM empleado_excepciones ex
                JOIN empleados e ON e.id = ex.empleado_id
                WHERE 1 = 1
                {scope_sql}
                  AND ex.fecha = %s
                """,
                (*scoped_params, today),
            )
            stats["asignaciones_vigentes"] = _safe_count(
                cursor,
                f"""
                SELECT COUNT(*)
                FROM empleado_horarios eh
                JOIN empleados e ON e.id = eh.empleado_id
                WHERE 1 = 1
                {scope_sql}
                  AND eh.fecha_desde <= %s
                  AND (eh.fecha_hasta IS NULL OR eh.fecha_hasta >= %s)
                """,
                (*scoped_params, today, today),
            )

            stats["asistencias_30d"] = _safe_count(
                cursor,
                f"""
                SELECT COUNT(*)
                FROM asistencias a
                JOIN empleados e ON e.id = a.empleado_id
                WHERE 1 = 1
                {scope_sql}
                  AND a.fecha BETWEEN %s AND %s
                """,
                (*scoped_params, since_30, today),
            )
            stats["tardes_30d"] = _safe_count(
                cursor,
                f"""
                SELECT COUNT(*)
                FROM asistencias a
                JOIN empleados e ON e.id = a.empleado_id
                WHERE 1 = 1
                {scope_sql}
                  AND a.fecha BETWEEN %s AND %s
                  AND a.estado = 'tarde'
                """,
                (*scoped_params, since_30, today),
            )
            stats["ausentes_30d"] = _safe_count(
                cursor,
                f"""
                SELECT COUNT(*)
                FROM asistencias a
                JOIN empleados e ON e.id = a.empleado_id
                WHERE 1 = 1
                {scope_sql}
                  AND a.fecha BETWEEN %s AND %s
                  AND a.estado = 'ausente'
                """,
                (*scoped_params, since_30, today),
            )
            stats["fichadas_mes"] = _safe_count(
                cursor,
                f"""
                SELECT COUNT(*)
                FROM asistencias a
                JOIN empleados e ON e.id = a.empleado_id
                WHERE 1 = 1
                {scope_sql}
                  AND a.fecha BETWEEN %s AND %s
                  AND (a.hora_entrada IS NOT NULL OR a.hora_salida IS NOT NULL)
                """,
                (*scoped_params, month_start, today),
            )
            stats["ok_fichadas_mes"] = _safe_count(
                cursor,
                f"""
                SELECT COUNT(*)
                FROM asistencias a
                JOIN empleados e ON e.id = a.empleado_id
                WHERE 1 = 1
                {scope_sql}
                  AND a.fecha BETWEEN %s AND %s
                  AND (a.hora_entrada IS NOT NULL OR a.hora_salida IS NOT NULL)
                  AND a.estado = 'ok'
                """,
                (*scoped_params, month_start, today),
            )
            stats["puntualidad_mes_pct"] = (
                round((stats["ok_fichadas_mes"] * 100.0) / stats["fichadas_mes"], 1)
                if stats["fichadas_mes"] > 0
                else 0.0
            )
            stats["asistencias_mes"] = _safe_count(
                cursor,
                f"""
                SELECT COUNT(*)
                FROM asistencias a
                JOIN empleados e ON e.id = a.empleado_id
                WHERE 1 = 1
                {scope_sql}
                  AND a.fecha BETWEEN %s AND %s
                """,
                (*scoped_params, month_start, today),
            )
            stats["tardes_mes"] = _safe_count(
                cursor,
                f"""
                SELECT COUNT(*)
                FROM asistencias a
                JOIN empleados e ON e.id = a.empleado_id
                WHERE 1 = 1
                {scope_sql}
                  AND a.fecha BETWEEN %s AND %s
                  AND a.estado = 'tarde'
                """,
                (*scoped_params, month_start, today),
            )
            stats["ausentes_mes"] = _safe_count(
                cursor,
                f"""
                SELECT COUNT(*)
                FROM asistencias a
                JOIN empleados e ON e.id = a.empleado_id
                WHERE 1 = 1
                {scope_sql}
                  AND a.fecha BETWEEN %s AND %s
                  AND a.estado = 'ausente'
                """,
                (*scoped_params, month_start, today),
            )
            stats["ausentismo_mes_pct"] = (
                round((stats["ausentes_mes"] * 100.0) / stats["asistencias_mes"], 1)
                if stats["asistencias_mes"] > 0
                else 0.0
            )
            stats["ausentes_sin_justificacion_mes"] = _safe_count(
                cursor,
                f"""
                SELECT COUNT(*)
                FROM asistencias a
                JOIN empleados e ON e.id = a.empleado_id
                WHERE 1 = 1
                {scope_sql}
                  AND a.fecha BETWEEN %s AND %s
                  AND a.estado = 'ausente'
                  AND NOT EXISTS (
                      SELECT 1
                      FROM justificaciones j
                      WHERE j.asistencia_id = a.id
                        AND j.estado = 'aprobada'
                  )
                """,
                (*scoped_params, month_start, today),
            )
            stats["no_show_mes_pct"] = (
                round((stats["ausentes_sin_justificacion_mes"] * 100.0) / stats["ausentes_mes"], 1)
                if stats["ausentes_mes"] > 0
                else 0.0
            )

            stats["ausentes_trimestre"] = _safe_count(
                cursor,
                f"""
                SELECT COUNT(*)
                FROM asistencias a
                JOIN empleados e ON e.id = a.empleado_id
                WHERE 1 = 1
                {scope_sql}
                  AND a.fecha BETWEEN %s AND %s
                  AND a.estado = 'ausente'
                """,
                (*scoped_params, quarter_start, today),
            )
            stats["asistencias_anio"] = _safe_count(
                cursor,
                f"""
                SELECT COUNT(*)
                FROM asistencias a
                JOIN empleados e ON e.id = a.empleado_id
                WHERE 1 = 1
                {scope_sql}
                  AND a.fecha BETWEEN %s AND %s
                """,
                (*scoped_params, year_start, today),
            )
            stats["tardes_anio"] = _safe_count(
                cursor,
                f"""
                SELECT COUNT(*)
                FROM asistencias a
                JOIN empleados e ON e.id = a.empleado_id
                WHERE 1 = 1
                {scope_sql}
                  AND a.fecha BETWEEN %s AND %s
                  AND a.estado = 'tarde'
                """,
                (*scoped_params, year_start, today),
            )
            stats["ausentes_anio"] = _safe_count(
                cursor,
                f"""
                SELECT COUNT(*)
                FROM asistencias a
                JOIN empleados e ON e.id = a.empleado_id
                WHERE 1 = 1
                {scope_sql}
                  AND a.fecha BETWEEN %s AND %s
                  AND a.estado = 'ausente'
                """,
                (*scoped_params, year_start, today),
            )
            stats["ausentismo_anual_pct"] = (
                round((stats["ausentes_anio"] * 100.0) / stats["asistencias_anio"], 1)
                if stats["asistencias_anio"] > 0
                else 0.0
            )
            if stats["empleados_activos"] > 0:
                stats["frecuencia_ausencias_mes"] = round(stats["ausentes_mes"] / stats["empleados_activos"], 2)
                stats["frecuencia_ausencias_trimestre"] = round(
                    stats["ausentes_trimestre"] / stats["empleados_activos"],
                    2,
                )
            else:
                stats["frecuencia_ausencias_mes"] = 0.0
                stats["frecuencia_ausencias_trimestre"] = 0.0

            stats["jornadas_completas_mes"] = _safe_count(
                cursor,
                f"""
                SELECT COUNT(*)
                FROM asistencias a
                JOIN empleados e ON e.id = a.empleado_id
                WHERE 1 = 1
                {scope_sql}
                  AND a.fecha BETWEEN %s AND %s
                  AND a.hora_entrada IS NOT NULL
                  AND a.hora_salida IS NOT NULL
                """,
                (*scoped_params, month_start, today),
            )
            stats["cumplimiento_jornada_mes_pct"] = (
                round((stats["jornadas_completas_mes"] * 100.0) / stats["fichadas_mes"], 1)
                if stats["fichadas_mes"] > 0
                else 0.0
            )
            stats["salida_anticipada_mes"] = _safe_count(
                cursor,
                f"""
                SELECT COUNT(*)
                FROM asistencias a
                JOIN empleados e ON e.id = a.empleado_id
                WHERE 1 = 1
                {scope_sql}
                  AND a.fecha BETWEEN %s AND %s
                  AND a.estado = 'salida_anticipada'
                """,
                (*scoped_params, month_start, today),
            )
            stats["tasa_salida_anticipada_mes_pct"] = (
                round((stats["salida_anticipada_mes"] * 100.0) / stats["fichadas_mes"], 1)
                if stats["fichadas_mes"] > 0
                else 0.0
            )

            stats["justificaciones_mes_total"] = _safe_count(
                cursor,
                f"""
                SELECT COUNT(*)
                FROM justificaciones j
                JOIN asistencias a ON a.id = j.asistencia_id
                JOIN empleados e ON e.id = a.empleado_id
                WHERE 1 = 1
                {scope_sql}
                  AND DATE(j.created_at) BETWEEN %s AND %s
                """,
                (*scoped_params, month_start, today),
            )
            stats["justificaciones_mes_pendientes"] = _safe_count(
                cursor,
                f"""
                SELECT COUNT(*)
                FROM justificaciones j
                JOIN asistencias a ON a.id = j.asistencia_id
                JOIN empleados e ON e.id = a.empleado_id
                WHERE 1 = 1
                {scope_sql}
                  AND DATE(j.created_at) BETWEEN %s AND %s
                  AND LOWER(COALESCE(j.estado, 'pendiente')) = 'pendiente'
                """,
                (*scoped_params, month_start, today),
            )
            stats["justificaciones_mes_aprobadas"] = _safe_count(
                cursor,
                f"""
                SELECT COUNT(*)
                FROM justificaciones j
                JOIN asistencias a ON a.id = j.asistencia_id
                JOIN empleados e ON e.id = a.empleado_id
                WHERE 1 = 1
                {scope_sql}
                  AND DATE(j.created_at) BETWEEN %s AND %s
                  AND LOWER(COALESCE(j.estado, 'pendiente')) = 'aprobada'
                """,
                (*scoped_params, month_start, today),
            )
            stats["justificaciones_mes_rechazadas"] = _safe_count(
                cursor,
                f"""
                SELECT COUNT(*)
                FROM justificaciones j
                JOIN asistencias a ON a.id = j.asistencia_id
                JOIN empleados e ON e.id = a.empleado_id
                WHERE 1 = 1
                {scope_sql}
                  AND DATE(j.created_at) BETWEEN %s AND %s
                  AND LOWER(COALESCE(j.estado, 'pendiente')) = 'rechazada'
                """,
                (*scoped_params, month_start, today),
            )
            stats["justificaciones_pendientes_total"] = _safe_count(
                cursor,
                f"""
                SELECT COUNT(*)
                FROM justificaciones j
                JOIN asistencias a ON a.id = j.asistencia_id
                JOIN empleados e ON e.id = a.empleado_id
                WHERE 1 = 1
                {scope_sql}
                  AND LOWER(COALESCE(j.estado, 'pendiente')) = 'pendiente'
                """,
                scoped_params,
            )
            stats["tasa_aprobacion_justificaciones_mes_pct"] = (
                round((stats["justificaciones_mes_aprobadas"] * 100.0) / stats["justificaciones_mes_total"], 1)
                if stats["justificaciones_mes_total"] > 0
                else 0.0
            )

            stats["vacaciones_en_curso_hoy"] = _safe_count(
                cursor,
                f"""
                SELECT COUNT(*)
                FROM vacaciones v
                JOIN empleados e ON e.id = v.empleado_id
                WHERE 1 = 1
                {scope_sql}
                  AND v.fecha_desde <= %s
                  AND v.fecha_hasta >= %s
                """,
                (*scoped_params, today, today),
            )
            stats["vacaciones_proximas_30d"] = _safe_count(
                cursor,
                f"""
                SELECT COUNT(*)
                FROM vacaciones v
                JOIN empleados e ON e.id = v.empleado_id
                WHERE 1 = 1
                {scope_sql}
                  AND v.fecha_desde > %s
                  AND v.fecha_desde <= %s
                """,
                (*scoped_params, today, next_30),
            )
            stats["vacaciones_dias_mes"] = _safe_count(
                cursor,
                f"""
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
                JOIN empleados e ON e.id = v.empleado_id
                WHERE 1 = 1
                {scope_sql}
                  AND v.fecha_desde <= %s
                  AND v.fecha_hasta >= %s
                """,
                (*scoped_params, today, month_start, today, month_start),
            )
            stats["vacaciones_dias_anio"] = _safe_count(
                cursor,
                f"""
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
                JOIN empleados e ON e.id = v.empleado_id
                WHERE 1 = 1
                {scope_sql}
                  AND v.fecha_desde <= %s
                  AND v.fecha_hasta >= %s
                """,
                (*scoped_params, today, year_start, today, year_start),
            )

            scoped_hours = _calc_hours_scope_summary(empresa_id, sucursal_id)
            stats["horas_registradas_mes"] = scoped_hours["horas_registradas"]
            stats["horas_esperadas_mes"] = scoped_hours["horas_esperadas"]
            stats["desvio_horas_mes"] = scoped_hours["desvio_horas"]
            stats["cumplimiento_horas_mes_pct"] = scoped_hours["cumplimiento_horas_pct"]
            stats["empleados_con_planilla_mes"] = scoped_hours["empleados_con_planilla"]
            stats["asignaciones_con_planilla_mes"] = scoped_hours["asignaciones_con_planilla"]
            charts["horas_por_plantilla_mes"] = scoped_hours["horas_por_plantilla"]
            charts["horas_por_sucursal_mes"] = scoped_hours["horas_por_sucursal"]

        current_app.logger.info(
            "dashboard_hours_metrics",
            extra={
                "extra": {
                    "month_start": month_start,
                    "today": today,
                    "scope_kind": stats["scope_kind"],
                    "scope_label": stats["scope_label"],
                    "horas_registradas_mes": stats["horas_registradas_mes"],
                    "horas_esperadas_mes": stats["horas_esperadas_mes"],
                    "desvio_horas_mes": stats["desvio_horas_mes"],
                    "cumplimiento_horas_mes_pct": stats["cumplimiento_horas_mes_pct"],
                    "empleados_con_planilla_mes": stats["empleados_con_planilla_mes"],
                    "asignaciones_vigentes_mes": stats["asignaciones_con_planilla_mes"],
                    "global_horas_registradas_mes": stats["global_horas_registradas_mes"],
                    "global_horas_esperadas_mes": stats["global_horas_esperadas_mes"],
                }
            },
        )

        dict_cursor = db.cursor(dictionary=True)

        lead_row = _safe_fetchall(
            dict_cursor,
            f"""
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
            JOIN empleados e ON e.id = a.empleado_id
            LEFT JOIN (
                SELECT asistencia_id, MIN(created_at) AS first_created_at
                FROM justificaciones
                WHERE asistencia_id IS NOT NULL
                GROUP BY asistencia_id
            ) j ON j.asistencia_id = a.id
            WHERE a.fecha BETWEEN %s AND %s
              AND a.estado IN ('ausente', 'tarde', 'salida_anticipada')
              {scope_sql}
            """,
            (month_start, today, *scope_params),
        )
        lead_data = lead_row[0] if lead_row else {}
        incidentes_mes = _to_int(lead_data.get("incidentes"))
        stats["incidentes_sin_regularizar_mes"] = _to_int(lead_data.get("sin_regularizar"))
        stats["incidentes_regularizados_mes"] = max(0, incidentes_mes - stats["incidentes_sin_regularizar_mes"])
        stats["lead_time_regularizacion_horas_mes"] = round(_to_float(lead_data.get("lead_horas")), 1)
        just_rows = _safe_fetchall(
            dict_cursor,
            f"""
            SELECT
                LOWER(COALESCE(j.estado, 'pendiente')) AS estado,
                COUNT(*) AS total
            FROM justificaciones j
            JOIN asistencias a ON a.id = j.asistencia_id
            JOIN empleados e ON e.id = a.empleado_id
            WHERE DATE(j.created_at) BETWEEN %s AND %s
              {scope_sql}
            GROUP BY LOWER(COALESCE(j.estado, 'pendiente'))
            """,
            (month_start, today, *scope_params),
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
            f"""
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
              {scope_sql}
            ORDER BY v.fecha_desde ASC, e.apellido ASC, e.nombre ASC
            LIMIT 12
            """,
            (today, next_30, *scope_params),
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
            f"""
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
              {scope_sql}
            GROUP BY e.id, e.apellido, e.nombre, emp.razon_social
            HAVING dias > 0
            ORDER BY dias DESC, e.apellido ASC, e.nombre ASC
            LIMIT 10
            """,
            (today, year_start, today, year_start, *scope_params),
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
            f"""
            SELECT
                a.fecha,
                COUNT(*) AS asistencias,
                SUM(CASE WHEN a.estado = 'tarde' THEN 1 ELSE 0 END) AS tardes,
                SUM(CASE WHEN a.estado = 'ausente' THEN 1 ELSE 0 END) AS ausentes
            FROM asistencias a
            JOIN empleados e ON e.id = a.empleado_id
            WHERE a.fecha BETWEEN %s AND %s
              {scope_sql}
            GROUP BY a.fecha
            ORDER BY a.fecha ASC
            """,
            (since_7, today, *scope_params),
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
            f"""
            SELECT COALESCE(a.estado, 'sin_estado') AS estado, COUNT(*) AS total
            FROM asistencias a
            JOIN empleados e ON e.id = a.empleado_id
            WHERE a.fecha BETWEEN %s AND %s
              {scope_sql}
            GROUP BY COALESCE(a.estado, 'sin_estado')
            """,
            (since_30, today, *scope_params),
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
            f"""
            SELECT
                emp.razon_social AS empresa,
                COUNT(*) AS total,
                SUM(CASE WHEN a.estado = 'ausente' THEN 1 ELSE 0 END) AS ausentes,
                SUM(CASE WHEN a.estado = 'tarde' THEN 1 ELSE 0 END) AS tardes
            FROM asistencias a
            JOIN empleados e ON e.id = a.empleado_id
            JOIN empresas emp ON emp.id = e.empresa_id
            WHERE a.fecha BETWEEN %s AND %s
              {scope_sql}
            GROUP BY emp.id, emp.razon_social
            ORDER BY ausentes DESC, tardes DESC, total DESC
            LIMIT 8
            """,
            (since_30, today, *scope_params),
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
            f"""
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
              {scope_sql}
            GROUP BY e.id, e.apellido, e.nombre, e.dni, emp.razon_social
            HAVING incidentes >= %s
            ORDER BY incidentes DESC, ausencias DESC, tardanzas DESC
            LIMIT 12
            """,
            (month_start, today, *scope_params, reincidencia_umbral),
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
            f"""
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
              {scope_sql}
            GROUP BY e.id, e.apellido, e.nombre, e.dni, emp.razon_social
            HAVING SUM(CASE WHEN a.estado = 'ausente' THEN 1 ELSE 0 END) > 0
            ORDER BY ausencias DESC, tardanzas DESC, total DESC
            LIMIT 12
            """,
            (year_start, today, *scope_params),
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
            f"""
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
              {scope_sql}
            ORDER BY a.empleado_id ASC, a.fecha DESC, a.id DESC
            """,
            (year_start, today, *scope_params),
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
                        "asistencias_mes": _to_int(row.get("asistencias_mes")),
                        "tardes_mes": _to_int(row.get("tardes_mes")),
                        "eventos_legajo_mes": _to_int(row.get("eventos_legajo_mes")),
                        "eventos_legajo_vigentes": _to_int(row.get("eventos_legajo_vigentes")),
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
            f"""
            SELECT
                emp.razon_social AS nombre,
                COALESCE(a.ausentes, 0) AS ausentes,
                COALESCE(d.dotacion, 0) AS dotacion
            FROM (
                SELECT e.empresa_id, COUNT(*) AS dotacion
                FROM empleados e
                WHERE e.activo = 1
                {scope_sql}
                GROUP BY e.empresa_id
            ) d
            JOIN empresas emp ON emp.id = d.empresa_id
            LEFT JOIN (
                SELECT e.empresa_id, COUNT(*) AS ausentes
                FROM asistencias a
                JOIN empleados e ON e.id = a.empleado_id
                WHERE a.fecha BETWEEN %s AND %s
                  AND a.estado = 'ausente'
                  {scope_sql}
                GROUP BY e.empresa_id
            ) a ON a.empresa_id = d.empresa_id
            WHERE COALESCE(d.dotacion, 0) > 0
            ORDER BY (COALESCE(a.ausentes, 0) / NULLIF(d.dotacion, 0)) DESC, COALESCE(a.ausentes, 0) DESC
            LIMIT 20
            """,
            (*scope_params, month_start, today, *scope_params),
        )
        charts["ausentismo_rank_empresa"] = _normalize_rank(aus_emp_rows)

        aus_sector_rows = _safe_fetchall(
            dict_cursor,
            f"""
            SELECT
                COALESCE(sec.nombre, 'Sin sector') AS nombre,
                COALESCE(a.ausentes, 0) AS ausentes,
                COALESCE(d.dotacion, 0) AS dotacion
            FROM (
                SELECT COALESCE(e.sector_id, 0) AS gid, COUNT(*) AS dotacion
                FROM empleados e
                WHERE e.activo = 1
                {scope_sql}
                GROUP BY COALESCE(e.sector_id, 0)
            ) d
            LEFT JOIN (
                SELECT COALESCE(e.sector_id, 0) AS gid, COUNT(*) AS ausentes
                FROM asistencias a
                JOIN empleados e ON e.id = a.empleado_id
                WHERE a.fecha BETWEEN %s AND %s
                  AND a.estado = 'ausente'
                  {scope_sql}
                GROUP BY COALESCE(e.sector_id, 0)
            ) a ON a.gid = d.gid
            LEFT JOIN sectores sec ON sec.id = NULLIF(d.gid, 0)
            ORDER BY (COALESCE(a.ausentes, 0) / NULLIF(d.dotacion, 0)) DESC, COALESCE(a.ausentes, 0) DESC
            LIMIT 20
            """,
            (*scope_params, month_start, today, *scope_params),
        )
        charts["ausentismo_rank_sector"] = _normalize_rank(aus_sector_rows)

        aus_sucursal_rows = _safe_fetchall(
            dict_cursor,
            f"""
            SELECT
                COALESCE(suc.nombre, 'Sin sucursal') AS nombre,
                COALESCE(a.ausentes, 0) AS ausentes,
                COALESCE(d.dotacion, 0) AS dotacion,
                COALESCE(a.asistencias_mes, 0) AS asistencias_mes,
                COALESCE(a.tardes_mes, 0) AS tardes_mes,
                COALESCE(le.eventos_legajo_mes, 0) AS eventos_legajo_mes,
                COALESCE(le.eventos_legajo_vigentes, 0) AS eventos_legajo_vigentes
            FROM (
                SELECT COALESCE(e.sucursal_id, 0) AS gid, COUNT(*) AS dotacion
                FROM empleados e
                WHERE e.activo = 1
                {scope_sql}
                GROUP BY COALESCE(e.sucursal_id, 0)
            ) d
            LEFT JOIN (
                SELECT
                    COALESCE(e.sucursal_id, 0) AS gid,
                    COUNT(*) AS asistencias_mes,
                    SUM(CASE WHEN a.estado = 'ausente' THEN 1 ELSE 0 END) AS ausentes,
                    SUM(CASE WHEN a.estado = 'tarde' THEN 1 ELSE 0 END) AS tardes_mes
                FROM asistencias a
                JOIN empleados e ON e.id = a.empleado_id
                WHERE a.fecha BETWEEN %s AND %s
                {scope_sql}
                GROUP BY COALESCE(e.sucursal_id, 0)
            ) a ON a.gid = d.gid
            LEFT JOIN (
                SELECT
                    COALESCE(e.sucursal_id, 0) AS gid,
                    COUNT(*) AS eventos_legajo_mes,
                    SUM(CASE WHEN le.estado = 'vigente' THEN 1 ELSE 0 END) AS eventos_legajo_vigentes
                FROM legajo_eventos le
                JOIN empleados e ON e.id = le.empleado_id
                WHERE le.fecha_evento BETWEEN %s AND %s
                {scope_sql}
                GROUP BY COALESCE(e.sucursal_id, 0)
            ) le ON le.gid = d.gid
            LEFT JOIN sucursales suc ON suc.id = NULLIF(d.gid, 0)
            ORDER BY (COALESCE(a.ausentes, 0) / NULLIF(d.dotacion, 0)) DESC, COALESCE(a.ausentes, 0) DESC
            LIMIT 20
            """,
            (*scope_params, month_start, today, *scope_params, month_start, today, *scope_params),
        )
        charts["ausentismo_rank_sucursal"] = _normalize_rank(aus_sucursal_rows)
        resumen_sucursal = []
        for row in aus_sucursal_rows:
            nombre = str(row.get("nombre") or "Sin sucursal").strip()
            dotacion = _to_int(row.get("dotacion"))
            asistencias_mes = _to_int(row.get("asistencias_mes"))
            ausentes_mes = _to_int(row.get("ausentes"))
            tardes_mes = _to_int(row.get("tardes_mes"))
            eventos_legajo_mes = _to_int(row.get("eventos_legajo_mes"))
            eventos_legajo_vigentes = _to_int(row.get("eventos_legajo_vigentes"))
            indice_ausencias_por_empleado = round((ausentes_mes / dotacion), 2) if dotacion > 0 else 0.0
            tasa_pct = round((ausentes_mes * 100.0) / (dotacion * month_days_elapsed), 2) if dotacion > 0 else 0.0
            ausentismo_pct = round((ausentes_mes * 100.0) / asistencias_mes, 1) if asistencias_mes > 0 else 0.0
            eventos_por_empleado = round((eventos_legajo_mes / dotacion), 2) if dotacion > 0 else 0.0
            resumen_sucursal.append(
                {
                    "nombre": nombre,
                    "dotacion": dotacion,
                    "asistencias_mes": asistencias_mes,
                    "ausentes_mes": ausentes_mes,
                    "tardes_mes": tardes_mes,
                    "ausentismo_pct": ausentismo_pct,
                    "eventos_legajo_mes": eventos_legajo_mes,
                    "eventos_legajo_vigentes": eventos_legajo_vigentes,
                    "eventos_por_empleado": eventos_por_empleado,
                    "indice_ausencias_por_empleado": indice_ausencias_por_empleado,
                    "tasa_pct": tasa_pct,
                }
            )
        resumen_sucursal.sort(
            key=lambda x: (
                x.get("ausentismo_pct", 0.0),
                x.get("eventos_legajo_mes", 0),
                x.get("nombre", ""),
            ),
            reverse=True,
        )
        charts["resumen_sucursal_mes"] = resumen_sucursal[:12]

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
