import datetime as _dt

from extensions import get_db


def _to_int(value):
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _pct(part: int, total: int):
    if total <= 0:
        return 0.0
    return round((part * 100.0) / total, 1)


def _safe_fetchone(cursor, query, params=()):
    try:
        cursor.execute(query, params)
        return cursor.fetchone() or {}
    except Exception:
        return {}


def _safe_fetchall(cursor, query, params=()):
    try:
        cursor.execute(query, params)
        return cursor.fetchall() or []
    except Exception:
        return []


def _count_workdays(desde_str, hasta_str):
    """Count Mon-Fri days in [desde, hasta] inclusive."""
    try:
        desde = _dt.date.fromisoformat(str(desde_str))
        hasta = _dt.date.fromisoformat(str(hasta_str))
    except (ValueError, TypeError):
        return 0
    if hasta < desde:
        return 0
    count = 0
    current = desde
    while current <= hasta:
        if current.weekday() < 5:  # 0=Mon ... 4=Fri
            count += 1
        current += _dt.timedelta(days=1)
    return count


def get_by_empleado(empleado_id: int, fecha_desde: str, fecha_hasta: str):
    db = get_db()
    cursor = db.cursor(dictionary=True)
    try:
        resumen_row = _safe_fetchone(
            cursor,
            """
            SELECT
                COUNT(*) AS registros,
                SUM(CASE WHEN COALESCE(estado, '') = 'ok' THEN 1 ELSE 0 END) AS ok_total,
                SUM(CASE WHEN estado = 'tarde' THEN 1 ELSE 0 END) AS tarde_total,
                SUM(CASE WHEN estado = 'ausente' THEN 1 ELSE 0 END) AS ausente_total,
                SUM(CASE WHEN estado = 'salida_anticipada' THEN 1 ELSE 0 END) AS salida_anticipada_total,
                SUM(CASE WHEN estado IS NULL OR estado = '' THEN 1 ELSE 0 END) AS sin_estado_total,
                SUM(CASE WHEN hora_entrada IS NOT NULL AND hora_salida IS NOT NULL THEN 1 ELSE 0 END) AS jornadas_completas,
                SUM(CASE WHEN hora_entrada IS NOT NULL OR hora_salida IS NOT NULL THEN 1 ELSE 0 END) AS jornadas_con_marca
            FROM asistencias
            WHERE empleado_id = %s
              AND fecha BETWEEN %s AND %s
            """,
            (empleado_id, fecha_desde, fecha_hasta),
        )

        ausentes_sin_justif_row = _safe_fetchone(
            cursor,
            """
            SELECT COUNT(*) AS ausentes_sin_justificacion
            FROM asistencias a
            WHERE a.empleado_id = %s
              AND a.fecha BETWEEN %s AND %s
              AND a.estado = 'ausente'
              AND NOT EXISTS (
                  SELECT 1
                  FROM justificaciones j
                  WHERE j.asistencia_id = a.id
                    AND LOWER(COALESCE(j.estado, '')) = 'aprobada'
              )
            """,
            (empleado_id, fecha_desde, fecha_hasta),
        )

        just_row = _safe_fetchone(
            cursor,
            """
            SELECT
                COUNT(*) AS total,
                SUM(CASE WHEN LOWER(COALESCE(j.estado, 'pendiente')) = 'pendiente' THEN 1 ELSE 0 END) AS pendientes,
                SUM(CASE WHEN LOWER(COALESCE(j.estado, 'pendiente')) = 'aprobada' THEN 1 ELSE 0 END) AS aprobadas,
                SUM(CASE WHEN LOWER(COALESCE(j.estado, 'pendiente')) = 'rechazada' THEN 1 ELSE 0 END) AS rechazadas
            FROM justificaciones j
            LEFT JOIN asistencias a ON a.id = j.asistencia_id
            WHERE j.empleado_id = %s
              AND (
                  (a.id IS NOT NULL AND a.fecha BETWEEN %s AND %s)
                  OR (a.id IS NULL AND DATE(j.created_at) BETWEEN %s AND %s)
              )
            """,
            (empleado_id, fecha_desde, fecha_hasta, fecha_desde, fecha_hasta),
        )

        vacaciones_row = _safe_fetchone(
            cursor,
            """
            SELECT
                COUNT(*) AS eventos,
                COALESCE(
                    SUM(
                        GREATEST(
                            0,
                            DATEDIFF(LEAST(v.fecha_hasta, %s), GREATEST(v.fecha_desde, %s)) + 1
                        )
                    ),
                    0
                ) AS dias
            FROM vacaciones v
            WHERE v.empleado_id = %s
              AND v.fecha_desde <= %s
              AND v.fecha_hasta >= %s
            """,
            (fecha_hasta, fecha_desde, empleado_id, fecha_hasta, fecha_desde),
        )

        diario_rows = _safe_fetchall(
            cursor,
            """
            SELECT
                fecha,
                COUNT(*) AS registros,
                SUM(CASE WHEN COALESCE(estado, '') = 'ok' THEN 1 ELSE 0 END) AS ok_total,
                SUM(CASE WHEN estado = 'tarde' THEN 1 ELSE 0 END) AS tarde_total,
                SUM(CASE WHEN estado = 'ausente' THEN 1 ELSE 0 END) AS ausente_total,
                SUM(CASE WHEN estado = 'salida_anticipada' THEN 1 ELSE 0 END) AS salida_anticipada_total
            FROM asistencias
            WHERE empleado_id = %s
              AND fecha BETWEEN %s AND %s
            GROUP BY fecha
            ORDER BY fecha ASC
            """,
            (empleado_id, fecha_desde, fecha_hasta),
        )

        gps_row = _safe_fetchone(
            cursor,
            """
            SELECT
                SUM(CASE WHEN hora_entrada IS NOT NULL AND gps_ok_entrada = 0 THEN 1 ELSE 0 END) +
                SUM(CASE WHEN hora_salida IS NOT NULL AND gps_ok_salida = 0 THEN 1 ELSE 0 END) AS gps_incidencias
            FROM asistencias
            WHERE empleado_id = %s AND fecha BETWEEN %s AND %s
            """,
            (empleado_id, fecha_desde, fecha_hasta),
        )

        horas_row = _safe_fetchone(
            cursor,
            """
            SELECT
                COALESCE(AVG(TIMESTAMPDIFF(SECOND, hora_entrada, hora_salida)) / 3600.0, 0) AS horas_promedio,
                COALESCE(SUM(TIMESTAMPDIFF(SECOND, hora_entrada, hora_salida)) / 3600.0, 0) AS horas_totales
            FROM asistencias
            WHERE empleado_id = %s AND fecha BETWEEN %s AND %s
              AND hora_entrada IS NOT NULL AND hora_salida IS NOT NULL AND hora_salida > hora_entrada
            """,
            (empleado_id, fecha_desde, fecha_hasta),
        )

        semanal_rows = _safe_fetchall(
            cursor,
            """
            SELECT
                YEARWEEK(fecha, 1) AS yearweek,
                MIN(fecha) AS desde,
                MAX(fecha) AS hasta,
                COUNT(*) AS registros,
                SUM(CASE WHEN COALESCE(estado,'')='ok' THEN 1 ELSE 0 END) AS ok,
                SUM(CASE WHEN estado='tarde' THEN 1 ELSE 0 END) AS tarde,
                SUM(CASE WHEN estado='ausente' THEN 1 ELSE 0 END) AS ausente,
                SUM(CASE WHEN estado='salida_anticipada' THEN 1 ELSE 0 END) AS salida_anticipada
            FROM asistencias
            WHERE empleado_id = %s AND fecha BETWEEN %s AND %s
            GROUP BY YEARWEEK(fecha, 1)
            ORDER BY yearweek ASC
            """,
            (empleado_id, fecha_desde, fecha_hasta),
        )

        total_registros = _to_int(resumen_row.get("registros"))
        ok_total = _to_int(resumen_row.get("ok_total"))
        tarde_total = _to_int(resumen_row.get("tarde_total"))
        ausente_total = _to_int(resumen_row.get("ausente_total"))
        salida_anticipada_total = _to_int(resumen_row.get("salida_anticipada_total"))
        sin_estado_total = _to_int(resumen_row.get("sin_estado_total"))
        jornadas_completas = _to_int(resumen_row.get("jornadas_completas"))
        jornadas_con_marca = _to_int(resumen_row.get("jornadas_con_marca"))
        ausentes_sin_justificacion = _to_int(ausentes_sin_justif_row.get("ausentes_sin_justificacion"))

        just_total = _to_int(just_row.get("total"))
        just_pendientes = _to_int(just_row.get("pendientes"))
        just_aprobadas = _to_int(just_row.get("aprobadas"))
        just_rechazadas = _to_int(just_row.get("rechazadas"))

        vac_eventos = _to_int(vacaciones_row.get("eventos"))
        vac_dias = _to_int(vacaciones_row.get("dias"))

        # --- racha_ok: consecutive days (sorted DESC) where ok_total == registros > 0 ---
        racha_ok = 0
        sorted_diario = sorted(diario_rows, key=lambda r: str(r.get("fecha")), reverse=True)
        for row in sorted_diario:
            reg = _to_int(row.get("registros"))
            ok = _to_int(row.get("ok_total"))
            if reg > 0 and ok == reg:
                racha_ok += 1
            else:
                break

        # --- adherencia ---
        dias_laborables = _count_workdays(fecha_desde, fecha_hasta)
        dias_con_registro = len({str(row.get("fecha")) for row in diario_rows})
        adherencia_pct = _pct(dias_con_registro, dias_laborables)

        # --- tasa_justificacion_pct: aprobadas / ausentes ---
        tasa_justificacion_pct = _pct(just_aprobadas, ausente_total)

        diario = []
        for row in diario_rows:
            registros = _to_int(row.get("registros"))
            ok = _to_int(row.get("ok_total"))
            tarde = _to_int(row.get("tarde_total"))
            ausente = _to_int(row.get("ausente_total"))
            salida_anticipada = _to_int(row.get("salida_anticipada_total"))
            diario.append(
                {
                    "fecha": str(row.get("fecha")),
                    "registros": registros,
                    "ok": ok,
                    "tarde": tarde,
                    "ausente": ausente,
                    "salida_anticipada": salida_anticipada,
                    "puntualidad_pct": _pct(ok, registros),
                    "ausentismo_pct": _pct(ausente, registros),
                }
            )

        semanal = [
            {
                "desde": str(w.get("desde")),
                "hasta": str(w.get("hasta")),
                "registros": _to_int(w.get("registros")),
                "ok": _to_int(w.get("ok")),
                "tarde": _to_int(w.get("tarde")),
                "ausente": _to_int(w.get("ausente")),
                "salida_anticipada": _to_int(w.get("salida_anticipada")),
                "puntualidad_pct": _pct(_to_int(w.get("ok")), _to_int(w.get("registros"))),
            }
            for w in semanal_rows
        ]

        return {
            "totales": {
                "registros": total_registros,
                "ok": ok_total,
                "tarde": tarde_total,
                "ausente": ausente_total,
                "salida_anticipada": salida_anticipada_total,
                "sin_estado": sin_estado_total,
            },
            "kpis": {
                "puntualidad_pct": _pct(ok_total, total_registros),
                "ausentismo_pct": _pct(ausente_total, total_registros),
                "cumplimiento_jornada_pct": _pct(jornadas_completas, jornadas_con_marca),
                "no_show_pct": _pct(ausentes_sin_justificacion, ausente_total),
                "tasa_salida_anticipada_pct": _pct(salida_anticipada_total, total_registros),
                "adherencia_pct": adherencia_pct,
                "horas_promedio": round(float(horas_row.get("horas_promedio") or 0), 2),
                "horas_totales": round(float(horas_row.get("horas_totales") or 0), 1),
                "gps_incidencias": _to_int(gps_row.get("gps_incidencias")),
                "dias_laborables": dias_laborables,
                "dias_con_registro": dias_con_registro,
                "racha_ok": racha_ok,
            },
            "jornadas": {
                "completas": jornadas_completas,
                "con_marca": jornadas_con_marca,
                "incompletas": max(0, jornadas_con_marca - jornadas_completas),
            },
            "justificaciones": {
                "total": just_total,
                "pendientes": just_pendientes,
                "aprobadas": just_aprobadas,
                "rechazadas": just_rechazadas,
                "tasa_aprobacion_pct": _pct(just_aprobadas, just_total),
                "tasa_justificacion_pct": tasa_justificacion_pct,
            },
            "vacaciones": {
                "eventos": vac_eventos,
                "dias": vac_dias,
            },
            "ausencias": {
                "total": ausente_total,
                "sin_justificacion": ausentes_sin_justificacion,
            },
            "series": {
                "diaria": diario,
                "semanal": semanal,
            },
        }
    finally:
        cursor.close()
        db.close()
