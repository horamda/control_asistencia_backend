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
            INSERT INTO kpis_sector_objetivo (empresa_id, sector_id, kpi_id, anio, objetivo_valor)
            SELECT empresa_id, sector_id, kpi_id, %s, objetivo_valor
            FROM kpis_sector_objetivo
            WHERE sector_id = %s AND anio = %s
            ON DUPLICATE KEY UPDATE objetivo_valor = VALUES(objetivo_valor)
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
