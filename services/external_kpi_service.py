"""Carga incremental: valida todo el lote antes de escribir, sin limpiar meses."""
import datetime
from decimal import Decimal, InvalidOperation

from repositories.kpi_sectorial_repository import bulk_upsert_resultados
from services.kpi_sectorial_import_service import _load_lookup_maps

MAX_RESULTADOS = 1000


class KpiBatchError(ValueError):
    def __init__(self, message, *, errors=None, status=400):
        super().__init__(message)
        self.errors = errors or []
        self.status = status


def _valor(raw):
    if isinstance(raw, bool) or not isinstance(raw, (int, float, str)):
        raise ValueError("valor debe ser un numero decimal.")
    text = str(raw).strip()
    if not text or len(text) > 100:
        raise ValueError("valor invalido.")
    try:
        value = Decimal(text)
        if not value.is_finite() or abs(value) > Decimal("9999999999.9999"):
            raise ValueError("valor debe ser finito y estar entre -9999999999.9999 y 9999999999.9999.")
        if value != value.quantize(Decimal("0.0001")):
            raise ValueError("valor admite hasta 4 decimales.")
    except InvalidOperation as exc:
        raise ValueError("valor debe ser decimal, con punto como separador.") from exc
    return value


def guardar_resultados_kpi(payload):
    if not isinstance(payload, dict):
        raise KpiBatchError("El cuerpo debe ser un objeto JSON.")
    empresa_id = payload.get("empresa_id")
    if type(empresa_id) is not int or not 1 <= empresa_id <= 2147483647:
        raise KpiBatchError("empresa_id debe ser un entero positivo.")
    resultados = payload.get("resultados")
    if not isinstance(resultados, list) or not 1 <= len(resultados) <= MAX_RESULTADOS:
        raise KpiBatchError("resultados debe contener entre 1 y 1000 filas.")

    empleados, kpis = _load_lookup_maps(empresa_id)
    today = datetime.date.today()
    prepared, errors, seen = [], [], set()
    for index, row in enumerate(resultados, start=1):
        try:
            if not isinstance(row, dict):
                raise ValueError("Cada resultado debe ser un objeto JSON.")
            fecha_raw = row.get("fecha")
            if not isinstance(fecha_raw, str) or len(fecha_raw) != 10:
                raise ValueError("fecha debe tener formato YYYY-MM-DD.")
            try:
                fecha = datetime.date.fromisoformat(fecha_raw)
            except ValueError as exc:
                raise ValueError("fecha invalida; use YYYY-MM-DD.") from exc
            if fecha.isoformat() != fecha_raw or fecha.year < 1000 or fecha > today:
                raise ValueError("fecha invalida o futura.")
            legajo = row.get("legajo")
            if not isinstance(legajo, str) or not legajo.strip():
                raise ValueError("legajo debe ser un texto no vacio.")
            empleado = empleados.get(legajo.strip())
            if not empleado:
                raise ValueError("Legajo no encontrado o inactivo en la empresa seleccionada.")
            if empleado.get("sector_id") is None:
                raise ValueError("Empleado sin sector asignado.")
            codigo = row.get("codigo_kpi")
            if not isinstance(codigo, str) or not codigo.strip():
                raise ValueError("codigo_kpi debe ser un texto no vacio.")
            kpi_id = kpis.get((empleado["sector_id"], codigo.strip().upper()))
            if not kpi_id:
                raise ValueError("KPI no encontrado o inactivo para el sector del empleado.")
            valor = _valor(row.get("valor"))
            key = (empleado["id"], kpi_id, fecha_raw)
            if key in seen:
                raise ValueError("Empleado, KPI y fecha repetidos dentro del lote.")
            seen.add(key)
            prepared.append((empresa_id, empleado["id"], kpi_id, fecha_raw, valor))
        except ValueError as exc:
            errors.append({"fila": index, "error": str(exc)})
    if errors:
        raise KpiBatchError("Lote rechazado. Corrija las filas indicadas y reenvie el lote completo.",
                            errors=errors, status=422)
    bulk_upsert_resultados(prepared)
    return {"empresa_id": empresa_id, "recibidos": len(resultados), "guardados": len(prepared)}
