import datetime
from decimal import Decimal

from repositories.vacaciones_repository import (
    count_dias_efectivamente_trabajados,
    create_movimiento,
    get_empleado_for_vacaciones,
    get_movimientos_by_empleado_anio,
)


class VacacionesError(ValueError):
    pass


class VacacionesSaldoInsuficienteError(VacacionesError):
    pass


def _parse_date(value, field_name: str = "fecha") -> datetime.date:
    if isinstance(value, datetime.datetime):
        return value.date()
    if isinstance(value, datetime.date):
        return value
    raw = str(value or "").strip()
    if not raw:
        raise VacacionesError(f"{field_name} es requerida.")
    try:
        return datetime.date.fromisoformat(raw[:10])
    except ValueError as exc:
        raise VacacionesError(f"{field_name} invalida. Use YYYY-MM-DD.") from exc


def _to_date_str(value):
    if value is None:
        return None
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)


def _days_number(value):
    decimal_value = Decimal(str(value or 0))
    if decimal_value == decimal_value.to_integral_value():
        return int(decimal_value)
    return float(decimal_value)


def _count_workdays(desde: datetime.date, hasta: datetime.date) -> int:
    if hasta < desde:
        return 0
    current = desde
    total = 0
    while current <= hasta:
        if current.weekday() < 5:
            total += 1
        current += datetime.timedelta(days=1)
    return total


def _antiguedad_al_31_12(fecha_ingreso: datetime.date, anio: int) -> int:
    cierre = datetime.date(int(anio), 12, 31)
    if fecha_ingreso > cierre:
        return 0
    years = cierre.year - fecha_ingreso.year
    if (cierre.month, cierre.day) < (fecha_ingreso.month, fecha_ingreso.day):
        years -= 1
    return max(0, years)


def _dias_base_por_antiguedad(antiguedad: int) -> int:
    if antiguedad <= 5:
        return 14
    if antiguedad <= 10:
        return 21
    if antiguedad <= 20:
        return 28
    return 35


def _empleado_nombre(empleado: dict) -> str:
    parts = [empleado.get("nombre"), empleado.get("apellido")]
    return " ".join(str(part).strip() for part in parts if str(part or "").strip())


def _movimiento_to_dict(row: dict) -> dict:
    return {
        "id": row.get("id"),
        "tipo": row.get("tipo"),
        "dias": _days_number(row.get("dias")),
        "fecha_desde": _to_date_str(row.get("fecha_desde")),
        "fecha_hasta": _to_date_str(row.get("fecha_hasta")),
        "estado": row.get("estado") or "aprobado",
        "observacion": row.get("observacion"),
    }


def listar_movimientos_vacaciones(empleado_id: int, anio: int) -> dict:
    empleado = _get_empleado_activo(empleado_id)
    movimientos = get_movimientos_by_empleado_anio(
        empleado_id=int(empleado_id),
        empresa_id=int(empleado["empresa_id"]),
        anio=int(anio),
    )
    return {
        "anio": int(anio),
        "movimientos": [_movimiento_to_dict(row) for row in movimientos],
    }


def _get_empleado_activo(empleado_id: int) -> dict:
    empleado = get_empleado_for_vacaciones(int(empleado_id))
    if not empleado or not empleado.get("activo"):
        raise VacacionesError("Empleado no encontrado o inactivo.")
    if not empleado.get("empresa_id"):
        raise VacacionesError("Empleado invalido o sin empresa asignada.")
    return empleado


def calcular_resumen_vacaciones(empleado_id: int, anio: int) -> dict:
    empleado = _get_empleado_activo(empleado_id)
    fecha_ingreso = _parse_date(empleado.get("fecha_ingreso"), "fecha_ingreso")
    empresa_id = int(empleado["empresa_id"])
    anio = int(anio)

    inicio_anio = datetime.date(anio, 1, 1)
    fin_anio = datetime.date(anio, 12, 31)
    desde_trabajado = max(inicio_anio, fecha_ingreso)
    dias_habiles_anio = _count_workdays(inicio_anio, fin_anio)
    dias_trabajados_anio = count_dias_efectivamente_trabajados(
        empleado_id=int(empleado_id),
        empresa_id=empresa_id,
        fecha_desde=desde_trabajado.isoformat(),
        fecha_hasta=fin_anio.isoformat(),
    )

    antiguedad = _antiguedad_al_31_12(fecha_ingreso, anio)
    dias_base = _dias_base_por_antiguedad(antiguedad)
    calculo_proporcional = dias_trabajados_anio < (dias_habiles_anio / 2)
    if calculo_proporcional:
        dias_base = dias_trabajados_anio // 20

    movimientos = get_movimientos_by_empleado_anio(
        empleado_id=int(empleado_id),
        empresa_id=empresa_id,
        anio=anio,
    )

    dias_compensatorios = Decimal("0")
    dias_ajustes = Decimal("0")
    dias_tomados = Decimal("0")
    dias_pendientes = Decimal("0")

    for row in movimientos:
        tipo = str(row.get("tipo") or "").strip().lower()
        estado = str(row.get("estado") or "aprobado").strip().lower()
        dias = Decimal(str(row.get("dias") or 0))

        if estado == "aprobado":
            if tipo == "compensatorio":
                dias_compensatorios += dias
            elif tipo == "ajuste":
                dias_ajustes += dias
            elif tipo == "tomado":
                dias_tomados += dias
        elif estado == "pendiente" and tipo == "tomado":
            dias_pendientes += dias

    dias_corresponden = Decimal(str(dias_base)) + dias_compensatorios + dias_ajustes
    dias_disponibles = dias_corresponden - dias_tomados
    dias_disponibles_con_pendientes = dias_disponibles - dias_pendientes

    return {
        "anio": anio,
        "empleado": {
            "id": empleado.get("id"),
            "dni": empleado.get("dni"),
            "nombre": _empleado_nombre(empleado),
        },
        "vacaciones": {
            "fecha_ingreso": fecha_ingreso.isoformat(),
            "antiguedad_al_31_12": antiguedad,
            "dias_habiles_anio": dias_habiles_anio,
            "dias_trabajados_anio": dias_trabajados_anio,
            "calculo_proporcional": calculo_proporcional,
            "dias_base": _days_number(dias_base),
            "dias_compensatorios": _days_number(dias_compensatorios),
            "dias_ajustes": _days_number(dias_ajustes),
            "dias_tomados": _days_number(dias_tomados),
            "dias_pendientes": _days_number(dias_pendientes),
            "dias_corresponden": _days_number(dias_corresponden),
            "dias_disponibles": _days_number(dias_disponibles),
            "dias_disponibles_con_pendientes": _days_number(dias_disponibles_con_pendientes),
        },
    }


def solicitar_vacaciones(
    *,
    empleado_id: int,
    fecha_desde: str,
    fecha_hasta: str,
    observacion: str | None = None,
) -> dict:
    desde = _parse_date(fecha_desde, "fecha_desde")
    hasta = _parse_date(fecha_hasta, "fecha_hasta")
    if desde > hasta:
        raise VacacionesError("fecha_desde no puede ser posterior a fecha_hasta.")
    if desde.year != hasta.year:
        raise VacacionesError("La solicitud debe estar contenida dentro del mismo anio.")

    dias_solicitados = (hasta - desde).days + 1
    resumen = calcular_resumen_vacaciones(int(empleado_id), desde.year)
    vacaciones = resumen["vacaciones"]
    saldo_reservado = Decimal(str(vacaciones.get("dias_disponibles_con_pendientes", 0)))

    if Decimal(str(dias_solicitados)) > saldo_reservado:
        raise VacacionesSaldoInsuficienteError("Saldo de vacaciones insuficiente.")

    movimiento_id = create_movimiento(
        {
            "empleado_id": int(empleado_id),
            "empresa_id": int(_get_empleado_activo(empleado_id)["empresa_id"]),
            "anio": desde.year,
            "tipo": "tomado",
            "dias": dias_solicitados,
            "observacion": (observacion or "").strip() or None,
            "fecha_desde": desde.isoformat(),
            "fecha_hasta": hasta.isoformat(),
            "estado": "pendiente",
        }
    )

    return {
        "id": movimiento_id,
        "anio": desde.year,
        "dias_solicitados": dias_solicitados,
        "estado": "pendiente",
        "fecha_desde": desde.isoformat(),
        "fecha_hasta": hasta.isoformat(),
    }
