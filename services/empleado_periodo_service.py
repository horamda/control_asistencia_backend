"""Periodos laborales del empleado: alta, baja, reingreso y edicion de fechas.

Un empleado puede tener varios periodos (se fue y volvio). Su fecha_ingreso
queda como ingreso original (antiguedad) y fecha_baja refleja el fin del
ultimo periodo. Las estadisticas usan los periodos, no el estado actual: una
baja conserva su historia y el intervalo hasta un reingreso no suma faltas.

Las funciones plan_* son puras: reciben los periodos actuales y devuelven
como deben quedar, o levantan PeriodoLaboralError si las fechas no cierran.
"""
import datetime as dt

ESTADOS_ACTIVOS = ("activo", "eventual")
_COLUMNAS = ("id", "fecha_desde", "fecha_hasta")


class PeriodoLaboralError(ValueError):
    pass


def _fecha(value):
    if value in (None, ""):
        return None
    if isinstance(value, dt.datetime):
        return value.date()
    if isinstance(value, dt.date):
        return value
    try:
        return dt.date.fromisoformat(str(value)[:10])
    except ValueError:
        raise PeriodoLaboralError(f"Fecha invalida: {value}.") from None


def _fmt(value: dt.date) -> str:
    return value.strftime("%d/%m/%Y")


def _copia(periodos) -> list[dict]:
    return [
        {"id": p.get("id"), "desde": _fecha(p.get("fecha_desde")), "hasta": _fecha(p.get("fecha_hasta"))}
        for p in periodos
    ]


def _cerrar(periodos: list[dict], fecha: dt.date, fecha_ingreso: dt.date | None) -> None:
    """Fija la baja en el ultimo periodo, o crea el unico si no hay ninguno."""
    if not periodos:
        desde = fecha_ingreso if fecha_ingreso and fecha_ingreso <= fecha else None
        periodos.append({"id": None, "desde": desde, "hasta": fecha})
        return
    ultimo = periodos[-1]
    if ultimo["desde"] and fecha < ultimo["desde"]:
        raise PeriodoLaboralError(
            f"La fecha de baja ({_fmt(fecha)}) no puede ser anterior al inicio del periodo ({_fmt(ultimo['desde'])})."
        )
    ultimo["hasta"] = fecha


def _abrir(periodos: list[dict], fecha: dt.date, hasta: dt.date | None = None) -> None:
    """Agrega un periodo nuevo desde `fecha`, salvo que ya haya uno vigente."""
    if periodos and periodos[-1]["hasta"] is None:
        return
    if periodos and fecha <= periodos[-1]["hasta"]:
        raise PeriodoLaboralError(
            f"La fecha de reingreso ({_fmt(fecha)}) debe ser posterior a la ultima baja ({_fmt(periodos[-1]['hasta'])})."
        )
    periodos.append({"id": None, "desde": fecha, "hasta": hasta})


def plan_alta(data: dict) -> list[dict]:
    ingreso = _fecha(data.get("fecha_ingreso"))
    baja = _fecha(data.get("fecha_baja"))
    if ingreso and baja and baja < ingreso:
        raise PeriodoLaboralError("La fecha de baja no puede ser anterior a la fecha de ingreso.")
    activo = (data.get("estado") or "activo") in ESTADOS_ACTIVOS
    if not activo and baja is None:
        return []
    return [{"id": None, "desde": ingreso, "hasta": baja}]


def plan_baja(periodos, fecha, fecha_ingreso=None) -> list[dict]:
    resultado = _copia(periodos)
    _cerrar(resultado, _fecha(fecha), _fecha(fecha_ingreso))
    return resultado


def plan_reingreso(periodos, fecha) -> list[dict]:
    resultado = _copia(periodos)
    _abrir(resultado, _fecha(fecha))
    return resultado


def plan_edicion(periodos, antes: dict, despues: dict, *, fecha_reingreso=None, hoy=None) -> tuple[list[dict], dt.date | None]:
    """Periodos tras editar el empleado y la fecha_baja que debe guardarse."""
    resultado = _copia(periodos)
    hoy = hoy or dt.date.today()
    antes_activo = int(antes.get("activo") or 0) == 1
    despues_activo = (despues.get("estado") or "activo") in ESTADOS_ACTIVOS
    ingreso = _fecha(despues.get("fecha_ingreso"))
    baja = _fecha(despues.get("fecha_baja"))
    baja_cambio = baja != _fecha(antes.get("fecha_baja"))

    if ingreso and ingreso != _fecha(antes.get("fecha_ingreso")) and resultado:
        primero = resultado[0]
        if primero["hasta"] and ingreso > primero["hasta"]:
            raise PeriodoLaboralError(
                f"La fecha de ingreso ({_fmt(ingreso)}) no puede ser posterior a la baja del primer periodo "
                f"({_fmt(primero['hasta'])}). Para un reingreso usa la fecha de reingreso."
            )
        primero["desde"] = ingreso

    if antes_activo and not despues_activo:
        if baja is None:
            raise PeriodoLaboralError(
                "Para pasar el empleado a inactivo o suspendido indica la fecha de baja (ultimo dia trabajado)."
            )
        _cerrar(resultado, baja, ingreso)
    elif despues_activo and not antes_activo:
        reingreso = _fecha(fecha_reingreso) or hoy
        # Una baja anterior al reingreso es la del periodo viejo: se limpia.
        baja = baja if baja and baja >= reingreso else None
        _abrir(resultado, reingreso, baja)
    elif despues_activo:
        if not resultado:
            resultado.append({"id": None, "desde": ingreso, "hasta": baja})
        elif baja_cambio:
            ultimo = resultado[-1]
            if baja and ultimo["desde"] and baja < ultimo["desde"]:
                raise PeriodoLaboralError(
                    f"La fecha de baja ({_fmt(baja)}) no puede ser anterior al inicio del periodo ({_fmt(ultimo['desde'])})."
                )
            ultimo["hasta"] = baja
    elif baja and baja_cambio:
        _cerrar(resultado, baja, ingreso)
    return resultado, baja


def get_periodos(cursor, empleado_id: int) -> list[dict]:
    cursor.execute(
        """
        SELECT id, fecha_desde, fecha_hasta
        FROM empleado_periodos_laborales
        WHERE empleado_id = %s
        ORDER BY fecha_desde IS NOT NULL, fecha_desde, id
        """,
        (empleado_id,),
    )
    return [row if isinstance(row, dict) else dict(zip(_COLUMNAS, row)) for row in cursor.fetchall() or []]


def aplicar(cursor, empleado_id: int, originales, resultado: list[dict]) -> None:
    """Escribe solo los periodos nuevos o modificados respecto de `originales`."""
    previos = {p["id"]: (p["desde"], p["hasta"]) for p in _copia(originales)}
    for periodo in resultado:
        if periodo["id"] is None:
            cursor.execute(
                "INSERT INTO empleado_periodos_laborales (empleado_id, fecha_desde, fecha_hasta) VALUES (%s, %s, %s)",
                (empleado_id, periodo["desde"], periodo["hasta"]),
            )
        elif previos.get(periodo["id"]) != (periodo["desde"], periodo["hasta"]):
            cursor.execute(
                "UPDATE empleado_periodos_laborales SET fecha_desde = %s, fecha_hasta = %s WHERE id = %s AND empleado_id = %s",
                (periodo["desde"], periodo["hasta"], periodo["id"], empleado_id),
            )


def periodos_por_empleado(cursor, empleado_ids) -> dict[int, list[tuple]]:
    """{empleado_id: [(desde, hasta), ...]} para filtrar reportes por periodo."""
    ids = sorted({int(i) for i in empleado_ids if i})
    if not ids:
        return {}
    placeholders = ",".join(["%s"] * len(ids))
    cursor.execute(
        f"""
        SELECT empleado_id, fecha_desde, fecha_hasta
        FROM empleado_periodos_laborales
        WHERE empleado_id IN ({placeholders})
        """,
        tuple(ids),
    )
    resultado: dict[int, list[tuple]] = {i: [] for i in ids}
    for row in cursor.fetchall() or []:
        if not isinstance(row, dict):
            row = dict(zip(("empleado_id", "fecha_desde", "fecha_hasta"), row))
        resultado[int(row["empleado_id"])].append((_fecha(row["fecha_desde"]), _fecha(row["fecha_hasta"])))
    return resultado


def en_periodo(periodos, fecha: dt.date) -> bool:
    return any((desde is None or desde <= fecha) and (hasta is None or hasta >= fecha) for desde, hasta in periodos)


def solapa(periodos, desde: dt.date, hasta: dt.date) -> bool:
    return any((p_desde is None or p_desde <= hasta) and (p_hasta is None or p_hasta >= desde) for p_desde, p_hasta in periodos)
