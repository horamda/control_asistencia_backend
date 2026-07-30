import calendar
import datetime

from extensions import get_db


# ---------------------------------------------------------------------------
# KPI Definicion
# ---------------------------------------------------------------------------

def get_kpis_by_sector(sector_id: int, activo: int | None = None):
    db = get_db()
    cursor = db.cursor(dictionary=True)
    try:
        where = ["k.sector_id = %s"]
        params = [sector_id]
        if activo is not None:
            where.append("k.activo = %s")
            params.append(activo)
        cursor.execute(
            f"""
            SELECT k.*
            FROM kpis_definicion k
            WHERE {' AND '.join(where)}
            ORDER BY k.nombre
            """,
            tuple(params),
        )
        return cursor.fetchall()
    finally:
        cursor.close()
        db.close()


def get_kpis_by_empresa(empresa_id: int, activo: int | None = None):
    """Todos los KPIs de la empresa agrupados — usado para vistas de resumen."""
    db = get_db()
    cursor = db.cursor(dictionary=True)
    try:
        where = ["k.empresa_id = %s"]
        params = [empresa_id]
        if activo is not None:
            where.append("k.activo = %s")
            params.append(activo)
        cursor.execute(
            f"""
            SELECT k.*, s.nombre AS sector_nombre
            FROM kpis_definicion k
            JOIN sectores s ON s.id = k.sector_id
            WHERE {' AND '.join(where)}
            ORDER BY s.nombre, k.nombre
            """,
            tuple(params),
        )
        return cursor.fetchall()
    finally:
        cursor.close()
        db.close()


def get_kpi_by_id(kpi_id: int):
    db = get_db()
    cursor = db.cursor(dictionary=True)
    try:
        cursor.execute(
            """
            SELECT k.*, s.nombre AS sector_nombre
            FROM kpis_definicion k
            JOIN sectores s ON s.id = k.sector_id
            WHERE k.id = %s
            """,
            (kpi_id,),
        )
        return cursor.fetchone()
    finally:
        cursor.close()
        db.close()


def create_kpi(empresa_id: int, sector_id: int, codigo: str, nombre: str,
               descripcion: str | None, unidad: str, tipo_acumulacion: str,
               mayor_es_mejor: int) -> int:
    db = get_db()
    cursor = db.cursor()
    try:
        cursor.execute(
            """
            INSERT INTO kpis_definicion
              (empresa_id, sector_id, codigo, nombre, descripcion, unidad, tipo_acumulacion, mayor_es_mejor)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (empresa_id, sector_id, codigo, nombre, descripcion, unidad, tipo_acumulacion, mayor_es_mejor),
        )
        db.commit()
        return cursor.lastrowid
    finally:
        cursor.close()
        db.close()


def update_kpi(kpi_id: int, codigo: str, nombre: str, descripcion: str | None,
               unidad: str, tipo_acumulacion: str, mayor_es_mejor: int):
    db = get_db()
    cursor = db.cursor()
    try:
        cursor.execute(
            """
            UPDATE kpis_definicion
            SET codigo=%s, nombre=%s, descripcion=%s, unidad=%s,
                tipo_acumulacion=%s, mayor_es_mejor=%s
            WHERE id = %s
            """,
            (codigo, nombre, descripcion, unidad, tipo_acumulacion, mayor_es_mejor, kpi_id),
        )
        db.commit()
    finally:
        cursor.close()
        db.close()


def toggle_kpi_activo(kpi_id: int):
    db = get_db()
    cursor = db.cursor()
    try:
        cursor.execute(
            "UPDATE kpis_definicion SET activo = 1 - activo WHERE id = %s",
            (kpi_id,),
        )
        db.commit()
    finally:
        cursor.close()
        db.close()


# ---------------------------------------------------------------------------
# Sector Objetivos
# ---------------------------------------------------------------------------

_CONDICIONES_VALIDAS = {"gte", "lte", "eq", "between"}
_MONTH_NAMES = ["", "Enero", "Febrero", "Marzo", "Abril", "Mayo", "Junio",
                "Julio", "Agosto", "Septiembre", "Octubre", "Noviembre", "Diciembre"]
_CONDICION_SIMBOLO = {"gte": "≥", "lte": "≤", "eq": "=", "between": "entre"}


def get_objetivos_by_sector_anio(sector_id: int, anio: int):
    """Objetivos del sector para el año, uno por KPI."""
    db = get_db()
    cursor = db.cursor(dictionary=True)
    try:
        cursor.execute(
            """
            SELECT
                k.id AS kpi_id,
                k.codigo,
                k.nombre AS kpi_nombre,
                k.unidad,
                k.tipo_acumulacion,
                k.mayor_es_mejor,
                o.objetivo_valor,
                o.condicion,
                o.valor_min,
                o.valor_max,
                o.id AS objetivo_id
            FROM kpis_definicion k
            LEFT JOIN kpis_sector_objetivo o
                ON o.kpi_id = k.id AND o.sector_id = %s AND o.anio = %s
            WHERE k.sector_id = %s AND k.activo = 1
            ORDER BY k.nombre
            """,
            (sector_id, anio, sector_id),
        )
        return cursor.fetchall()
    finally:
        cursor.close()
        db.close()


def upsert_objetivo(empresa_id: int, sector_id: int, kpi_id: int, anio: int,
                    condicion: str = "gte",
                    objetivo_valor: float | None = None,
                    valor_min: float | None = None,
                    valor_max: float | None = None):
    if condicion not in _CONDICIONES_VALIDAS:
        condicion = "gte"
    # between usa valor_min/valor_max; objetivo_valor no aplica (NULL tras migración 04)
    if condicion == "between":
        objetivo_valor = None
    db = get_db()
    cursor = db.cursor()
    try:
        cursor.execute(
            """
            INSERT INTO kpis_sector_objetivo
              (empresa_id, sector_id, kpi_id, anio, objetivo_valor, condicion, valor_min, valor_max)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            ON DUPLICATE KEY UPDATE
              objetivo_valor = VALUES(objetivo_valor),
              condicion      = VALUES(condicion),
              valor_min      = VALUES(valor_min),
              valor_max      = VALUES(valor_max)
            """,
            (empresa_id, sector_id, kpi_id, anio, objetivo_valor, condicion, valor_min, valor_max),
        )
        db.commit()
    finally:
        cursor.close()
        db.close()


def tiene_objetivos_anio(sector_id: int, anio: int) -> bool:
    db = get_db()
    cursor = db.cursor()
    try:
        cursor.execute(
            "SELECT COUNT(*) FROM kpis_sector_objetivo WHERE sector_id=%s AND anio=%s",
            (sector_id, anio),
        )
        row = cursor.fetchone()
        return (row[0] if row else 0) > 0
    finally:
        cursor.close()
        db.close()


def copiar_objetivos_anio(empresa_id: int, sector_id: int, anio_origen: int, anio_destino: int):
    """Copia todos los objetivos de anio_origen a anio_destino, sobreescribiendo existentes."""
    db = get_db()
    cursor = db.cursor()
    try:
        cursor.execute(
            """
            INSERT INTO kpis_sector_objetivo
              (empresa_id, sector_id, kpi_id, anio, objetivo_valor, condicion, valor_min, valor_max)
            SELECT empresa_id, sector_id, kpi_id, %s, objetivo_valor, condicion, valor_min, valor_max
            FROM kpis_sector_objetivo
            WHERE sector_id = %s AND anio = %s
            ON DUPLICATE KEY UPDATE
              objetivo_valor = VALUES(objetivo_valor),
              condicion      = VALUES(condicion),
              valor_min      = VALUES(valor_min),
              valor_max      = VALUES(valor_max)
            """,
            (anio_destino, sector_id, anio_origen),
        )
        db.commit()
        return cursor.rowcount
    finally:
        cursor.close()
        db.close()


def delete_objetivo(sector_id: int, kpi_id: int, anio: int):
    db = get_db()
    cursor = db.cursor()
    try:
        cursor.execute(
            "DELETE FROM kpis_sector_objetivo WHERE sector_id=%s AND kpi_id=%s AND anio=%s",
            (sector_id, kpi_id, anio),
        )
        db.commit()
    finally:
        cursor.close()
        db.close()


# ---------------------------------------------------------------------------
# Resultados diarios por empleado
# ---------------------------------------------------------------------------

def get_empleados_by_sector_para_kpis(empresa_id: int, sector_id: int, sucursal_id: int | None = None):
    db = get_db()
    cursor = db.cursor(dictionary=True)
    try:
        where = ["e.empresa_id = %s", "e.sector_id = %s", "e.activo = 1"]
        params = [empresa_id, sector_id]
        if sucursal_id:
            where.append("e.sucursal_id = %s")
            params.append(sucursal_id)
        cursor.execute(
            f"""
            SELECT
                e.id,
                e.empresa_id,
                e.sector_id,
                e.sucursal_id,
                e.legajo,
                e.dni,
                e.nombre,
                e.apellido,
                emp.razon_social AS empresa_nombre,
                sec.nombre AS sector_nombre,
                suc.nombre AS sucursal_nombre
            FROM empleados e
            JOIN empresas emp ON emp.id = e.empresa_id
            LEFT JOIN sectores sec ON sec.id = e.sector_id
            LEFT JOIN sucursales suc ON suc.id = e.sucursal_id
            WHERE {" AND ".join(where)}
            ORDER BY e.apellido, e.nombre
            """,
            params,
        )
        return cursor.fetchall()
    finally:
        cursor.close()
        db.close()


def get_resultados_empleado_kpis_anio(empleado_id: int, sector_id: int, anio: int):
    """Devuelve KPIs activos del sector y sus resultados diarios del empleado en el anio."""
    db = get_db()
    cursor = db.cursor(dictionary=True)
    try:
        desde = datetime.date(anio, 1, 1).isoformat()
        hasta = datetime.date(anio, 12, 31).isoformat()
        cursor.execute(
            """
            SELECT
                k.id AS kpi_id,
                k.codigo,
                k.nombre,
                k.unidad,
                k.tipo_acumulacion,
                k.mayor_es_mejor,
                o.objetivo_valor,
                COALESCE(o.condicion, 'gte') AS condicion,
                o.valor_min,
                o.valor_max,
                r.fecha,
                r.valor
            FROM kpis_definicion k
            LEFT JOIN kpis_sector_objetivo o
                ON o.kpi_id = k.id
               AND o.sector_id = %s
               AND o.anio = %s
            LEFT JOIN kpis_empleado_resultado r
                ON r.kpi_id = k.id
               AND r.empleado_id = %s
               AND r.fecha BETWEEN %s AND %s
            WHERE k.sector_id = %s
              AND k.activo = 1
            ORDER BY k.nombre, r.fecha
            """,
            (sector_id, anio, empleado_id, desde, hasta, sector_id),
        )
        return cursor.fetchall()
    finally:
        cursor.close()
        db.close()


def bulk_upsert_resultados(rows: list[tuple]):
    """rows: list of (empresa_id, empleado_id, kpi_id, fecha, valor)"""
    if not rows:
        return
    db = get_db()
    cursor = db.cursor()
    try:
        cursor.executemany(
            """
            INSERT INTO kpis_empleado_resultado (empresa_id, empleado_id, kpi_id, fecha, valor)
            VALUES (%s, %s, %s, %s, %s)
            ON DUPLICATE KEY UPDATE valor = VALUES(valor)
            """,
            rows,
        )
        db.commit()
    finally:
        cursor.close()
        db.close()


def delete_resultados_mes(empresa_id: int, sector_id: int, anio: int, mes: int,
                          empleado_id: int | None = None, kpi_id: int | None = None) -> int:
    """Elimina resultados cargados en un mes, acotados a empresa/sector y filtros opcionales."""
    desde = datetime.date(anio, mes, 1).isoformat()
    hasta = datetime.date(anio, mes, calendar.monthrange(anio, mes)[1]).isoformat()
    where = [
        "r.empresa_id = %s",
        "r.fecha BETWEEN %s AND %s",
        "e.empresa_id = %s",
        "e.sector_id = %s",
        "k.empresa_id = %s",
        "k.sector_id = %s",
    ]
    params = [empresa_id, desde, hasta, empresa_id, sector_id, empresa_id, sector_id]
    if empleado_id:
        where.append("r.empleado_id = %s")
        params.append(empleado_id)
    if kpi_id:
        where.append("r.kpi_id = %s")
        params.append(kpi_id)

    db = get_db()
    cursor = db.cursor()
    try:
        cursor.execute(
            f"""
            DELETE r
            FROM kpis_empleado_resultado r
            JOIN empleados e ON e.id = r.empleado_id
            JOIN kpis_definicion k ON k.id = r.kpi_id
            WHERE {' AND '.join(where)}
            """,
            tuple(params),
        )
        db.commit()
        return cursor.rowcount
    finally:
        cursor.close()
        db.close()


def delete_resultados_mes_empleados(empresa_id: int, anio: int, mes: int, empleado_ids: list[int]) -> int:
    """Elimina resultados de un mes para empleados especificos de una empresa."""
    empleado_ids = sorted({int(emp_id) for emp_id in empleado_ids if emp_id})
    if not empleado_ids:
        return 0

    desde = datetime.date(anio, mes, 1).isoformat()
    hasta = datetime.date(anio, mes, calendar.monthrange(anio, mes)[1]).isoformat()
    placeholders = ", ".join(["%s"] * len(empleado_ids))
    db = get_db()
    cursor = db.cursor()
    try:
        cursor.execute(
            f"""
            DELETE FROM kpis_empleado_resultado
            WHERE empresa_id = %s
              AND fecha BETWEEN %s AND %s
              AND empleado_id IN ({placeholders})
            """,
            tuple([empresa_id, desde, hasta, *empleado_ids]),
        )
        db.commit()
        return cursor.rowcount
    finally:
        cursor.close()
        db.close()


def get_ultimo_resultado_cargado_empleado(empleado_id: int, anio: int | None = None):
    """Ultimo resultado de KPI cargado para el empleado, ordenado por actualizacion."""
    db = get_db()
    cursor = db.cursor(dictionary=True)
    try:
        where = ["e.id = %s", "k.activo = 1", "k.sector_id = e.sector_id"]
        params = [empleado_id]
        if anio:
            where.append("r.fecha BETWEEN %s AND %s")
            params.extend([f"{anio}-01-01", f"{anio}-12-31"])

        cursor.execute(
            f"""
            SELECT
                k.id AS kpi_id,
                k.codigo,
                k.nombre,
                k.unidad,
                k.tipo_acumulacion,
                k.mayor_es_mejor,
                COALESCE(o.objetivo_valor, 0) AS objetivo_anual,
                COALESCE(o.condicion, 'gte') AS condicion,
                o.valor_min,
                o.valor_max,
                r.fecha,
                r.valor,
                r.created_at,
                r.updated_at
            FROM empleados e
            JOIN kpis_empleado_resultado r ON r.empleado_id = e.id
            JOIN kpis_definicion k ON k.id = r.kpi_id
            LEFT JOIN kpis_sector_objetivo o
                ON o.kpi_id = k.id
               AND o.sector_id = e.sector_id
               AND o.anio = YEAR(r.fecha)
            WHERE {' AND '.join(where)}
            ORDER BY r.updated_at DESC, r.fecha DESC, r.id DESC
            LIMIT 1
            """,
            tuple(params),
        )
        row = cursor.fetchone()
        if not row:
            return None

        fecha = _iso_date(row.get("fecha"))
        fecha_year = int(fecha[:4]) if fecha else (anio or datetime.date.today().year)
        fraccion = _period_fraction_for_kpi(row, 1 / _days_in_year(fecha_year))
        item = _build_mobile_kpi_result_item(row, float(row["valor"]), fraccion)
        item.update({
            "valor": round(float(row["valor"]), 4),
            "fecha_resultado": fecha,
            "cargado_at": _iso_datetime(row.get("updated_at") or row.get("created_at")),
        })
        return item
    finally:
        cursor.close()
        db.close()


def get_resultados_empleado_meses_cerrados(
    empleado_id: int,
    anio: int,
    limit_meses: int = 6,
    today: datetime.date | None = None,
):
    """KPIs mensuales del empleado para meses calendario ya cerrados."""
    today = today or datetime.date.today()
    limit_meses = max(1, min(int(limit_meses or 6), 12))

    if anio < today.year:
        ultimo_mes_cerrado = 12
    elif anio == today.year:
        ultimo_mes_cerrado = today.month - 1
    else:
        ultimo_mes_cerrado = 0

    if ultimo_mes_cerrado <= 0:
        return []

    meses = list(range(ultimo_mes_cerrado, 0, -1))[:limit_meses]
    db = get_db()
    cursor = db.cursor(dictionary=True)
    try:
        sector = _get_sector_empleado(cursor, empleado_id)
        sector_id = sector.get("sector_id")
        if not sector_id:
            return []

        cursor.execute(
            """
            SELECT
                k.id AS kpi_id,
                k.codigo,
                k.nombre,
                k.unidad,
                k.tipo_acumulacion,
                k.mayor_es_mejor,
                COALESCE(o.objetivo_valor, 0) AS objetivo_anual,
                COALESCE(o.condicion, 'gte') AS condicion,
                o.valor_min,
                o.valor_max
            FROM kpis_definicion k
            LEFT JOIN kpis_sector_objetivo o
                ON o.kpi_id = k.id
               AND o.sector_id = %s
               AND o.anio = %s
            WHERE k.sector_id = %s
              AND k.activo = 1
            ORDER BY k.nombre
            """,
            (sector_id, anio, sector_id),
        )
        kpis = cursor.fetchall()
        if not kpis:
            return [
                _build_empty_closed_month(anio, mes)
                for mes in meses
            ]

        desde = datetime.date(anio, min(meses), 1).isoformat()
        hasta_mes = max(meses)
        hasta = datetime.date(
            anio,
            hasta_mes,
            calendar.monthrange(anio, hasta_mes)[1],
        ).isoformat()
        cursor.execute(
            """
            SELECT kpi_id, fecha, valor
            FROM kpis_empleado_resultado
            WHERE empleado_id = %s
              AND fecha BETWEEN %s AND %s
            ORDER BY fecha
            """,
            (empleado_id, desde, hasta),
        )
        valores = {}
        for row in cursor.fetchall():
            fecha = _iso_date(row.get("fecha"))
            if not fecha:
                continue
            mes = int(fecha[5:7])
            valores.setdefault((mes, int(row["kpi_id"])), []).append((fecha, float(row["valor"])))

        result = []
        for mes in meses:
            mes_inicio = datetime.date(anio, mes, 1)
            mes_fin = datetime.date(anio, mes, calendar.monthrange(anio, mes)[1])
            fraccion_mes = ((mes_fin - mes_inicio).days + 1) / _days_in_year(anio)
            items = []
            resumen = {"total": 0, "verde": 0, "amarillo": 0, "rojo": 0, "gris": 0}

            for kpi in kpis:
                kpi_id = int(kpi["kpi_id"])
                kpi_values = valores.get((mes, kpi_id), [])
                resultado = _aggregate_kpi_values(kpi_values, kpi.get("tipo_acumulacion"))
                fraccion = _period_fraction_for_kpi(kpi, fraccion_mes)
                item = _build_mobile_kpi_result_item(kpi, resultado, fraccion)
                item.update({
                    "resultado_mes": item.pop("resultado"),
                    "objetivo_mes": item.pop("objetivo_periodo"),
                    "registros": len(kpi_values),
                    "fecha_ultimo_resultado": kpi_values[-1][0] if kpi_values else None,
                })
                resumen["total"] += 1
                resumen[item["semaforo"]] = resumen.get(item["semaforo"], 0) + 1
                items.append(item)

            result.append({
                "periodo": f"{anio}-{mes:02d}",
                "periodo_year": anio,
                "periodo_month": mes,
                "mes_nombre": _MONTH_NAMES[mes],
                "desde": mes_inicio.isoformat(),
                "hasta": mes_fin.isoformat(),
                "cerrado": True,
                "resumen": resumen,
                "kpis": items,
            })

        return result
    finally:
        cursor.close()
        db.close()


def get_resultados_empleado_anio(empleado_id: int, anio: int):
    """
    KPIs del sector del empleado con resultado acumulado y semaforo.
    Solo muestra los KPIs del sector al que pertenece el empleado.
    """
    db = get_db()
    cursor = db.cursor(dictionary=True)
    try:
        today = datetime.date.today()
        anio_inicio = f"{anio}-01-01"
        hasta = min(today, datetime.date(anio, 12, 31)).isoformat()

        cursor.execute(
            """
            SELECT e.sector_id, sec.nombre AS sector_nombre
            FROM empleados e
            LEFT JOIN sectores sec ON sec.id = e.sector_id
            WHERE e.id = %s
            """,
            (empleado_id,),
        )
        emp_row = cursor.fetchone() or {}
        sector_id = emp_row.get("sector_id")
        sector_nombre = emp_row.get("sector_nombre")

        if not sector_id:
            return {"sector_id": None, "sector_nombre": None, "kpis": []}

        cursor.execute(
            """
            SELECT
                k.id AS kpi_id,
                k.codigo,
                k.nombre,
                k.unidad,
                k.tipo_acumulacion,
                k.mayor_es_mejor,
                COALESCE(o.objetivo_valor, 0) AS objetivo_anual,
                COALESCE(o.condicion, 'gte') AS condicion,
                o.valor_min,
                o.valor_max,
                CASE k.tipo_acumulacion
                    WHEN 'suma'     THEN COALESCE(SUM(r.valor), 0)
                    WHEN 'promedio' THEN COALESCE(AVG(r.valor), 0)
                    WHEN 'ultimo'   THEN COALESCE(
                        (SELECT r2.valor FROM kpis_empleado_resultado r2
                         WHERE r2.empleado_id = %s AND r2.kpi_id = k.id
                           AND r2.fecha BETWEEN %s AND %s
                         ORDER BY r2.fecha DESC LIMIT 1), 0)
                    ELSE 0
                END AS resultado_acumulado
            FROM kpis_definicion k
            LEFT JOIN kpis_sector_objetivo o
                ON o.kpi_id = k.id AND o.sector_id = %s AND o.anio = %s
            LEFT JOIN kpis_empleado_resultado r
                ON r.kpi_id = k.id AND r.empleado_id = %s
                AND r.fecha BETWEEN %s AND %s
            WHERE k.sector_id = %s AND k.activo = 1
            GROUP BY k.id, k.codigo, k.nombre, k.unidad, k.tipo_acumulacion, k.mayor_es_mejor, o.objetivo_valor, o.condicion, o.valor_min, o.valor_max
            ORDER BY k.nombre
            """,
            (
                empleado_id, anio_inicio, hasta,
                sector_id, anio,
                empleado_id, anio_inicio, hasta,
                sector_id,
            ),
        )
        kpi_rows = cursor.fetchall()

        day_of_year = today.timetuple().tm_yday
        days_in_year = 366 if _is_leap(anio) else 365
        fraccion_anio = day_of_year / days_in_year if anio == today.year else 1.0

        result = []
        for row in kpi_rows:
            objetivo = float(row["objetivo_anual"] or 0)
            acumulado = float(row["resultado_acumulado"] or 0)
            condicion = row["condicion"] or "gte"
            valor_min = float(row["valor_min"]) if row["valor_min"] is not None else None
            valor_max = float(row["valor_max"]) if row["valor_max"] is not None else None
            tipo_acumulacion = row["tipo_acumulacion"]

            usa_fraccion = tipo_acumulacion == "suma" and condicion != "between"
            progreso_pct = round((acumulado / objetivo * 100) if objetivo > 0 else 0, 1)
            esperado_pct = round(fraccion_anio * 100, 1) if usa_fraccion else 100.0

            semaforo, recomendacion = _calcular_semaforo(
                acumulado, objetivo,
                fraccion_anio if usa_fraccion else 1.0,
                condicion,
                valor_min=valor_min,
                valor_max=valor_max,
            )

            result.append({
                "kpi_id": row["kpi_id"],
                "codigo": row["codigo"],
                "nombre": row["nombre"],
                "unidad": row["unidad"],
                "tipo_acumulacion": tipo_acumulacion,
                "mayor_es_mejor": bool(row["mayor_es_mejor"]),
                "condicion": condicion,
                "condicion_simbolo": _CONDICION_SIMBOLO.get(condicion, "≥"),
                "objetivo_anual": objetivo,
                "valor_min": valor_min,
                "valor_max": valor_max,
                "resultado_acumulado": round(acumulado, 4),
                "progreso_pct": progreso_pct,
                "progreso_esperado_pct": esperado_pct,
                "semaforo": semaforo,
                "recomendacion": recomendacion,
            })

        return {
            "sector_id": sector_id,
            "sector_nombre": sector_nombre,
            "kpis": result,
        }
    finally:
        cursor.close()
        db.close()


def get_series_diaria_empleado(
    empleado_id: int,
    anio: int,
    dias: int = 60,
    today: datetime.date | None = None,
):
    """
    Serie diaria de KPIs del sector del empleado con acumulados y semáforos por punto.

    - Solo incluye fechas donde hay resultado real (no rellena días vacíos).
    - Fetch de todo el año para acumulados correctos; muestra solo los últimos `dias` días.
    - Para KPIs 'between': objetivo_dia y objetivo_acumulado_a_fecha son null.
    """
    today = today or datetime.date.today()
    dias = max(1, min(int(dias), 365))

    anio_inicio = datetime.date(anio, 1, 1)
    anio_fin = min(today, datetime.date(anio, 12, 31))
    display_desde = max(anio_inicio, anio_fin - datetime.timedelta(days=dias - 1))
    dias_en_anio = _days_in_year(anio)

    db = get_db()
    cursor = db.cursor(dictionary=True)
    try:
        sector = _get_sector_empleado(cursor, empleado_id)
        sector_id = sector.get("sector_id")
        if not sector_id:
            return []

        cursor.execute(
            """
            SELECT
                k.id AS kpi_id,
                k.codigo,
                k.nombre,
                k.unidad,
                k.tipo_acumulacion,
                k.mayor_es_mejor,
                COALESCE(o.objetivo_valor, 0) AS objetivo_anual,
                COALESCE(o.condicion, 'gte') AS condicion,
                o.valor_min,
                o.valor_max
            FROM kpis_definicion k
            LEFT JOIN kpis_sector_objetivo o
                ON o.kpi_id = k.id
               AND o.sector_id = %s
               AND o.anio = %s
            WHERE k.sector_id = %s AND k.activo = 1
            ORDER BY k.nombre
            """,
            (sector_id, anio, sector_id),
        )
        kpis = cursor.fetchall()
        if not kpis:
            return []

        cursor.execute(
            """
            SELECT kpi_id, fecha, valor
            FROM kpis_empleado_resultado
            WHERE empleado_id = %s
              AND fecha BETWEEN %s AND %s
            ORDER BY kpi_id, fecha
            """,
            (empleado_id, anio_inicio.isoformat(), anio_fin.isoformat()),
        )
        raw: dict[int, list[tuple[str, float]]] = {}
        for row in cursor.fetchall():
            kid = int(row["kpi_id"])
            raw.setdefault(kid, []).append((_iso_date(row["fecha"]), float(row["valor"])))

        display_desde_str = display_desde.isoformat()
        result = []

        for kpi in kpis:
            kpi_id = int(kpi["kpi_id"])
            tipo = kpi.get("tipo_acumulacion")
            condicion = kpi.get("condicion") or "gte"
            objetivo = float(kpi.get("objetivo_anual") or 0)
            valor_min = float(kpi["valor_min"]) if kpi.get("valor_min") is not None else None
            valor_max = float(kpi["valor_max"]) if kpi.get("valor_max") is not None else None
            is_between = condicion == "between"
            usa_fraccion = tipo == "suma" and not is_between

            puntos_raw = sorted(raw.get(kpi_id, []), key=lambda x: x[0])

            running_sum = 0.0
            running_vals: list[float] = []
            puntos = []

            for fecha_str, valor in puntos_raw:
                running_sum += valor
                running_vals.append(valor)

                if tipo == "suma":
                    acumulado = running_sum
                elif tipo == "promedio":
                    acumulado = running_sum / len(running_vals)
                else:
                    acumulado = valor

                if fecha_str < display_desde_str:
                    continue

                fecha_date = datetime.date.fromisoformat(fecha_str)
                dia_del_anio = fecha_date.timetuple().tm_yday
                fraccion_dia = 1.0 / dias_en_anio
                fraccion_acum = dia_del_anio / dias_en_anio

                if is_between:
                    objetivo_dia = None
                    objetivo_acum = None
                elif usa_fraccion:
                    objetivo_dia = round(objetivo * fraccion_dia, 4) if objetivo > 0 else 0.0
                    objetivo_acum = round(objetivo * fraccion_acum, 4) if objetivo > 0 else 0.0
                else:
                    objetivo_dia = objetivo
                    objetivo_acum = objetivo

                progreso_dia_pct = (
                    round(valor * 100 / objetivo_dia, 1)
                    if objetivo_dia and objetivo_dia > 0 else 0.0
                )
                progreso_acum_pct = (
                    round(acumulado * 100 / objetivo_acum, 1)
                    if objetivo_acum and objetivo_acum > 0 else 0.0
                )

                semaforo_dia, _ = _calcular_semaforo(
                    valor, objetivo, fraccion_dia if usa_fraccion else 1.0,
                    condicion, valor_min=valor_min, valor_max=valor_max,
                )
                semaforo_acum, _ = _calcular_semaforo(
                    acumulado, objetivo, fraccion_acum if usa_fraccion else 1.0,
                    condicion, valor_min=valor_min, valor_max=valor_max,
                )

                puntos.append({
                    "fecha": fecha_str,
                    "resultado_dia": round(valor, 4),
                    "objetivo_dia": objetivo_dia,
                    "resultado_acumulado_a_fecha": round(acumulado, 4),
                    "objetivo_acumulado_a_fecha": objetivo_acum,
                    "progreso_dia_pct": progreso_dia_pct,
                    "progreso_acumulado_pct": progreso_acum_pct,
                    "semaforo_dia": semaforo_dia,
                    "semaforo_acumulado": semaforo_acum,
                })

            result.append({
                "kpi_id": kpi_id,
                "codigo": kpi["codigo"],
                "nombre": kpi["nombre"],
                "unidad": kpi["unidad"],
                "tipo_acumulacion": tipo,
                "condicion": condicion,
                "condicion_simbolo": _CONDICION_SIMBOLO.get(condicion, "≥"),
                "objetivo_anual": objetivo,
                "valor_min": valor_min,
                "valor_max": valor_max,
                "periodo_desde": display_desde.isoformat(),
                "periodo_hasta": anio_fin.isoformat(),
                "puntos": puntos,
            })

        return result
    finally:
        cursor.close()
        db.close()


def get_kpis_dia_empleado(
    empleado_id: int,
    fecha: datetime.date,
):
    """
    Snapshot de todos los KPIs del sector del empleado para una fecha concreta.

    Siempre devuelve una fila por KPI activo, haya o no resultado ese día.
    El acumulado se calcula desde el 1 de enero del año de la fecha.
    """
    anio = fecha.year
    anio_inicio = datetime.date(anio, 1, 1)
    dias_en_anio = _days_in_year(anio)
    dia_del_anio = fecha.timetuple().tm_yday
    fraccion_dia = 1.0 / dias_en_anio
    fraccion_acum = dia_del_anio / dias_en_anio

    db = get_db()
    cursor = db.cursor(dictionary=True)
    try:
        sector = _get_sector_empleado(cursor, empleado_id)
        sector_id = sector.get("sector_id")
        if not sector_id:
            return {"sector_id": None, "sector_nombre": None, "kpis": []}

        cursor.execute(
            """
            SELECT
                k.id AS kpi_id,
                k.codigo,
                k.nombre,
                k.unidad,
                k.tipo_acumulacion,
                k.mayor_es_mejor,
                COALESCE(o.objetivo_valor, 0) AS objetivo_anual,
                COALESCE(o.condicion, 'gte') AS condicion,
                o.valor_min,
                o.valor_max
            FROM kpis_definicion k
            LEFT JOIN kpis_sector_objetivo o
                ON o.kpi_id = k.id
               AND o.sector_id = %s
               AND o.anio = %s
            WHERE k.sector_id = %s AND k.activo = 1
            ORDER BY k.nombre
            """,
            (sector_id, anio, sector_id),
        )
        kpis = cursor.fetchall()
        if not kpis:
            return {"sector_id": sector_id, "sector_nombre": sector.get("sector_nombre"), "kpis": []}

        # Todos los resultados desde inicio de año hasta la fecha (inclusive)
        cursor.execute(
            """
            SELECT kpi_id, fecha, valor
            FROM kpis_empleado_resultado
            WHERE empleado_id = %s
              AND fecha BETWEEN %s AND %s
            ORDER BY kpi_id, fecha
            """,
            (empleado_id, anio_inicio.isoformat(), fecha.isoformat()),
        )
        raw: dict[int, list[tuple[str, float]]] = {}
        for row in cursor.fetchall():
            kid = int(row["kpi_id"])
            raw.setdefault(kid, []).append((_iso_date(row["fecha"]), float(row["valor"])))

        fecha_str = fecha.isoformat()
        result_kpis = []

        for kpi in kpis:
            kpi_id = int(kpi["kpi_id"])
            tipo = kpi.get("tipo_acumulacion")
            condicion = kpi.get("condicion") or "gte"
            objetivo = float(kpi.get("objetivo_anual") or 0)
            valor_min = float(kpi["valor_min"]) if kpi.get("valor_min") is not None else None
            valor_max = float(kpi["valor_max"]) if kpi.get("valor_max") is not None else None
            is_between = condicion == "between"
            usa_fraccion = tipo == "suma" and not is_between

            puntos_raw = sorted(raw.get(kpi_id, []), key=lambda x: x[0])

            # Acumulado hasta la fecha
            running_sum = sum(v for _, v in puntos_raw)
            running_vals = [v for _, v in puntos_raw]

            if tipo == "suma":
                acumulado = running_sum
            elif tipo == "promedio":
                acumulado = running_sum / len(running_vals) if running_vals else None
            else:
                acumulado = running_vals[-1] if running_vals else None

            # Resultado específico del día
            resultado_dia = next((v for d, v in puntos_raw if d == fecha_str), None)
            tiene_resultado = resultado_dia is not None

            # Objetivos
            if is_between:
                objetivo_dia = None
                objetivo_acum = None
            elif usa_fraccion:
                objetivo_dia = round(objetivo * fraccion_dia, 4) if objetivo > 0 else 0.0
                objetivo_acum = round(objetivo * fraccion_acum, 4) if objetivo > 0 else 0.0
            else:
                objetivo_dia = objetivo
                objetivo_acum = objetivo

            # Progresos
            progreso_dia_pct = (
                round(resultado_dia * 100 / objetivo_dia, 1)
                if tiene_resultado and objetivo_dia and objetivo_dia > 0 else 0.0
            )
            progreso_acum_pct = (
                round(acumulado * 100 / objetivo_acum, 1)
                if acumulado is not None and objetivo_acum and objetivo_acum > 0 else 0.0
            )

            # Semáforos
            if tiene_resultado:
                semaforo_dia, _ = _calcular_semaforo(
                    resultado_dia, objetivo, fraccion_dia if usa_fraccion else 1.0,
                    condicion, valor_min=valor_min, valor_max=valor_max,
                )
            else:
                semaforo_dia = "gris"

            if acumulado is not None:
                semaforo_acum, _ = _calcular_semaforo(
                    acumulado, objetivo, fraccion_acum if usa_fraccion else 1.0,
                    condicion, valor_min=valor_min, valor_max=valor_max,
                )
            else:
                semaforo_acum = "gris"

            result_kpis.append({
                "kpi_id": kpi_id,
                "codigo": kpi["codigo"],
                "nombre": kpi["nombre"],
                "unidad": kpi["unidad"],
                "tipo_acumulacion": tipo,
                "mayor_es_mejor": bool(kpi.get("mayor_es_mejor")),
                "condicion": condicion,
                "condicion_simbolo": _CONDICION_SIMBOLO.get(condicion, "≥"),
                "objetivo_anual": objetivo,
                "valor_min": valor_min,
                "valor_max": valor_max,
                "tiene_resultado": tiene_resultado,
                "resultado_dia": round(resultado_dia, 4) if tiene_resultado else None,
                "objetivo_dia": objetivo_dia,
                "resultado_acumulado_a_fecha": round(acumulado, 4) if acumulado is not None else None,
                "objetivo_acumulado_a_fecha": objetivo_acum,
                "progreso_dia_pct": progreso_dia_pct,
                "progreso_acumulado_pct": progreso_acum_pct,
                "semaforo_dia": semaforo_dia,
                "semaforo_acumulado": semaforo_acum,
            })

        return {
            "sector_id": sector_id,
            "sector_nombre": sector.get("sector_nombre"),
            "kpis": result_kpis,
        }
    finally:
        cursor.close()
        db.close()


def _get_sector_empleado(cursor, empleado_id: int):
    cursor.execute(
        """
        SELECT e.sector_id, sec.nombre AS sector_nombre
        FROM empleados e
        LEFT JOIN sectores sec ON sec.id = e.sector_id
        WHERE e.id = %s
        """,
        (empleado_id,),
    )
    return cursor.fetchone() or {"sector_id": None, "sector_nombre": None}


def _iso_date(value):
    if value is None:
        return None
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)[:10]


def _iso_datetime(value):
    if value is None:
        return None
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)


def _days_in_year(year: int):
    return 366 if calendar.isleap(year) else 365


def _period_fraction_for_kpi(kpi: dict, fraction: float):
    condicion = kpi.get("condicion") or "gte"
    if kpi.get("tipo_acumulacion") == "suma" and condicion != "between":
        return fraction
    return 1.0


def _aggregate_kpi_values(values: list[tuple[str, float]], tipo_acumulacion: str | None):
    if not values:
        return None
    ordered = sorted(values, key=lambda item: item[0])
    nums = [float(item[1]) for item in ordered]
    if tipo_acumulacion == "promedio":
        return sum(nums) / len(nums)
    if tipo_acumulacion == "ultimo":
        return nums[-1]
    return sum(nums)


def _build_mobile_kpi_result_item(kpi: dict, resultado: float | None, fraccion: float):
    condicion = kpi.get("condicion") or "gte"
    tipo_acumulacion = kpi.get("tipo_acumulacion")
    objetivo = float(kpi.get("objetivo_anual") or 0)
    valor_min = float(kpi["valor_min"]) if kpi.get("valor_min") is not None else None
    valor_max = float(kpi["valor_max"]) if kpi.get("valor_max") is not None else None

    objetivo_periodo = None
    if condicion != "between":
        objetivo_periodo = objetivo * fraccion if tipo_acumulacion == "suma" else objetivo

    if resultado is None:
        semaforo = "gris"
        recomendacion = "Sin resultado cargado para este periodo."
        progreso_pct = 0.0
    else:
        semaforo, recomendacion = _calcular_semaforo(
            float(resultado),
            objetivo,
            fraccion,
            condicion,
            valor_min=valor_min,
            valor_max=valor_max,
        )
        progreso_pct = (
            round(float(resultado) * 100 / objetivo_periodo, 1)
            if objetivo_periodo and objetivo_periodo > 0 else 0.0
        )

    return {
        "kpi_id": kpi.get("kpi_id"),
        "codigo": kpi.get("codigo"),
        "nombre": kpi.get("nombre"),
        "unidad": kpi.get("unidad"),
        "tipo_acumulacion": tipo_acumulacion,
        "mayor_es_mejor": bool(kpi.get("mayor_es_mejor")),
        "condicion": condicion,
        "condicion_simbolo": _CONDICION_SIMBOLO.get(condicion, ">="),
        "objetivo_anual": objetivo,
        "objetivo_periodo": round(objetivo_periodo, 4) if objetivo_periodo is not None else None,
        "valor_min": valor_min,
        "valor_max": valor_max,
        "resultado": round(float(resultado), 4) if resultado is not None else None,
        "progreso_pct": progreso_pct,
        "semaforo": semaforo,
        "recomendacion": recomendacion,
    }


def _build_empty_closed_month(anio: int, mes: int):
    mes_inicio = datetime.date(anio, mes, 1)
    mes_fin = datetime.date(anio, mes, calendar.monthrange(anio, mes)[1])
    return {
        "periodo": f"{anio}-{mes:02d}",
        "periodo_year": anio,
        "periodo_month": mes,
        "mes_nombre": _MONTH_NAMES[mes],
        "desde": mes_inicio.isoformat(),
        "hasta": mes_fin.isoformat(),
        "cerrado": True,
        "resumen": {"total": 0, "verde": 0, "amarillo": 0, "rojo": 0, "gris": 0},
        "kpis": [],
    }


def _is_leap(year: int) -> bool:
    return year % 4 == 0 and (year % 100 != 0 or year % 400 == 0)


def _calcular_semaforo(acumulado: float, objetivo: float, fraccion: float, condicion: str,
                       valor_min: float | None = None, valor_max: float | None = None):
    """
    condicion:
      'gte'     — resultado debe ser >= objetivo (mayor es mejor)
      'lte'     — resultado debe ser <= objetivo (menor es mejor)
      'eq'      — resultado debe ser ~= objetivo (tolerancia ±10%)
      'between' — resultado debe estar en [valor_min, valor_max]
    """
    if condicion == "between":
        if valor_min is None or valor_max is None:
            return "gris", "Rango sin definir para este KPI."
        rango = valor_max - valor_min
        margen = rango * 0.10 if rango > 0 else abs(valor_min) * 0.10
        if valor_min <= acumulado <= valor_max:
            return "verde", f"Dentro del rango objetivo ({valor_min} – {valor_max})."
        distancia = min(abs(acumulado - valor_min), abs(acumulado - valor_max))
        if distancia <= margen:
            return "amarillo", f"Levemente fuera del rango objetivo ({valor_min} – {valor_max})."
        return "rojo", f"Fuera del rango objetivo ({valor_min} – {valor_max}). Se requiere ajuste."

    if objetivo <= 0:
        return "gris", "Sin objetivo definido para este KPI."

    esperado = objetivo * fraccion
    if esperado <= 0:
        return "gris", "Sin datos esperados para calcular avance."

    if condicion == "gte":
        ratio = acumulado / esperado
        if ratio >= 0.90:
            return "verde", "En camino al objetivo anual."
        if ratio >= 0.70:
            return "amarillo", "Levemente por debajo del ritmo esperado."
        return "rojo", "Muy por debajo del objetivo esperado. Se requiere acelerar."

    if condicion == "lte":
        ratio = acumulado / esperado
        if ratio <= 1.10:
            return "verde", "Dentro del rango esperado."
        if ratio <= 1.30:
            return "amarillo", "Levemente por encima del limite esperado."
        return "rojo", "Por encima del limite objetivo. Se requiere mejora."

    # eq — tolerancia ±10%
    ratio = acumulado / esperado
    if 0.90 <= ratio <= 1.10:
        return "verde", "Dentro del valor objetivo esperado."
    if 0.75 <= ratio <= 1.25:
        return "amarillo", "Levemente fuera del valor objetivo."
    return "rojo", "Fuera del rango del objetivo. Se requiere ajuste."
