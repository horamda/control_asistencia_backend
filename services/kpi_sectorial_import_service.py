"""
Importacion de resultados diarios de KPIs desde CSV.

Formato esperado del CSV:
  fecha,legajo,codigo_kpi,valor

- fecha: YYYY-MM-DD
- legajo: legajo del empleado (unico por empresa)
- codigo_kpi: codigo del KPI segun kpis_definicion
- valor: numero decimal (punto como separador)

El CSV debe corresponder a una sola empresa (empresa_id se pasa como param).
"""

import csv
import datetime
import io

from extensions import get_db
from repositories.kpi_sectorial_repository import bulk_upsert_resultados

_REQUIRED_HEADERS = {"fecha", "legajo", "codigo_kpi", "valor"}


class KpiImportError(ValueError):
    pass


def _load_lookup_maps(empresa_id: int):
    db = get_db()
    cursor = db.cursor(dictionary=True)
    try:
        cursor.execute(
            "SELECT id, legajo FROM empleados WHERE empresa_id = %s AND activo = 1",
            (empresa_id,),
        )
        legajo_to_id = {str(r["legajo"]).strip(): int(r["id"]) for r in cursor.fetchall() if r["legajo"]}

        # KPIs buscados por codigo dentro de los sectores de la empresa
        cursor.execute(
            """
            SELECT k.id, k.codigo
            FROM kpis_definicion k
            JOIN sectores s ON s.id = k.sector_id
            WHERE s.empresa_id = %s AND k.activo = 1
            """,
            (empresa_id,),
        )
        codigo_to_id = {str(r["codigo"]).strip().upper(): int(r["id"]) for r in cursor.fetchall()}

        return legajo_to_id, codigo_to_id
    finally:
        cursor.close()
        db.close()


def importar_resultados_desde_csv(empresa_id: int, stream) -> dict:
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

    for lineno, raw_row in enumerate(reader, start=2):
        row = {k.strip().lower(): (v or "").strip() for k, v in raw_row.items()}

        fecha_str = row.get("fecha", "")
        legajo_str = row.get("legajo", "")
        codigo_kpi = row.get("codigo_kpi", "").upper()
        valor_str = row.get("valor", "")

        # --- validate fecha ---
        try:
            fecha = datetime.date.fromisoformat(fecha_str)
            if fecha > datetime.date.today():
                raise ValueError("fecha futura")
        except ValueError:
            errors.append({"linea": lineno, "error": f"Fecha invalida: '{fecha_str}'"})
            continue

        # --- validate legajo ---
        empleado_id = legajo_map.get(legajo_str)
        if not empleado_id:
            errors.append({"linea": lineno, "error": f"Legajo no encontrado o inactivo: '{legajo_str}'"})
            continue

        # --- validate kpi ---
        kpi_id = kpi_map.get(codigo_kpi)
        if not kpi_id:
            errors.append({"linea": lineno, "error": f"Codigo KPI no encontrado o inactivo: '{codigo_kpi}'"})
            continue

        # --- validate valor ---
        try:
            valor = float(valor_str.replace(",", "."))
        except (ValueError, AttributeError):
            errors.append({"linea": lineno, "error": f"Valor invalido: '{valor_str}'"})
            continue

        rows_ok.append((empresa_id, empleado_id, kpi_id, fecha.isoformat(), valor))

    imported = 0
    if rows_ok:
        bulk_upsert_resultados(rows_ok)
        imported = len(rows_ok)

    return {
        "total_filas": lineno - 1 if rows_ok or errors else 0,
        "importadas": imported,
        "errores": len(errors),
        "detalle_errores": errors[:100],
    }
