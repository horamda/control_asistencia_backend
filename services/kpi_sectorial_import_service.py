"""
Importacion de resultados diarios de KPIs desde CSV.

Formato esperado del CSV:
  fecha,legajo,codigo_kpi,valor

- fecha: YYYY-MM-DD
- legajo: legajo del empleado (unico por empresa)
- codigo_kpi: codigo del KPI dentro del sector del empleado
- valor: numero decimal (punto como separador)

El CSV debe corresponder a una sola empresa (empresa_id se pasa como param).
"""

import csv
import datetime
import io

from extensions import get_db
from repositories.kpi_sectorial_repository import bulk_upsert_resultados, delete_resultados_mes_empleados

_REQUIRED_HEADERS = {"fecha", "legajo", "codigo_kpi", "valor"}


class KpiImportError(ValueError):
    pass


def _today():
    return datetime.date.today()


def _load_lookup_maps(empresa_id: int):
    db = get_db()
    cursor = db.cursor(dictionary=True)
    try:
        cursor.execute(
            "SELECT id, legajo, sector_id FROM empleados WHERE empresa_id = %s AND activo = 1",
            (empresa_id,),
        )
        legajo_to_empleado = {
            str(r["legajo"]).strip(): {
                "id": int(r["id"]),
                "sector_id": int(r["sector_id"]) if r.get("sector_id") is not None else None,
            }
            for r in cursor.fetchall()
            if r["legajo"]
        }

        # Los codigos pueden repetirse entre sectores; el legajo define el sector correcto.
        cursor.execute(
            """
            SELECT k.id, k.codigo, k.sector_id
            FROM kpis_definicion k
            JOIN sectores s ON s.id = k.sector_id
            WHERE s.empresa_id = %s AND k.activo = 1
            """,
            (empresa_id,),
        )
        kpi_by_sector_codigo = {
            (int(r["sector_id"]), str(r["codigo"]).strip().upper()): int(r["id"])
            for r in cursor.fetchall()
            if r.get("sector_id") is not None and r["codigo"]
        }

        return legajo_to_empleado, kpi_by_sector_codigo
    finally:
        cursor.close()
        db.close()


def importar_resultados_desde_csv(empresa_id: int, stream) -> dict:
    today = _today()
    raw = stream.read()
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = raw.decode("latin-1")

    reader = csv.DictReader(io.StringIO(text))
    headers = {h.strip().lower() for h in (reader.fieldnames or [])}
    missing = _REQUIRED_HEADERS - headers
    if missing:
        raise KpiImportError(f"Columnas faltantes en el CSV: {', '.join(sorted(missing))}")

    legajo_map, kpi_map = _load_lookup_maps(empresa_id)

    rows_ok: list[tuple] = []
    errors: list[dict] = []
    empleados_mes_actual: set[int] = set()

    for lineno, raw_row in enumerate(reader, start=2):
        row = {k.strip().lower(): (v or "").strip() for k, v in raw_row.items()}

        fecha_str = row.get("fecha", "")
        legajo_str = row.get("legajo", "")
        codigo_kpi = row.get("codigo_kpi", "").upper()
        valor_str = row.get("valor", "")

        # --- validate fecha ---
        try:
            fecha = datetime.date.fromisoformat(fecha_str)
            if fecha > today:
                raise ValueError("fecha futura")
        except ValueError:
            errors.append({"linea": lineno, "error": f"Fecha invalida: '{fecha_str}'"})
            continue

        # --- validate legajo ---
        empleado = legajo_map.get(legajo_str)
        if not empleado:
            errors.append({"linea": lineno, "error": f"Legajo no encontrado o inactivo: '{legajo_str}'"})
            continue
        empleado_id = empleado["id"]
        sector_id = empleado.get("sector_id")
        if sector_id is None:
            errors.append({"linea": lineno, "error": f"Empleado sin sector asignado: '{legajo_str}'"})
            continue

        # --- validate kpi ---
        kpi_id = kpi_map.get((sector_id, codigo_kpi))
        if not kpi_id:
            errors.append({
                "linea": lineno,
                "error": f"Codigo KPI no encontrado o inactivo para el sector del empleado: '{codigo_kpi}'",
            })
            continue

        # --- validate valor ---
        try:
            valor = float(valor_str.replace(",", "."))
        except (ValueError, AttributeError):
            errors.append({"linea": lineno, "error": f"Valor invalido: '{valor_str}'"})
            continue

        rows_ok.append((empresa_id, empleado_id, kpi_id, fecha.isoformat(), valor))
        if fecha.year == today.year and fecha.month == today.month:
            empleados_mes_actual.add(empleado_id)

    imported = 0
    deleted_current_month = 0
    if rows_ok:
        if empleados_mes_actual:
            deleted_current_month = delete_resultados_mes_empleados(
                empresa_id,
                today.year,
                today.month,
                list(empleados_mes_actual),
            )
        bulk_upsert_resultados(rows_ok)
        imported = len(rows_ok)

    return {
        "total_filas": lineno - 1 if rows_ok or errors else 0,
        "importadas": imported,
        "limpiadas_mes_actual": deleted_current_month,
        "empleados_limpiados_mes_actual": len(empleados_mes_actual),
        "periodo_limpiado": f"{today.year}-{today.month:02d}" if empleados_mes_actual else None,
        "errores": len(errors),
        "detalle_errores": errors[:100],
    }
