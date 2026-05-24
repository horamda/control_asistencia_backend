import datetime
from decimal import Decimal

from repositories.vacaciones_repository import (
    count_dias_efectivamente_trabajados,
    create_movimiento,
    exists_movimiento_tomado_overlap,
    get_empleado_for_vacaciones,
    get_movimiento_by_id,
    get_movimientos_by_empleado_anio,
    mark_movimiento_revertido,
    update_movimiento,
    update_movimiento_estado,
)
from repositories.vacacion_repository import (
    create as create_legacy_vacacion,
    exists_by_empleado_rango as exists_legacy_vacacion_rango,
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


def _today() -> datetime.date:
    return datetime.date.today()


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
    estado = row.get("estado") or "aprobado"
    tipo = str(row.get("tipo") or "").strip().lower()
    es_reversion = _movimiento_es_reversion(row)
    afecta_saldo = (
        not es_reversion
        and estado in ("aprobado", "pendiente")
        and tipo in ("tomado", "compensatorio", "ajuste")
    )
    return {
        "id": row.get("id"),
        "tipo": tipo or None,
        "dias": _days_number(row.get("dias")),
        "fecha_desde": _to_date_str(row.get("fecha_desde")),
        "fecha_hasta": _to_date_str(row.get("fecha_hasta")),
        "estado": estado,
        "observacion": row.get("observacion"),
        "es_reversion": es_reversion,
        "afecta_saldo": afecta_saldo,
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
    fecha_baja = (
        _parse_date(empleado.get("fecha_baja"), "fecha_baja")
        if empleado.get("fecha_baja")
        else None
    )
    empresa_id = int(empleado["empresa_id"])
    anio = int(anio)

    inicio_anio = datetime.date(anio, 1, 1)
    fin_anio = datetime.date(anio, 12, 31)
    desde_trabajado = max(inicio_anio, fecha_ingreso)
    today = _today()
    fin_laboral = min(fin_anio, fecha_baja) if fecha_baja else fin_anio
    if anio > today.year and not fecha_baja:
        fin_evaluacion = None
    elif anio == today.year and (fecha_baja is None or fecha_baja > today):
        fin_evaluacion = min(fin_laboral, today)
    else:
        fin_evaluacion = fin_laboral

    dias_habiles_anio_total = _count_workdays(inicio_anio, fin_anio)
    # Contar desde el primer día efectivo de trabajo (no desde el 1 de enero).
    # Así el control proporcional compara contra "mitad de SU período", no del año completo.
    dias_habiles_evaluados = (
        _count_workdays(desde_trabajado, fin_evaluacion)
        if fin_evaluacion is not None and fin_evaluacion >= desde_trabajado
        else 0
    )
    dias_habiles_para_proporcional = (
        dias_habiles_evaluados
        if fin_evaluacion is not None and fin_evaluacion < fin_anio
        else _count_workdays(desde_trabajado, fin_anio)
    )
    hasta_trabajado = fin_evaluacion or fin_anio
    dias_trabajados_anio = count_dias_efectivamente_trabajados(
        empleado_id=int(empleado_id),
        empresa_id=empresa_id,
        fecha_desde=desde_trabajado.isoformat(),
        fecha_hasta=hasta_trabajado.isoformat(),
    ) if desde_trabajado <= hasta_trabajado else 0

    antiguedad = _antiguedad_al_31_12(fecha_ingreso, anio)
    dias_base = _dias_base_por_antiguedad(antiguedad)
    # Solo empleados con menos de un anio al 31/12 pasan a proporcional.
    aplica_control_proporcional = antiguedad < 1
    calculo_proporcional = (
        aplica_control_proporcional
        and dias_habiles_para_proporcional > 0
        and dias_trabajados_anio < (dias_habiles_para_proporcional / 2)
    )
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
        if _movimiento_es_reversion(row):
            continue
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

    # Porcentaje de días trabajados sobre el total posible del período evaluado.
    dias_habiles_ref = dias_habiles_para_proporcional
    if dias_habiles_ref > 0:
        pct_trabajados = round(dias_trabajados_anio / dias_habiles_ref * 100, 1)
    else:
        pct_trabajados = 100.0

    # Desglose legible de cómo se compone "días que corresponden".
    desglose = [{"concepto": "Base LCT", "dias": _days_number(dias_base)}]
    if dias_compensatorios:
        desglose.append({"concepto": "Compensatorios", "dias": _days_number(dias_compensatorios)})
    if dias_ajustes:
        desglose.append({"concepto": "Ajustes", "dias": _days_number(dias_ajustes)})

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
            "dias_habiles_anio": dias_habiles_para_proporcional,
            "dias_habiles_anio_total": dias_habiles_anio_total,
            "dias_habiles_evaluados": dias_habiles_evaluados,
            "dias_trabajados_anio": dias_trabajados_anio,
            "dias_trabajados_porcentaje": pct_trabajados,
            "umbral_proporcional_pct": 50.0,
            "fecha_evaluacion_trabajo": _to_date_str(hasta_trabajado),
            "aplica_control_proporcional": aplica_control_proporcional,
            "calculo_proporcional": calculo_proporcional,
            "dias_base": _days_number(dias_base),
            "dias_compensatorios": _days_number(dias_compensatorios),
            "dias_ajustes": _days_number(dias_ajustes),
            "dias_tomados": _days_number(dias_tomados),
            "dias_pendientes": _days_number(dias_pendientes),
            "dias_corresponden": _days_number(dias_corresponden),
            "dias_disponibles": _days_number(dias_disponibles),
            "dias_disponibles_con_pendientes": _days_number(dias_disponibles_con_pendientes),
            "desglose_corresponde": desglose,
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
    _validar_rango_tomado_sin_solape(
        empleado_id=int(empleado_id),
        fecha_desde=desde.isoformat(),
        fecha_hasta=hasta.isoformat(),
    )
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


TIPOS_MOVIMIENTO = {"tomado", "compensatorio", "ajuste"}
ESTADOS_MOVIMIENTO = {"pendiente", "aprobado", "rechazado"}


def _normalize_movimiento_tipo(value: str | None) -> str:
    tipo = str(value or "").strip().lower()
    if tipo not in TIPOS_MOVIMIENTO:
        raise VacacionesError("Tipo de movimiento invalido.")
    return tipo


def _normalize_movimiento_estado(value: str | None, *, default: str = "aprobado") -> str:
    estado = str(value or default).strip().lower()
    if estado not in ESTADOS_MOVIMIENTO:
        raise VacacionesError("Estado de movimiento invalido.")
    return estado


def _parse_dias(value, *, required: bool = True, allow_negative: bool = False):
    raw = str(value or "").strip()
    if not raw:
        if required:
            raise VacacionesError("Dias es requerido.")
        return None
    try:
        dias = Decimal(raw.replace(",", "."))
    except Exception as exc:
        raise VacacionesError("Dias invalido.") from exc
    if dias == 0 or (dias < 0 and not allow_negative):
        raise VacacionesError("Dias debe ser mayor a cero.")
    return dias


def _dias_calendario(desde: datetime.date, hasta: datetime.date) -> Decimal:
    return Decimal(str((hasta - desde).days + 1))


def _movimiento_es_reversion(row: dict) -> bool:
    return bool(row.get("revertido_por_movimiento_id") or row.get("origen_movimiento_id"))


def _validar_rango_tomado_sin_solape(
    *,
    empleado_id: int,
    fecha_desde: str,
    fecha_hasta: str,
    exclude_movimiento_id: int | None = None,
):
    if exists_movimiento_tomado_overlap(
        empleado_id=int(empleado_id),
        fecha_desde=fecha_desde,
        fecha_hasta=fecha_hasta,
        exclude_movimiento_id=exclude_movimiento_id,
    ):
        raise VacacionesError("Ya existe una solicitud o periodo aprobado que se superpone con esas fechas.")


def _ensure_legacy_vacacion_for_movimiento(row: dict):
    if str(row.get("tipo") or "").lower() != "tomado":
        return
    if _movimiento_es_reversion(row):
        return
    fecha_desde = _to_date_str(row.get("fecha_desde"))
    fecha_hasta = _to_date_str(row.get("fecha_hasta"))
    if not fecha_desde or not fecha_hasta:
        return
    empleado_id = int(row["empleado_id"])
    if exists_legacy_vacacion_rango(empleado_id, fecha_desde, fecha_hasta):
        return
    create_legacy_vacacion(
        {
            "empleado_id": empleado_id,
            "empresa_id": row.get("empresa_id"),
            "fecha_desde": fecha_desde,
            "fecha_hasta": fecha_hasta,
            "observaciones": row.get("observacion") or "Vacaciones aprobadas desde movimientos",
        }
    )


def crear_movimiento_vacaciones_admin(data: dict) -> int:
    empleado_id = int(data.get("empleado_id") or 0)
    if not empleado_id:
        raise VacacionesError("Empleado es requerido.")

    empleado = _get_empleado_activo(empleado_id)
    anio = int(data.get("anio") or 0)
    if anio < 2000 or anio > 2100:
        raise VacacionesError("Anio invalido.")

    tipo = _normalize_movimiento_tipo(data.get("tipo"))
    estado = _normalize_movimiento_estado(data.get("estado"))
    observacion = str(data.get("observacion") or "").strip() or None
    fecha_desde = None
    fecha_hasta = None

    if tipo == "tomado":
        desde = _parse_date(data.get("fecha_desde"), "fecha_desde")
        hasta = _parse_date(data.get("fecha_hasta"), "fecha_hasta")
        if desde > hasta:
            raise VacacionesError("fecha_desde no puede ser posterior a fecha_hasta.")
        if desde.year != anio or hasta.year != anio:
            raise VacacionesError("Las fechas deben pertenecer al anio del movimiento.")
        fecha_desde = desde.isoformat()
        fecha_hasta = hasta.isoformat()
        if estado != "rechazado":
            _validar_rango_tomado_sin_solape(
                empleado_id=empleado_id,
                fecha_desde=fecha_desde,
                fecha_hasta=fecha_hasta,
            )
        dias = _parse_dias(data.get("dias"), required=False)
        if dias is None:
            dias = _dias_calendario(desde, hasta)
        elif dias != _dias_calendario(desde, hasta):
            raise VacacionesError("Dias debe coincidir con el rango de fechas.")
    else:
        dias = _parse_dias(data.get("dias"), allow_negative=(tipo == "ajuste"))

    if tipo == "tomado" and estado != "rechazado":
        resumen = calcular_resumen_vacaciones(empleado_id, anio)["vacaciones"]
        saldo_key = "dias_disponibles" if estado == "aprobado" else "dias_disponibles_con_pendientes"
        saldo = Decimal(str(resumen.get(saldo_key) or 0))
        if dias > saldo:
            raise VacacionesSaldoInsuficienteError("Saldo de vacaciones insuficiente.")

    movimiento_id = create_movimiento(
        {
            "empleado_id": empleado_id,
            "empresa_id": int(empleado["empresa_id"]),
            "anio": anio,
            "tipo": tipo,
            "dias": dias,
            "observacion": observacion,
            "fecha_desde": fecha_desde,
            "fecha_hasta": fecha_hasta,
            "estado": estado,
        }
    )

    if estado == "aprobado":
        row = get_movimiento_by_id(movimiento_id)
        if row:
            _ensure_legacy_vacacion_for_movimiento(row)
    return movimiento_id


def editar_movimiento_vacaciones_pendiente(movimiento_id: int, data: dict) -> None:
    row = get_movimiento_by_id(movimiento_id)
    if not row:
        raise VacacionesError("Movimiento de vacaciones no encontrado.")
    estado_actual = str(row.get("estado") or "aprobado").lower()
    if estado_actual != "pendiente":
        raise VacacionesError("Solo se pueden editar movimientos pendientes.")

    empleado_id = int(data.get("empleado_id") or 0)
    if not empleado_id:
        raise VacacionesError("Empleado es requerido.")
    empleado = _get_empleado_activo(empleado_id)

    anio = int(data.get("anio") or 0)
    if anio < 2000 or anio > 2100:
        raise VacacionesError("Anio invalido.")

    tipo = _normalize_movimiento_tipo(data.get("tipo"))
    observacion = str(data.get("observacion") or "").strip() or None
    fecha_desde = None
    fecha_hasta = None

    if tipo == "tomado":
        desde = _parse_date(data.get("fecha_desde"), "fecha_desde")
        hasta = _parse_date(data.get("fecha_hasta"), "fecha_hasta")
        if desde > hasta:
            raise VacacionesError("fecha_desde no puede ser posterior a fecha_hasta.")
        if desde.year != anio or hasta.year != anio:
            raise VacacionesError("Las fechas deben pertenecer al anio del movimiento.")
        fecha_desde = desde.isoformat()
        fecha_hasta = hasta.isoformat()
        _validar_rango_tomado_sin_solape(
            empleado_id=empleado_id,
            fecha_desde=fecha_desde,
            fecha_hasta=fecha_hasta,
            exclude_movimiento_id=int(movimiento_id),
        )
        dias = _parse_dias(data.get("dias"), required=False)
        if dias is None:
            dias = _dias_calendario(desde, hasta)
        elif dias != _dias_calendario(desde, hasta):
            raise VacacionesError("Dias debe coincidir con el rango de fechas.")

        resumen = calcular_resumen_vacaciones(empleado_id, anio)["vacaciones"]
        saldo_reservado = Decimal(str(resumen.get("dias_disponibles_con_pendientes") or 0))
        if (
            int(row.get("empleado_id") or 0) == empleado_id
            and str(row.get("tipo") or "").lower() == "tomado"
            and int(row.get("anio") or 0) == anio
            and not _movimiento_es_reversion(row)
        ):
            saldo_reservado += Decimal(str(row.get("dias") or 0))
        if dias > saldo_reservado:
            raise VacacionesSaldoInsuficienteError("Saldo de vacaciones insuficiente.")
    else:
        dias = _parse_dias(data.get("dias"), allow_negative=(tipo == "ajuste"))

    update_movimiento(
        movimiento_id,
        {
            "empleado_id": empleado_id,
            "empresa_id": int(empleado["empresa_id"]),
            "anio": anio,
            "tipo": tipo,
            "dias": dias,
            "observacion": observacion,
            "fecha_desde": fecha_desde,
            "fecha_hasta": fecha_hasta,
            "estado": "pendiente",
        },
    )


def aprobar_movimiento_vacaciones(movimiento_id: int, *, actor_id: int | None = None) -> None:
    row = get_movimiento_by_id(movimiento_id)
    if not row:
        raise VacacionesError("Movimiento de vacaciones no encontrado.")
    estado_actual = str(row.get("estado") or "aprobado").lower()
    if estado_actual != "pendiente":
        raise VacacionesError(f"No se puede aprobar un movimiento en estado '{estado_actual}'.")

    if str(row.get("tipo") or "").lower() == "tomado":
        _validar_rango_tomado_sin_solape(
            empleado_id=int(row["empleado_id"]),
            fecha_desde=_to_date_str(row.get("fecha_desde")),
            fecha_hasta=_to_date_str(row.get("fecha_hasta")),
            exclude_movimiento_id=int(movimiento_id),
        )
        resumen = calcular_resumen_vacaciones(int(row["empleado_id"]), int(row["anio"]))["vacaciones"]
        saldo = Decimal(str(resumen.get("dias_disponibles") or 0))
        dias = Decimal(str(row.get("dias") or 0))
        if dias > saldo:
            raise VacacionesSaldoInsuficienteError("Saldo de vacaciones insuficiente.")

    if not update_movimiento_estado(
        movimiento_id,
        "aprobado",
        actor_id=actor_id,
        expected_estado="pendiente",
    ):
        raise VacacionesError("El movimiento ya fue resuelto.")
    row = get_movimiento_by_id(movimiento_id)
    if row:
        _ensure_legacy_vacacion_for_movimiento(row)


def cancelar_movimiento_vacaciones(
    movimiento_id: int,
    *,
    actor_id: int | None = None,
    motivo: str | None = None,
) -> int:
    motivo = str(motivo or "").strip()
    if not motivo:
        raise VacacionesError("Motivo de cancelacion es requerido.")

    row = get_movimiento_by_id(movimiento_id)
    if not row:
        raise VacacionesError("Movimiento de vacaciones no encontrado.")
    estado_actual = str(row.get("estado") or "aprobado").lower()
    if estado_actual != "aprobado":
        raise VacacionesError(f"No se puede cancelar un movimiento en estado '{estado_actual}'.")
    if _movimiento_es_reversion(row):
        raise VacacionesError("El movimiento ya fue revertido o es una reversion.")

    tipo = str(row.get("tipo") or "").lower()
    dias_originales = Decimal(str(row.get("dias") or 0))
    if tipo == "tomado":
        dias_ajuste = dias_originales
    elif tipo in {"compensatorio", "ajuste"}:
        dias_ajuste = -dias_originales
    else:
        raise VacacionesError("Tipo de movimiento invalido.")

    observacion = f"Reversion movimiento #{movimiento_id}: {motivo}"
    ajuste_id = create_movimiento(
        {
            "empleado_id": int(row["empleado_id"]),
            "empresa_id": int(row["empresa_id"]),
            "anio": int(row["anio"]),
            "tipo": "ajuste",
            "dias": dias_ajuste,
            "observacion": observacion[:255],
            "fecha_desde": None,
            "fecha_hasta": None,
            "estado": "aprobado",
            "origen_movimiento_id": int(movimiento_id),
        }
    )
    mark_movimiento_revertido(
        movimiento_id,
        ajuste_id=ajuste_id,
        actor_id=actor_id,
        motivo=motivo,
    )
    return ajuste_id


def crear_compensatorios_bulk(
    *,
    empleado_ids: list[int],
    dias,
    anio: int,
    observacion: str | None = None,
) -> tuple[int, list[dict]]:
    """Crea movimientos compensatorios aprobados para múltiples empleados.
    Devuelve (cantidad_ok, lista_de_errores).
    """
    if not empleado_ids:
        raise VacacionesError("Seleccione al menos un empleado.")
    dias_d = _parse_dias(str(dias))
    if anio < 2000 or anio > 2100:
        raise VacacionesError("Anio invalido.")
    obs = str(observacion or "").strip() or None

    ok = 0
    errors: list[dict] = []
    for eid in empleado_ids:
        try:
            empleado = _get_empleado_activo(int(eid))
            create_movimiento({
                "empleado_id": int(eid),
                "empresa_id": int(empleado["empresa_id"]),
                "anio": anio,
                "tipo": "compensatorio",
                "dias": dias_d,
                "observacion": obs,
                "fecha_desde": None,
                "fecha_hasta": None,
                "estado": "aprobado",
            })
            ok += 1
        except VacacionesError as exc:
            errors.append({"empleado_id": eid, "error": str(exc)})
        except Exception as exc:
            errors.append({"empleado_id": eid, "error": f"Error inesperado: {exc}"})
    return ok, errors


def editar_movimiento_vacaciones_aprobado(movimiento_id: int, data: dict) -> None:
    """Edita fechas de un movimiento tomado/aprobado. Uso exclusivo del Gantt."""
    row = get_movimiento_by_id(movimiento_id)
    if not row:
        raise VacacionesError("Movimiento de vacaciones no encontrado.")
    if str(row.get("estado") or "").lower() != "aprobado":
        raise VacacionesError("Solo se pueden editar movimientos aprobados con esta función.")
    if _movimiento_es_reversion(row):
        raise VacacionesError("El movimiento fue revertido y no se puede editar.")
    if str(row.get("tipo") or "").lower() != "tomado":
        raise VacacionesError("Solo se pueden editar movimientos de tipo 'tomado'.")

    empleado_id = int(row["empleado_id"])
    empleado = _get_empleado_activo(empleado_id)
    anio = int(row["anio"])

    desde = _parse_date(data.get("fecha_desde"), "fecha_desde")
    hasta = _parse_date(data.get("fecha_hasta"), "fecha_hasta")
    if desde > hasta:
        raise VacacionesError("fecha_desde no puede ser posterior a fecha_hasta.")
    if desde.year != anio or hasta.year != anio:
        raise VacacionesError("Las fechas deben pertenecer al anio del movimiento.")

    fecha_desde = desde.isoformat()
    fecha_hasta = hasta.isoformat()
    _validar_rango_tomado_sin_solape(
        empleado_id=empleado_id,
        fecha_desde=fecha_desde,
        fecha_hasta=fecha_hasta,
        exclude_movimiento_id=int(movimiento_id),
    )

    dias = _dias_calendario(desde, hasta)
    dias_originales = Decimal(str(row.get("dias") or 0))

    resumen = calcular_resumen_vacaciones(empleado_id, anio)["vacaciones"]
    saldo = Decimal(str(resumen.get("dias_disponibles") or 0)) + dias_originales
    if dias > saldo:
        raise VacacionesSaldoInsuficienteError("Saldo de vacaciones insuficiente.")

    update_movimiento(
        movimiento_id,
        {
            "empleado_id": empleado_id,
            "empresa_id": int(empleado["empresa_id"]),
            "anio": anio,
            "tipo": "tomado",
            "dias": dias,
            "observacion": data.get("observacion") or row.get("observacion"),
            "fecha_desde": fecha_desde,
            "fecha_hasta": fecha_hasta,
            "estado": "aprobado",
        },
    )


def rechazar_movimiento_vacaciones(
    movimiento_id: int,
    *,
    actor_id: int | None = None,
    motivo: str | None = None,
) -> None:
    motivo = str(motivo or "").strip()
    if not motivo:
        raise VacacionesError("Motivo de rechazo es requerido.")
    row = get_movimiento_by_id(movimiento_id)
    if not row:
        raise VacacionesError("Movimiento de vacaciones no encontrado.")
    estado_actual = str(row.get("estado") or "aprobado").lower()
    if estado_actual != "pendiente":
        raise VacacionesError(f"No se puede rechazar un movimiento en estado '{estado_actual}'.")
    if not update_movimiento_estado(
        movimiento_id,
        "rechazado",
        actor_id=actor_id,
        motivo=motivo,
        expected_estado="pendiente",
    ):
        raise VacacionesError("El movimiento ya fue resuelto.")
