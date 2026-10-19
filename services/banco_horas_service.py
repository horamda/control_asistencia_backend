"""Banco de horas (jornada laboral, etapa D): acuerdos por empleado y libro de movimientos que no se edita.

- Acuerdo: vigencia con versiones (una nueva cierra la anterior), factores de equivalencia para horas habiles y de
  descanso (por defecto 1 + recargo de la regla: 1,5 y 2), saldo maximo y meses hasta que vencen las horas. Solo se
  carga si la regla del empleado tiene "Banco de horas habilitado".
- Libro (jl_banco_movimientos), en minutos: creditos (+) y debitos (-). Nada se borra ni se edita: un error se
  corrige con una reversion. El saldo es la suma; las horas se consumen primero por las que vencen antes y lo vencido
  se registra con un movimiento de vencimiento.
- Creditos: horas extras aprobadas "al banco" (se acreditan al cerrar el mes) y creditos manuales con motivo.
  Debitos: francos compensatorios (dia completo u horas; el motor del calculo los toma como licencia), debitos
  manuales con motivo y, al cerrar el mes, los faltantes de llegadas tarde y salidas antes.
- Nunca queda saldo negativo. Un mes cerrado no admite movimientos con fecha en el."""

import calendar
import datetime as dt
from collections import defaultdict
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

from repositories import carga_repository as db
from services import jornada_calculo_service as calc
from services import jornada_service as reglas
from services.carga_service import CargaError as Error, now_local

TIPOS = {
    "extra": "Horas extras compensadas",
    "credito": "Crédito manual",
    "franco": "Franco compensatorio",
    "debito": "Débito manual",
    "faltantes": "Faltantes del mes",
    "vencimiento": "Vencimiento",
    "reversion": "Reversión",
}
DEL_CIERRE = {"extra", "faltantes", "vencimiento"}  # se revierten reabriendo el mes
POR_VENCER_DIAS = 30
FIN = dt.date.max


# --- Utilidades -------------------------------------------------------------------------------------------------

def _hoy():
    return now_local().date()


def _fecha(valor, nombre="Fecha"):
    try:
        return valor if isinstance(valor, dt.date) else dt.date.fromisoformat(str(valor).strip()[:10])
    except (TypeError, ValueError):
        raise Error(f"{nombre}: fecha inválida.") from None


def _mas_meses(fecha, meses):
    total = fecha.month - 1 + int(meses)
    anio, mes = fecha.year + total // 12, total % 12 + 1
    return dt.date(anio, mes, min(fecha.day, calendar.monthrange(anio, mes)[1]))


def minutos(valor, nombre="Horas"):
    """'2:30', '2,5' o '150m' -> minutos (> 0)."""
    texto = str(valor or "").strip().lower()
    try:
        if ":" in texto:
            h, _, m = texto.partition(":")
            total = int(h) * 60 + int(m) if int(m) < 60 else -1
        elif texto.endswith("m"):
            total = int(texto[:-1])
        else:
            total = int((Decimal(texto.replace(",", ".")) * 60).to_integral_value(ROUND_HALF_UP))
    except (ValueError, InvalidOperation):
        total = -1
    if total <= 0:
        raise Error(f"{nombre}: use H:MM (por ejemplo 2:30) o horas (2,5).")
    return total


def _factor(valor, defecto, nombre):
    texto = str(valor or "").strip().replace(",", ".")
    if not texto:
        return defecto
    try:
        numero = Decimal(texto)
    except InvalidOperation:
        raise Error(f"{nombre}: número inválido.") from None
    if not Decimal("0.5") <= numero <= Decimal("3"):
        raise Error(f"{nombre}: debe estar entre 0,5 y 3.")
    return numero.quantize(Decimal("0.01"))


def _empleado(c, empresa_id, empleado_id, lock=False):
    fila = db.one(c, "SELECT id, empresa_id, apellido, nombre, legajo, sucursal_id FROM empleados WHERE id = %s AND empresa_id = %s"
                  + (" FOR UPDATE" if lock else ""), (int(empleado_id), empresa_id))
    if not fila:
        raise Error("Empleado no encontrado.", 404)
    return fila


def _mes_cerrado(c, empresa_id, fecha):
    fila = db.one(c, "SELECT estado FROM jl_periodos WHERE empresa_id = %s AND mes = %s", (empresa_id, fecha.replace(day=1)))
    return bool(fila and fila["estado"] == "cerrado")


# --- Acuerdos ---------------------------------------------------------------------------------------------------

def acuerdo_vigente(c, empleado_id, fecha):
    return db.one(c, """SELECT * FROM jl_banco_acuerdos WHERE empleado_id = %s AND vigente_desde <= %s
                        AND (vigente_hasta IS NULL OR vigente_hasta >= %s) ORDER BY vigente_desde DESC, id DESC LIMIT 1""",
                  (int(empleado_id), fecha, fecha))


def _regla(empresa_id, empleado, fecha):
    return reglas.Resolutor(empresa_id, [empleado], fecha, fecha).efectivas(empleado["id"], fecha)[0]


def factores_por_defecto(regla):
    return tuple((Decimal(1) + Decimal(int(regla.get(k) or v)) / 100).quantize(Decimal("0.01"))
                 for k, v in (("recargo_habil_pct", 50), ("recargo_descanso_pct", 100)))


def guardar_acuerdo(who, empleado_id, data):
    desde = _fecha(data.get("vigente_desde"), "Vigente desde")
    with db.transaction(read_only=True) as c:
        empleado = _empleado(c, who["empresa_id"], empleado_id)
    regla = _regla(who["empresa_id"], empleado, desde)
    if not int(regla.get("banco_horas_habilitado") or 0):
        raise Error("La regla de jornada de este empleado no habilita el banco de horas (Jornada laboral → reglas).")
    def_habil, def_descanso = factores_por_defecto(regla)
    factor_habil = _factor(data.get("factor_habil"), def_habil, "Equivalencia de la hora hábil")
    factor_descanso = _factor(data.get("factor_descanso"), def_descanso, "Equivalencia de la hora de descanso")
    maximo = minutos(data.get("saldo_maximo"), "Saldo máximo") if str(data.get("saldo_maximo") or "").strip() else None
    vence = str(data.get("vence_meses") or "").strip()
    if vence and (not vence.isdigit() or not 1 <= int(vence) <= 60):
        raise Error("Vencimiento: entre 1 y 60 meses, o vacío si no vencen.")
    motivo = str(data.get("motivo") or "").strip()[:255] or None
    ahora = now_local().replace(microsecond=0)
    with db.transaction() as c:
        _empleado(c, who["empresa_id"], empleado_id, lock=True)
        actual = db.one(c, """SELECT * FROM jl_banco_acuerdos WHERE empleado_id = %s
                              ORDER BY vigente_desde DESC, id DESC LIMIT 1""", (int(empleado_id),))
        if actual and desde <= actual["vigente_desde"]:
            raise Error(f"La versión nueva tiene que empezar después del {actual['vigente_desde']:%d/%m/%Y} (la vigente).")
        if actual and (actual["vigente_hasta"] is None or actual["vigente_hasta"] >= desde):
            c.execute("UPDATE jl_banco_acuerdos SET vigente_hasta = %s WHERE id = %s", (desde - dt.timedelta(days=1), actual["id"]))
        return db.insert(c, "jl_banco_acuerdos", dict(
            empresa_id=who["empresa_id"], empleado_id=int(empleado_id), vigente_desde=desde, factor_habil=factor_habil,
            factor_descanso=factor_descanso, saldo_maximo_min=maximo, vence_meses=int(vence) if vence else None,
            motivo=motivo, reemplaza_id=actual and actual["id"], creado_por=who.get("user_id"), creado_at=ahora))


def finalizar_acuerdo(who, empleado_id, hasta, motivo):
    hasta = _fecha(hasta, "Hasta")
    motivo = str(motivo or "").strip()[:255]
    if not motivo:
        raise Error("Indicá el motivo de la finalización.")
    with db.transaction() as c:
        _empleado(c, who["empresa_id"], empleado_id, lock=True)
        actual = db.one(c, """SELECT * FROM jl_banco_acuerdos WHERE empleado_id = %s AND vigente_hasta IS NULL
                              ORDER BY vigente_desde DESC LIMIT 1 FOR UPDATE""", (int(empleado_id),))
        if not actual:
            raise Error("No tiene un acuerdo abierto.")
        if hasta < actual["vigente_desde"]:
            raise Error("La finalización no puede ser anterior al inicio del acuerdo.")
        c.execute("UPDATE jl_banco_acuerdos SET vigente_hasta = %s, motivo = %s WHERE id = %s",
                  (hasta, f"{actual['motivo'] or ''} · Finalizado: {motivo}".strip(" ·")[:255], actual["id"]))
    return actual["id"]


# --- Saldo y vencimientos ---------------------------------------------------------------------------------------

def _movimientos(c, empleado_id):
    return db.all_rows(c, """SELECT m.*, (SELECT r.id FROM jl_banco_movimientos r WHERE r.revierte_id = m.id) AS revertido_por
                             FROM jl_banco_movimientos m WHERE m.empleado_id = %s ORDER BY m.fecha, m.id""", (int(empleado_id),))


def lotes(movimientos):
    """Lotes de horas acreditadas que quedan, despues de aplicar los debitos (primero los que vencen antes; una
    reversion de un credito consume ese credito)."""
    vivos = []
    for m in sorted(movimientos, key=lambda x: (x["fecha"], x["id"])):
        if m["minutos"] > 0:
            vivos.append(dict(id=m["id"], fecha=m["fecha"], restante=m["minutos"], vence=m["vence"]))
            continue
        resta = -m["minutos"]
        orden = sorted((l for l in vivos if l["restante"] > 0),
                       key=lambda l: (l["id"] != m["revierte_id"], l["vence"] or FIN, l["id"]))
        for lote in orden:
            toma = min(resta, lote["restante"])
            lote["restante"] -= toma
            resta -= toma
            if not resta:
                break
    return [l for l in vivos if l["restante"] > 0]


def saldo(movimientos, al=None):
    """dict(total, disponible, por_vencer, vencido_sin_registrar) en minutos al dia indicado (hoy por defecto)."""
    al = al or _hoy()
    vivos = lotes(movimientos)
    return dict(
        total=sum(m["minutos"] for m in movimientos),
        disponible=sum(l["restante"] for l in vivos if not l["vence"] or l["vence"] >= al),
        por_vencer=sum(l["restante"] for l in vivos if l["vence"] and al <= l["vence"] <= al + dt.timedelta(days=POR_VENCER_DIAS)),
        vencido_sin_registrar=sum(l["restante"] for l in vivos if l["vence"] and l["vence"] < al),
        lotes=vivos,
    )


def _insertar(c, who, empleado_id, fecha, tipo, minutos_, **extra):
    return db.insert(c, "jl_banco_movimientos", dict(
        empresa_id=who["empresa_id"], empleado_id=int(empleado_id), fecha=fecha, tipo=tipo, minutos=int(minutos_),
        creado_por=who.get("user_id"), creado_at=now_local().replace(microsecond=0), **extra))


def _vencer(c, who, empleado_id, corte, periodo_id=None):
    """Registra como vencido lo que vencio antes del corte. Devuelve los minutos vencidos."""
    vencido = sum(l["restante"] for l in lotes(_movimientos(c, empleado_id)) if l["vence"] and l["vence"] < corte)
    if vencido:
        _insertar(c, who, empleado_id, corte - dt.timedelta(days=1), "vencimiento", -vencido, periodo_id=periodo_id,
                  motivo="Horas acreditadas que vencieron")
    return vencido


def _vence(acuerdo, fecha):
    return _mas_meses(fecha, acuerdo["vence_meses"]) if acuerdo and acuerdo["vence_meses"] else None


# --- Movimientos manuales, francos y reversiones ------------------------------------------------------------------

def registrar(who, empleado_id, tipo, fecha, horas=None, motivo=None, dia_completo=False):
    """tipo: credito, debito o franco. Devuelve el id del movimiento."""
    if tipo not in ("credito", "debito", "franco"):
        raise Error("Tipo de movimiento inválido.")
    fecha = _fecha(fecha)
    motivo = str(motivo or "").strip()[:255] or None
    if tipo in ("credito", "debito") and not motivo:
        raise Error("Indicá el motivo del movimiento.")
    if tipo == "franco" and dia_completo:
        datos = calc.calcular(who["empresa_id"], fecha, fecha, {"empleado_id": empleado_id})
        if not datos["empleados"]:
            raise Error("Empleado no encontrado.", 404)
        dia = datos["empleados"][0]["dias"][0]
        cantidad = dia["programados"]
        if not cantidad:
            raise Error("Ese día no tiene horas programadas: indicá cuántas horas toma.")
    else:
        cantidad = minutos(horas)
    hoy = _hoy()
    with db.transaction() as c:
        _empleado(c, who["empresa_id"], empleado_id, lock=True)
        if _mes_cerrado(c, who["empresa_id"], fecha):
            raise Error("El mes de esa fecha está cerrado.")
        acuerdo = acuerdo_vigente(c, empleado_id, fecha)
        _vencer(c, who, empleado_id, hoy)
        estado = saldo(_movimientos(c, empleado_id), hoy)
        if tipo == "credito":
            if not acuerdo:
                raise Error("No tiene un acuerdo de banco de horas vigente en esa fecha.")
            if acuerdo["saldo_maximo_min"] is not None and estado["total"] + cantidad > acuerdo["saldo_maximo_min"]:
                raise Error(f"Supera el saldo máximo del acuerdo ({calc.horas(acuerdo['saldo_maximo_min'])} h).")
            return _insertar(c, who, empleado_id, fecha, "credito", cantidad, vence=_vence(acuerdo, fecha), motivo=motivo)
        if tipo == "franco" and db.one(c, """SELECT m.id FROM jl_banco_movimientos m WHERE m.empleado_id = %s AND m.fecha = %s
                                            AND m.tipo = 'franco' AND NOT EXISTS (SELECT 1 FROM jl_banco_movimientos r
                                            WHERE r.revierte_id = m.id)""", (int(empleado_id), fecha)):
            raise Error("Ya tiene un franco compensatorio ese día.")
        if cantidad > estado["disponible"]:
            raise Error(f"Saldo insuficiente: tiene {calc.horas(estado['disponible'])} h disponibles.")
        return _insertar(c, who, empleado_id, fecha, tipo, -cantidad,
                         motivo=motivo or ("Día completo" if dia_completo else None))


def revertir(who, movimiento_id, motivo):
    motivo = str(motivo or "").strip()[:255]
    if not motivo:
        raise Error("Indicá el motivo de la reversión.")
    hoy = _hoy()
    with db.transaction() as c:
        original = db.one(c, "SELECT * FROM jl_banco_movimientos WHERE id = %s AND empresa_id = %s",
                          (int(movimiento_id), who["empresa_id"]))
        if not original:
            raise Error("Movimiento no encontrado.", 404)
        _empleado(c, who["empresa_id"], original["empleado_id"], lock=True)
        if original["tipo"] == "reversion":
            raise Error("Una reversión no se revierte: cargá un movimiento nuevo.")
        if original["tipo"] in DEL_CIERRE:
            raise Error("Ese movimiento salió del cierre del mes: se revierte reabriendo el mes.")
        if db.one(c, "SELECT id FROM jl_banco_movimientos WHERE revierte_id = %s", (original["id"],)):
            raise Error("Ese movimiento ya fue revertido.")
        if _mes_cerrado(c, who["empresa_id"], original["fecha"]):
            raise Error("El mes de ese movimiento está cerrado: reabrilo para revertirlo.")
        _vencer(c, who, original["empleado_id"], hoy)
        if original["minutos"] > 0:
            restante = next((l["restante"] for l in lotes(_movimientos(c, original["empleado_id"])) if l["id"] == original["id"]), 0)
            if restante < original["minutos"]:
                raise Error("Esas horas ya se usaron o vencieron: no se puede revertir el crédito sin dejar saldo negativo.")
        acuerdo = acuerdo_vigente(c, original["empleado_id"], hoy)
        return _insertar(c, who, original["empleado_id"], hoy, "reversion", -original["minutos"], revierte_id=original["id"],
                         vence=_vence(acuerdo, hoy) if original["minutos"] < 0 else None,
                         motivo=f"Revierte {TIPOS[original['tipo']].lower()} del {original['fecha']:%d/%m/%Y}: {motivo}"[:255])


# --- Horas extras: destino banco y cierre del mes -------------------------------------------------------------------

def credito_de(acuerdo, habil, descanso, recargos=(None, None)):
    """Minutos de banco que acredita una hora extra (factores del acuerdo o, sin acuerdo, 1 + recargo)."""
    if acuerdo:
        fh, fd = Decimal(acuerdo["factor_habil"]), Decimal(acuerdo["factor_descanso"])
    else:
        fh, fd = factores_por_defecto(dict(recargo_habil_pct=recargos[0], recargo_descanso_pct=recargos[1]))
    return int((habil * fh + descanso * fd).to_integral_value(ROUND_HALF_UP))


def validar_destino_banco(c, empleado_id, fecha, habil, descanso, horas_extra_id=None):
    """Al aprobar horas extras al banco: tiene que haber acuerdo vigente y no superar su saldo maximo."""
    acuerdo = acuerdo_vigente(c, empleado_id, fecha)
    if not acuerdo:
        raise Error("No tiene un acuerdo de banco de horas vigente ese día: solo se pueden pagar.")
    if acuerdo["saldo_maximo_min"] is not None:
        pendientes = sum(credito_de(acuerdo_vigente(c, empleado_id, f["fecha"]) or acuerdo, f["minutos_habil"], f["minutos_descanso"])
                         for f in db.all_rows(c, """SELECT fecha, minutos_habil, minutos_descanso FROM jl_horas_extra
                                                    WHERE empleado_id = %s AND estado = 'aprobada' AND destino = 'banco'
                                                      AND id <> %s""", (int(empleado_id), horas_extra_id or 0)))
        actual = sum(m["minutos"] for m in _movimientos(c, empleado_id))
        if actual + pendientes + credito_de(acuerdo, habil, descanso) > acuerdo["saldo_maximo_min"]:
            raise Error(f"Al banco superaría el saldo máximo del acuerdo ({calc.horas(acuerdo['saldo_maximo_min'])} h): "
                        "conviene pagarlas.")
    return acuerdo


def al_cerrar(c, who, periodo_id, desde, hasta, calculo_id):
    """Dentro de la transaccion del cierre: acredita lo aprobado al banco, registra vencimientos y debita faltantes."""
    ahora = now_local().replace(microsecond=0)
    resumen = defaultdict(int)
    extras = db.all_rows(c, """SELECT * FROM jl_horas_extra WHERE empresa_id = %s AND fecha BETWEEN %s AND %s
                               AND estado = 'aprobada' AND destino = 'banco' FOR UPDATE""", (who["empresa_id"], desde, hasta))
    faltantes = defaultdict(int)
    for f in db.all_rows(c, """SELECT r.empleado_id, r.fecha, r.minutos_faltantes FROM jl_resultados_dia r
                               WHERE r.calculo_id = %s AND r.estado = 'normal' AND r.minutos_faltantes > 0""", (calculo_id,)):
        if acuerdo_vigente(c, f["empleado_id"], f["fecha"]):
            faltantes[int(f["empleado_id"])] += int(f["minutos_faltantes"])
    con_movimientos = {int(f["empleado_id"]) for f in db.all_rows(
        c, "SELECT DISTINCT empleado_id FROM jl_banco_movimientos WHERE empresa_id = %s", (who["empresa_id"],))}
    empleados = sorted({int(x["empleado_id"]) for x in extras} | set(faltantes) | con_movimientos)
    if empleados:
        db.all_rows(c, f"SELECT id FROM empleados WHERE id IN ({','.join(['%s'] * len(empleados))}) FOR UPDATE", tuple(empleados))
    for f in extras:
        acuerdo = acuerdo_vigente(c, f["empleado_id"], f["fecha"])
        credito = credito_de(acuerdo, f["minutos_habil"], f["minutos_descanso"], (f["recargo_habil"], f["recargo_descanso"]))
        _insertar(c, who, f["empleado_id"], f["fecha"], "extra", credito, vence=_vence(acuerdo, f["fecha"]),
                  horas_extra_id=f["id"], periodo_id=periodo_id,
                  motivo=f"{calc.horas(f['minutos_habil'] + f['minutos_descanso'])} h extras del {f['fecha']:%d/%m}")
        c.execute("UPDATE jl_horas_extra SET estado='compensada', periodo_id=%s, actualizado_at=%s WHERE id=%s",
                  (periodo_id, ahora, f["id"]))
        db.insert(c, "jl_horas_extra_eventos", dict(
            horas_extra_id=f["id"], empresa_id=who["empresa_id"], accion="compensar", estado_anterior="aprobada",
            estado_nuevo="compensada", minutos_habil=f["minutos_habil"], minutos_descanso=f["minutos_descanso"],
            supera_tope=f["supera_tope"], motivo=f"Acreditadas {calc.horas(credito)} h al banco", usuario_id=who["user_id"],
            creado_at=ahora))
        resumen["compensadas"] += 1
        resumen["acreditado"] += credito
    corte = hasta + dt.timedelta(days=1)
    for eid in empleados:
        resumen["vencido"] += _vencer(c, who, eid, corte, periodo_id)
        if faltantes.get(eid):
            disponible = saldo(_movimientos(c, eid), corte)["disponible"]
            debito = min(faltantes[eid], disponible)
            resumen["faltantes_sin_descontar"] += faltantes[eid] - debito
            if debito:
                _insertar(c, who, eid, hasta, "faltantes", -debito, periodo_id=periodo_id,
                          motivo=f"Faltantes de {desde:%m/%Y}: {calc.horas(debito)} de {calc.horas(faltantes[eid])} h")
                resumen["faltantes"] += debito
    return dict(resumen)


def al_reabrir(c, who, periodo_id, motivo):
    """Dentro de la transaccion de la reapertura: revierte los movimientos del cierre y lo compensado vuelve a aprobado."""
    ahora = now_local().replace(microsecond=0)
    hoy = ahora.date()
    movimientos = db.all_rows(c, """SELECT * FROM jl_banco_movimientos m WHERE m.periodo_id = %s
                                    AND NOT EXISTS (SELECT 1 FROM jl_banco_movimientos r WHERE r.revierte_id = m.id)
                                    ORDER BY m.id""", (periodo_id,))
    por_empleado = defaultdict(list)
    for m in movimientos:
        por_empleado[int(m["empleado_id"])].append(m)
    if por_empleado:
        db.all_rows(c, f"SELECT id FROM empleados WHERE id IN ({','.join(['%s'] * len(por_empleado))}) FOR UPDATE",
                    tuple(sorted(por_empleado)))
    for eid, lista in por_empleado.items():
        total = sum(m["minutos"] for m in _movimientos(c, eid)) - sum(m["minutos"] for m in lista)
        if total < 0:
            empleado = _empleado(c, who["empresa_id"], eid)
            raise Error(f"No se puede reabrir: el banco de {empleado['apellido']}, {empleado['nombre']} quedaría en "
                        f"negativo ({calc.horas(total)} h) porque ya usó esas horas. Revertí antes sus francos o débitos.")
    for eid, lista in por_empleado.items():
        acuerdo = acuerdo_vigente(c, eid, hoy)
        for m in lista:
            vence = m["fecha"] if m["tipo"] == "vencimiento" else (_vence(acuerdo, hoy) if m["minutos"] < 0 else None)
            _insertar(c, who, eid, hoy, "reversion", -m["minutos"], revierte_id=m["id"], vence=vence,
                      motivo=f"Reapertura del mes: {motivo}"[:255])
    compensadas = db.all_rows(c, "SELECT * FROM jl_horas_extra WHERE periodo_id = %s AND estado = 'compensada' FOR UPDATE",
                              (periodo_id,))
    for f in compensadas:
        c.execute("UPDATE jl_horas_extra SET estado='aprobada', periodo_id=NULL, actualizado_at=%s WHERE id=%s", (ahora, f["id"]))
        db.insert(c, "jl_horas_extra_eventos", dict(
            horas_extra_id=f["id"], empresa_id=who["empresa_id"], accion="reabrir", estado_anterior="compensada",
            estado_nuevo="aprobada", minutos_habil=f["minutos_habil"], minutos_descanso=f["minutos_descanso"],
            supera_tope=f["supera_tope"], motivo=motivo, usuario_id=who["user_id"], creado_at=ahora))
    return len(movimientos), len(compensadas)


# --- Consultas para el panel ------------------------------------------------------------------------------------

def resumen(empresa_id, filtros=None):
    """Empleados con acuerdo vigente o con movimientos: saldo, disponible y por vencer."""
    filtros = filtros or {}
    hoy = _hoy()
    donde, args = ["e.empresa_id = %s"], [empresa_id]
    for clave, columna in (("sucursal_id", "e.sucursal_id"), ("sector_id", "e.sector_id")):
        if str(filtros.get(clave) or "").isdigit():
            donde.append(f"{columna} = %s")
            args.append(int(filtros[clave]))
    with db.transaction(read_only=True) as c:
        empleados = db.all_rows(c, f"""SELECT e.id, e.apellido, e.nombre, e.legajo, su.nombre AS sucursal_nombre
                                       FROM empleados e LEFT JOIN sucursales su ON su.id = e.sucursal_id
                                       WHERE {' AND '.join(donde)} AND (
                                         EXISTS (SELECT 1 FROM jl_banco_acuerdos a WHERE a.empleado_id = e.id
                                                 AND (a.vigente_hasta IS NULL OR a.vigente_hasta >= %s))
                                         OR EXISTS (SELECT 1 FROM jl_banco_movimientos m WHERE m.empleado_id = e.id))
                                       ORDER BY e.apellido, e.nombre""", (*args, hoy))
        ids = [int(e["id"]) for e in empleados]
        movimientos, acuerdos = defaultdict(list), {}
        if ids:
            marcas = ",".join(["%s"] * len(ids))
            for m in db.all_rows(c, f"SELECT * FROM jl_banco_movimientos WHERE empleado_id IN ({marcas}) ORDER BY fecha, id", tuple(ids)):
                movimientos[int(m["empleado_id"])].append(m)
            for a in db.all_rows(c, f"""SELECT * FROM jl_banco_acuerdos WHERE empleado_id IN ({marcas}) AND vigente_desde <= %s
                                        AND (vigente_hasta IS NULL OR vigente_hasta >= %s)""", (*ids, hoy, hoy)):
                acuerdos[int(a["empleado_id"])] = a
    for e in empleados:
        e.update(saldo=saldo(movimientos.get(int(e["id"]), []), hoy), acuerdo=acuerdos.get(int(e["id"])))
    return empleados


def detalle(who, empleado_id):
    hoy = _hoy()
    with db.transaction(read_only=True) as c:
        empleado = _empleado(c, who["empresa_id"], empleado_id)
        movimientos = db.all_rows(c, """SELECT m.*, u.usuario,
                                               (SELECT r.id FROM jl_banco_movimientos r WHERE r.revierte_id = m.id) AS revertido_por
                                        FROM jl_banco_movimientos m LEFT JOIN usuarios u ON u.id = m.creado_por
                                        WHERE m.empleado_id = %s ORDER BY m.fecha, m.id""", (int(empleado_id),))
        acuerdos = db.all_rows(c, """SELECT a.*, u.usuario FROM jl_banco_acuerdos a LEFT JOIN usuarios u ON u.id = a.creado_por
                                     WHERE a.empleado_id = %s ORDER BY a.vigente_desde DESC, a.id DESC""", (int(empleado_id),))
        vigente = acuerdo_vigente(c, empleado_id, hoy)
    regla = _regla(who["empresa_id"], empleado, hoy)
    acumulado = 0
    for m in movimientos:
        acumulado += m["minutos"]
        m["saldo"] = acumulado
    return dict(empleado=empleado, movimientos=list(reversed(movimientos)), acuerdos=acuerdos, acuerdo=vigente,
                saldo=saldo(movimientos, hoy), habilitado=bool(int(regla.get("banco_horas_habilitado") or 0)),
                factores=factores_por_defecto(regla))
