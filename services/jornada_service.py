"""Gestion de jornada laboral, etapa A: convenios, reglas con vigencia y condiciones laborales de cada empleado.

Niveles de una regla, del mas general al mas especifico: empresa, sucursal, convenio y empleado. Para cada campo vale
el valor del nivel mas especifico vigente en la fecha (un campo vacio hereda del nivel superior).

- El convenio del empleado (o la ley, en "Fuera de convenio") fija los topes obligatorios: una regla individual no
  puede superarlos (horas semanales, diarias, nocturnas y topes de horas extras). Se valida al guardar.
- Las reglas y asignaciones nunca se editan: una version nueva cierra la anterior y la referencia (historial completo).
- Horario habitual y descansos salen de los horarios ya asignados (no se cargan dos veces). Las tolerancias solo sirven
  para clasificar llegadas y salidas: nunca cambian los minutos trabajados.
- No lee ni modifica fichajes (eso es la etapa B, el motor de calculo)."""

import datetime as dt
from decimal import Decimal, InvalidOperation

from repositories import carga_repository as db
from services.carga_service import CargaError as Error, now_local

ALCANCES = ("empresa", "sucursal", "convenio", "empleado")
# El primero que define el campo gana; "ley" (la regla de Fuera de convenio, LCT) completa lo que nadie definio.
PRECEDENCIA = ("empleado", "convenio", "sucursal", "empresa", "ley")
TIPOS_CONVENIO = {"ley": "Ley general", "cct": "Convenio colectivo", "acuerdo": "Acuerdo de empresa"}
REGIMENES = {"diaria": "Jornada diaria fija", "semanal": "Distribución semanal", "promedio": "Promedio en un ciclo"}
DIAS = {1: "Lun", 2: "Mar", 3: "Mié", 4: "Jue", 5: "Vie", 6: "Sáb", 7: "Dom"}
NOMBRES_DIA = {1: "lunes", 2: "martes", 3: "miércoles", 4: "jueves", 5: "viernes", 6: "sábado", 7: "domingo"}

# clave: (etiqueta, tipo, minimo, maximo, es_tope_del_convenio)
CAMPOS = {
    "horas_semanales": ("Horas semanales pactadas", "decimal", 1, 80, True),
    "horas_diarias": ("Horas diarias pactadas", "decimal", 1, 24, True),
    "dias_laborales": ("Días laborales", "dias", None, None, False),
    "regimen_distribucion": ("Régimen de distribución", "regimen", None, None, False),
    "descanso_computable_min": ("Descanso computable (min por jornada)", "entero", 0, 240, False),
    "tolerancia_ingreso_min": ("Tolerancia de ingreso (min)", "entero", 0, 120, False),
    "tolerancia_salida_min": ("Tolerancia de salida (min)", "entero", 0, 120, False),
    "nocturna_desde": ("Jornada nocturna desde", "hora", None, None, False),
    "nocturna_hasta": ("Jornada nocturna hasta", "hora", None, None, False),
    "horas_nocturnas_diarias": ("Horas nocturnas diarias", "decimal", 1, 24, True),
    "trabaja_feriados": ("Trabaja en feriados", "booleano", None, None, False),
    "tope_extras_mes": ("Tope de horas extras por mes", "entero", 0, 300, True),
    "tope_extras_anio": ("Tope de horas extras por año", "entero", 0, 2000, True),
    "banco_horas_habilitado": ("Banco de horas habilitado", "booleano", None, None, False),
    "observaciones": ("Observaciones", "texto", None, 255, False),
}


# --- Utilidades ---------------------------------------------------------------------------------------------

def _hoy():
    return now_local().date()


def _fecha(valor, nombre):
    try:
        return dt.date.fromisoformat(str(valor).strip()[:10])
    except (TypeError, ValueError):
        raise Error(f"{nombre}: fecha inválida (use AAAA-MM-DD).") from None


def _texto_fecha(valor):
    if not valor:
        return None
    return valor.isoformat() if hasattr(valor, "isoformat") else str(valor)[:10]


def _hhmm(valor):
    if valor in (None, ""):
        return None
    if isinstance(valor, dt.timedelta):
        minutos = int(valor.total_seconds() // 60)
        return f"{minutos // 60:02d}:{minutos % 60:02d}"
    if hasattr(valor, "strftime"):
        return valor.strftime("%H:%M")
    return str(valor)[:5]


def _numero(valor):
    if valor is None:
        return None
    numero = Decimal(str(valor))
    return int(numero) if numero == numero.to_integral_value() else float(numero)


def _leer_campo(clave, crudo):
    """Valor del formulario -> valor guardable (None = hereda del nivel superior)."""
    etiqueta, tipo, minimo, maximo, _ = CAMPOS[clave]
    if isinstance(crudo, (list, tuple)):
        valores = [str(v).strip() for v in crudo if str(v).strip()]
    else:
        valores = None
        crudo = "" if crudo is None else str(crudo).strip()
    if tipo == "dias":
        if not valores:
            return None
        dias = sorted({int(v) for v in valores if v.isdigit() and 1 <= int(v) <= 7})
        if not dias:
            raise Error(f"{etiqueta}: elegí al menos un día.")
        return ",".join(str(d) for d in dias)
    if crudo == "":
        return None
    if tipo == "decimal":
        try:
            numero = Decimal(crudo.replace(",", "."))
        except InvalidOperation:
            raise Error(f"{etiqueta}: número inválido.") from None
        if not minimo <= numero <= maximo:
            raise Error(f"{etiqueta}: debe estar entre {minimo} y {maximo}.")
        return numero
    if tipo == "entero":
        if not crudo.lstrip("-").isdigit() or not minimo <= int(crudo) <= maximo:
            raise Error(f"{etiqueta}: use un entero entre {minimo} y {maximo}.")
        return int(crudo)
    if tipo == "hora":
        try:
            return dt.datetime.strptime(crudo[:5], "%H:%M").time()
        except ValueError:
            raise Error(f"{etiqueta}: hora inválida (use HH:MM, 24 h).") from None
    if tipo == "booleano":
        if crudo not in ("0", "1"):
            raise Error(f"{etiqueta}: valor inválido.")
        return int(crudo)
    if tipo == "regimen":
        if crudo not in REGIMENES:
            raise Error(f"{etiqueta}: valor inválido.")
        return crudo
    return crudo[:maximo]


def mostrar(clave, valor):
    """Valor guardado -> texto para el panel."""
    if valor is None or valor == "":
        return None
    tipo = CAMPOS[clave][1]
    if tipo == "dias":
        return ", ".join(DIAS[int(d)] for d in str(valor).split(",") if d.strip().isdigit())
    if tipo == "hora":
        return _hhmm(valor)
    if tipo == "booleano":
        return "Sí" if int(valor) else "No"
    if tipo == "regimen":
        return REGIMENES.get(valor, valor)
    if tipo == "decimal":
        return f"{_numero(valor):g} h".replace(".", ",")
    if tipo == "entero":
        return f"{int(valor)}"
    return str(valor)


# --- Convenios ----------------------------------------------------------------------------------------------

def convenios(empresa_id, *, solo_activos=False):
    with db.transaction(read_only=True) as c:
        filas = db.all_rows(c, f"""SELECT c.*, (SELECT COUNT(*) FROM jl_asignaciones a WHERE a.convenio_id = c.id
                                              AND a.vigente_desde <= %s AND (a.vigente_hasta IS NULL OR a.vigente_hasta >= %s)) AS empleados
                                   FROM jl_convenios c WHERE c.empresa_id = %s {'AND c.activo = 1' if solo_activos else ''}
                                   ORDER BY c.activo DESC, c.nombre""", (_hoy(), _hoy(), empresa_id))
    for f in filas:
        f["tipo_nombre"] = TIPOS_CONVENIO.get(f["tipo"], f["tipo"])
        f["empleados"] = int(f["empleados"] or 0)
    return filas


def _convenio(c, empresa_id, convenio_id):
    fila = db.one(c, "SELECT * FROM jl_convenios WHERE id = %s AND empresa_id = %s", (int(convenio_id), empresa_id))
    if not fila:
        raise Error("Convenio no encontrado.", 404)
    return fila


def guardar_convenio(who, data, convenio_id=None):
    nombre = str(data.get("nombre") or "").strip()[:120]
    if not nombre:
        raise Error("Indicá el nombre del convenio o acuerdo.")
    tipo = str(data.get("tipo") or "cct")
    if tipo not in TIPOS_CONVENIO:
        raise Error("Tipo inválido.")
    descripcion = (str(data.get("descripcion") or "").strip() or None)
    activo = 1 if str(data.get("activo", "1")) == "1" else 0
    with db.transaction() as c:
        if convenio_id:
            _convenio(c, who["empresa_id"], convenio_id)
            c.execute("UPDATE jl_convenios SET nombre=%s, tipo=%s, descripcion=%s, activo=%s WHERE id=%s",
                      (nombre, tipo, descripcion and descripcion[:500], activo, int(convenio_id)))
            return int(convenio_id)
        codigo = "".join(ch if ch.isalnum() else "_" for ch in nombre.upper())[:30] + f"_{now_local():%y%m%d%H%M%S}"
        return db.insert(c, "jl_convenios", dict(empresa_id=who["empresa_id"], codigo=codigo, nombre=nombre, tipo=tipo,
                                                 descripcion=descripcion and descripcion[:500], activo=activo,
                                                 creado_por=who.get("user_id"), creado_at=now_local()))


# --- Reglas -------------------------------------------------------------------------------------------------

def _filtro_alcance(alcance, ref_id):
    columna = {"sucursal": "sucursal_id", "convenio": "convenio_id", "empleado": "empleado_id"}.get(alcance)
    return (f" AND {columna} = %s", (int(ref_id),)) if columna else ("", ())


def _vigentes(c, empresa_id, alcance, ref_id, fecha):
    filtro, args = _filtro_alcance(alcance, ref_id)
    return db.one(c, f"""SELECT * FROM jl_reglas WHERE empresa_id = %s AND alcance = %s {filtro}
                         AND vigente_desde <= %s AND (vigente_hasta IS NULL OR vigente_hasta >= %s)
                         ORDER BY vigente_desde DESC, id DESC LIMIT 1""", (empresa_id, alcance, *args, fecha, fecha))


def versiones(empresa_id, alcance, ref_id=None):
    filtro, args = _filtro_alcance(alcance, ref_id)
    with db.transaction(read_only=True) as c:
        return db.all_rows(c, f"""SELECT r.*, u.usuario AS creado_por_usuario FROM jl_reglas r
                                  LEFT JOIN usuarios u ON u.id = r.creado_por
                                  WHERE r.empresa_id = %s AND r.alcance = %s {filtro}
                                  ORDER BY r.vigente_desde DESC, r.id DESC""", (empresa_id, alcance, *args))


def _ref_valida(c, empresa_id, alcance, ref_id):
    if alcance == "empresa":
        return None
    if not ref_id:
        raise Error("Falta indicar a quién aplica la regla.")
    tabla = {"sucursal": "sucursales", "convenio": "jl_convenios", "empleado": "empleados"}[alcance]
    if not db.one(c, f"SELECT id FROM {tabla} WHERE id = %s AND empresa_id = %s", (int(ref_id), empresa_id)):
        raise Error("No se encontró a quién aplica la regla.", 404)
    return int(ref_id)


def _regla_ley(c, empresa_id, fecha):
    lct = db.one(c, "SELECT id FROM jl_convenios WHERE empresa_id = %s AND codigo = 'LCT'", (empresa_id,))
    return _vigentes(c, empresa_id, "convenio", lct["id"], fecha) if lct else None


def _topes(c, empresa_id, empleado_id, fecha):
    """Topes obligatorios para un empleado: la regla de su convenio vigente (o de Fuera de convenio si no tiene)."""
    asignacion = _asignacion(c, empleado_id, fecha)
    convenio_id = asignacion["convenio_id"] if asignacion else None
    if not convenio_id:
        lct = db.one(c, "SELECT id FROM jl_convenios WHERE empresa_id = %s AND codigo = 'LCT'", (empresa_id,))
        convenio_id = lct["id"] if lct else None
    regla = _vigentes(c, empresa_id, "convenio", convenio_id, fecha) if convenio_id else None
    return regla or {}


def guardar_regla(who, alcance, ref_id, data):
    """Nueva version de la regla de un nivel. Cierra la version abierta anterior el dia previo al inicio de esta."""
    if alcance not in ALCANCES:
        raise Error("Nivel inválido.")
    desde = _fecha(data.get("vigente_desde"), "Vigente desde")
    motivo = (str(data.get("motivo") or "").strip() or None)
    valores = {clave: _leer_campo(clave, data.getlist(clave) if CAMPOS[clave][1] == "dias" and hasattr(data, "getlist")
                                   else data.get(clave)) for clave in CAMPOS}
    if all(v is None for v in valores.values()):
        raise Error("Completá al menos un valor (los vacíos heredan del nivel superior).")
    if (valores["nocturna_desde"] is None) != (valores["nocturna_hasta"] is None):
        raise Error("La jornada nocturna necesita hora de inicio y de fin.")
    empresa_id = who["empresa_id"]
    with db.transaction() as c:
        ref = _ref_valida(c, empresa_id, alcance, ref_id)
        if alcance == "empleado":
            topes = _topes(c, empresa_id, ref, desde)
            for clave, (etiqueta, _, _, _, es_tope) in CAMPOS.items():
                if es_tope and valores[clave] is not None and topes.get(clave) is not None \
                        and Decimal(str(valores[clave])) > Decimal(str(topes[clave])):
                    raise Error(f"{etiqueta}: {mostrar(clave, valores[clave])} supera el tope de su convenio "
                                f"({mostrar(clave, topes[clave])}). Una condición individual solo puede ser más favorable.")
        filtro, args = _filtro_alcance(alcance, ref)
        abierta = db.one(c, f"""SELECT * FROM jl_reglas WHERE empresa_id = %s AND alcance = %s {filtro}
                                AND (vigente_hasta IS NULL OR vigente_hasta >= %s)
                                ORDER BY vigente_desde DESC, id DESC LIMIT 1 FOR UPDATE""", (empresa_id, alcance, *args, desde))
        if abierta and abierta["vigente_desde"] >= desde:
            raise Error(f"Ya hay una versión vigente desde el {abierta['vigente_desde']:%d/%m/%Y}: la nueva tiene que empezar después.")
        if abierta:
            c.execute("UPDATE jl_reglas SET vigente_hasta = %s WHERE id = %s", (desde - dt.timedelta(days=1), abierta["id"]))
        columnas = {"sucursal": "sucursal_id", "convenio": "convenio_id", "empleado": "empleado_id"}
        fila = dict(empresa_id=empresa_id, alcance=alcance, vigente_desde=desde, motivo=motivo and motivo[:255],
                    reemplaza_id=abierta["id"] if abierta else None, creado_por=who.get("user_id"), creado_at=now_local(),
                    **valores)
        if alcance in columnas:
            fila[columnas[alcance]] = ref
        return db.insert(c, "jl_reglas", fila)


# --- Asignacion de convenio ---------------------------------------------------------------------------------

def _asignacion(c, empleado_id, fecha):
    return db.one(c, """SELECT a.*, cv.nombre AS convenio_nombre FROM jl_asignaciones a
                        JOIN jl_convenios cv ON cv.id = a.convenio_id
                        WHERE a.empleado_id = %s AND a.vigente_desde <= %s AND (a.vigente_hasta IS NULL OR a.vigente_hasta >= %s)
                        ORDER BY a.vigente_desde DESC, a.id DESC LIMIT 1""", (int(empleado_id), fecha, fecha))


def asignar_convenio(who, empleado_ids, convenio_id, desde, motivo=None):
    """Asignacion masiva. Por empleado: cierra la asignacion abierta anterior y crea la nueva. Devuelve
    (asignados, errores) con el motivo de cada empleado que no se pudo asignar."""
    ids = sorted({int(i) for i in empleado_ids or [] if str(i).strip().isdigit()})
    if not ids:
        raise Error("Elegí al menos un empleado.")
    desde = _fecha(desde, "Vigente desde")
    motivo = (str(motivo or "").strip() or None)
    empresa_id = who["empresa_id"]
    asignados, errores = 0, []
    with db.transaction() as c:
        convenio = _convenio(c, empresa_id, convenio_id)
        if not convenio["activo"]:
            raise Error("El convenio está inactivo.")
        marcas = ",".join(["%s"] * len(ids))
        empleados = {int(e["id"]): e for e in db.all_rows(
            c, f"SELECT id, apellido, nombre FROM empleados WHERE empresa_id = %s AND id IN ({marcas})", (empresa_id, *ids))}
        for eid in ids:
            if eid not in empleados:
                errores.append(dict(empleado_id=eid, error="No es un empleado de la empresa."))
                continue
            abierta = db.one(c, """SELECT * FROM jl_asignaciones WHERE empleado_id = %s
                                   AND (vigente_hasta IS NULL OR vigente_hasta >= %s)
                                   ORDER BY vigente_desde DESC, id DESC LIMIT 1 FOR UPDATE""", (eid, desde))
            nombre = f"{empleados[eid]['apellido']} {empleados[eid]['nombre']}"
            if abierta and abierta["vigente_desde"] >= desde:
                errores.append(dict(empleado_id=eid, nombre=nombre,
                                    error=f"ya tiene una asignación desde el {abierta['vigente_desde']:%d/%m/%Y}"))
                continue
            if abierta and int(abierta["convenio_id"]) == int(convenio["id"]):
                errores.append(dict(empleado_id=eid, nombre=nombre, error="ya tiene ese convenio"))
                continue
            if abierta:
                c.execute("UPDATE jl_asignaciones SET vigente_hasta = %s WHERE id = %s",
                          (desde - dt.timedelta(days=1), abierta["id"]))
            db.insert(c, "jl_asignaciones", dict(empresa_id=empresa_id, empleado_id=eid, convenio_id=convenio["id"],
                                                 vigente_desde=desde, motivo=motivo and motivo[:255],
                                                 reemplaza_id=abierta["id"] if abierta else None,
                                                 creado_por=who.get("user_id"), creado_at=now_local()))
            asignados += 1
    return asignados, errores


def empleados_para_asignar(empresa_id, filtros=None, fecha=None):
    """Empleados activos con su convenio vigente, para el listado de asignacion masiva."""
    filtros = filtros or {}
    fecha = fecha or _hoy()
    donde, args = ["e.empresa_id = %s", "e.activo = 1"], [empresa_id]
    for clave, columna in (("sucursal_id", "e.sucursal_id"), ("sector_id", "e.sector_id"), ("puesto_id", "e.puesto_id")):
        if str(filtros.get(clave) or "").isdigit():
            donde.append(f"{columna} = %s")
            args.append(int(filtros[clave]))
    if filtros.get("convenio_id") == "sin":
        donde.append("a.id IS NULL")
    elif str(filtros.get("convenio_id") or "").isdigit():
        donde.append("a.convenio_id = %s")
        args.append(int(filtros["convenio_id"]))
    q = str(filtros.get("q") or "").strip()
    if q:
        donde.append("(e.apellido LIKE %s OR e.nombre LIKE %s OR e.legajo LIKE %s)")
        args += [f"%{q}%"] * 3
    with db.transaction(read_only=True) as c:
        return db.all_rows(c, f"""SELECT e.id, e.apellido, e.nombre, e.legajo, su.nombre AS sucursal_nombre,
                                         se.nombre AS sector_nombre, a.convenio_id, cv.nombre AS convenio_nombre,
                                         a.vigente_desde AS convenio_desde
                                  FROM empleados e
                                  LEFT JOIN sucursales su ON su.id = e.sucursal_id
                                  LEFT JOIN sectores se ON se.id = e.sector_id
                                  LEFT JOIN jl_asignaciones a ON a.empleado_id = e.id AND a.vigente_desde <= %s
                                       AND (a.vigente_hasta IS NULL OR a.vigente_hasta >= %s)
                                  LEFT JOIN jl_convenios cv ON cv.id = a.convenio_id
                                  WHERE {' AND '.join(donde)}
                                  ORDER BY e.apellido, e.nombre""", (fecha, fecha, *args))


# --- Condiciones laborales del empleado -----------------------------------------------------------------------

_ORIGEN = {"empleado": "Individual", "convenio": "Convenio", "sucursal": "Sucursal", "empresa": "Empresa", "ley": "Ley"}


def _horario_semana(empleado_id, fecha):
    """Horario asignado vigente en la fecha: dias, bloques y descansos no computables (huecos entre bloques)."""
    from repositories.empleado_horario_repository import get_by_empleado_fecha
    from repositories.horario_dia_bloque_repository import get_by_horario_dia
    from repositories.horario_dia_repository import get_by_horario

    horario = get_by_empleado_fecha(int(empleado_id), fecha.isoformat())
    if not horario:
        return None
    dias = []
    minutos_semana = 0
    for dia in sorted(get_by_horario(horario["horario_id"]) or [], key=lambda d: int(d.get("dia_semana") or 0)):
        bloques = [(_hhmm(b.get("hora_entrada")), _hhmm(b.get("hora_salida"))) for b in get_by_horario_dia(dia["id"]) or []]
        bloques = [b for b in bloques if b[0] and b[1]]
        minutos = sum(_minutos(b[1]) - _minutos(b[0]) for b in bloques)
        descansos = [(bloques[i][1], bloques[i + 1][0]) for i in range(len(bloques) - 1)]
        minutos_semana += minutos
        dias.append(dict(dia=int(dia["dia_semana"]), nombre=NOMBRES_DIA.get(int(dia["dia_semana"])), bloques=bloques,
                         descansos=descansos, minutos=minutos))
    return dict(nombre=horario.get("nombre"), desde=_texto_fecha(horario.get("fecha_desde")),
                hasta=_texto_fecha(horario.get("fecha_hasta")), tolerancia_min=int(horario.get("tolerancia_min") or 0),
                dias=dias, horas_semana=round(minutos_semana / 60, 2))


def _minutos(hhmm):
    h, m = str(hhmm).split(":")[:2]
    return int(h) * 60 + int(m)


def condiciones(who, empleado_id, fecha=None):
    """Condiciones laborales efectivas del empleado en la fecha: valor de cada campo con su origen, convenio, horario
    asignado, topes del convenio y avisos (por ejemplo, un horario que programa mas horas que las pactadas)."""
    fecha = _fecha(fecha, "Fecha") if fecha else _hoy()
    empresa_id = who["empresa_id"]
    with db.transaction(read_only=True) as c:
        empleado = db.one(c, """SELECT e.id, e.empresa_id, e.apellido, e.nombre, e.legajo, e.fecha_ingreso, e.tipo_contrato,
                                       e.categoria, e.sucursal_id, su.nombre AS sucursal_nombre, se.nombre AS sector_nombre,
                                       p.nombre AS puesto_nombre
                                FROM empleados e LEFT JOIN sucursales su ON su.id = e.sucursal_id
                                LEFT JOIN sectores se ON se.id = e.sector_id LEFT JOIN puestos p ON p.id = e.puesto_id
                                WHERE e.id = %s AND e.empresa_id = %s""", (int(empleado_id), empresa_id))
        if not empleado:
            raise Error("Empleado no encontrado.", 404)
        asignacion = _asignacion(c, empleado["id"], fecha)
        reglas = {
            "empleado": _vigentes(c, empresa_id, "empleado", empleado["id"], fecha),
            "convenio": _vigentes(c, empresa_id, "convenio", asignacion["convenio_id"], fecha) if asignacion else None,
            "sucursal": _vigentes(c, empresa_id, "sucursal", empleado["sucursal_id"], fecha) if empleado["sucursal_id"] else None,
            "empresa": _vigentes(c, empresa_id, "empresa", None, fecha),
            "ley": _regla_ley(c, empresa_id, fecha),
        }
        topes = _topes(c, empresa_id, empleado["id"], fecha)
        historial = db.all_rows(c, """SELECT a.*, cv.nombre AS convenio_nombre, u.usuario AS creado_por_usuario
                                      FROM jl_asignaciones a JOIN jl_convenios cv ON cv.id = a.convenio_id
                                      LEFT JOIN usuarios u ON u.id = a.creado_por
                                      WHERE a.empleado_id = %s ORDER BY a.vigente_desde DESC, a.id DESC""", (empleado["id"],))
    campos = []
    for clave, (etiqueta, tipo, _, _, es_tope) in CAMPOS.items():
        origen, valor = None, None
        for nivel in PRECEDENCIA:
            regla = reglas[nivel]
            if regla and regla.get(clave) not in (None, ""):
                origen, valor = nivel, regla[clave]
                break
        campos.append(dict(clave=clave, etiqueta=etiqueta, valor=mostrar(clave, valor), origen=_ORIGEN.get(origen),
                           tope=mostrar(clave, topes.get(clave)) if es_tope else None))
    try:
        horario = _horario_semana(empleado["id"], fecha)
    except Exception:
        horario = None
    efectivos = {c["clave"]: c for c in campos}
    avisos = []
    if not asignacion:
        avisos.append("No tiene convenio asignado: se usan los topes de Fuera de convenio (LCT).")
    pactadas = next((r.get("horas_semanales") for n in PRECEDENCIA for r in [reglas[n]] if r and r.get("horas_semanales")), None)
    if horario and pactadas and horario["horas_semana"] > float(pactadas):
        avisos.append(f"El horario asignado programa {horario['horas_semana']:g} h por semana y la jornada pactada es de "
                      f"{_numero(pactadas):g} h.")
    if not horario:
        avisos.append("No tiene horario asignado en esa fecha.")
    return dict(fecha=fecha.isoformat(), empleado=empleado, convenio=asignacion, campos=campos, efectivos=efectivos,
                horario=horario, avisos=avisos, historial=historial,
                reglas_propias=versiones(empresa_id, "empleado", empleado["id"]))


def resumen_empleado(who, empleado_id):
    """Version corta para la ficha del empleado (no falla si el modulo todavia no esta migrado)."""
    try:
        datos = condiciones(who, empleado_id)
    except Exception:
        return None
    e = datos["efectivos"]
    return dict(convenio=(datos["convenio"] or {}).get("convenio_nombre"), horas_semanales=e["horas_semanales"]["valor"],
                horas_diarias=e["horas_diarias"]["valor"], dias=e["dias_laborales"]["valor"],
                horario=(datos["horario"] or {}).get("nombre"), banco=e["banco_horas_habilitado"]["valor"],
                avisos=datos["avisos"])


# --- Historial ----------------------------------------------------------------------------------------------

def historial(empresa_id, limite=200):
    with db.transaction(read_only=True) as c:
        reglas = db.all_rows(c, """SELECT 'regla' AS tipo, r.id, r.alcance, r.vigente_desde, r.vigente_hasta, r.motivo,
                                          r.creado_at, u.usuario, su.nombre AS sucursal_nombre, cv.nombre AS convenio_nombre,
                                          CONCAT(e.apellido, ' ', e.nombre) AS empleado_nombre
                                   FROM jl_reglas r LEFT JOIN usuarios u ON u.id = r.creado_por
                                   LEFT JOIN sucursales su ON su.id = r.sucursal_id
                                   LEFT JOIN jl_convenios cv ON cv.id = r.convenio_id
                                   LEFT JOIN empleados e ON e.id = r.empleado_id
                                   WHERE r.empresa_id = %s ORDER BY r.creado_at DESC, r.id DESC LIMIT %s""", (empresa_id, limite))
        asignaciones = db.all_rows(c, """SELECT 'asignacion' AS tipo, a.id, 'empleado' AS alcance, a.vigente_desde,
                                                a.vigente_hasta, a.motivo, a.creado_at, u.usuario, NULL AS sucursal_nombre,
                                                cv.nombre AS convenio_nombre, CONCAT(e.apellido, ' ', e.nombre) AS empleado_nombre
                                         FROM jl_asignaciones a JOIN jl_convenios cv ON cv.id = a.convenio_id
                                         JOIN empleados e ON e.id = a.empleado_id LEFT JOIN usuarios u ON u.id = a.creado_por
                                         WHERE a.empresa_id = %s ORDER BY a.creado_at DESC, a.id DESC LIMIT %s""", (empresa_id, limite))
    filas = reglas + asignaciones
    filas.sort(key=lambda f: (str(f["creado_at"]), f["id"]), reverse=True)
    return filas[:limite]


def vista_reglas(empresa_id, fecha=None):
    """Reglas vigentes de la empresa y de cada sucursal, con sus versiones (pantalla Reglas generales)."""
    fecha = fecha or _hoy()
    with db.transaction(read_only=True) as c:
        sucursales = db.all_rows(c, "SELECT id, nombre FROM sucursales WHERE empresa_id = %s ORDER BY nombre", (empresa_id,))
        empresa = _vigentes(c, empresa_id, "empresa", None, fecha)
        por_sucursal = {s["id"]: _vigentes(c, empresa_id, "sucursal", s["id"], fecha) for s in sucursales}
    return dict(empresa=empresa, sucursales=sucursales, por_sucursal=por_sucursal,
                versiones_empresa=versiones(empresa_id, "empresa"))


def valores(regla):
    """Regla -> {clave: texto} para mostrarla."""
    return {clave: mostrar(clave, (regla or {}).get(clave)) for clave in CAMPOS}


# --- Resolucion por lote (motor de calculo, etapa B) ------------------------------------------------------------

class Resolutor:
    """Reglas efectivas de muchos empleados y dias con dos consultas (mismas reglas de precedencia que condiciones)."""

    def __init__(self, empresa_id, empleados, desde, hasta):
        self.empleados = {int(e["id"]): e for e in empleados}
        ids = sorted(self.empleados)
        with db.transaction(read_only=True) as c:
            self.reglas = db.all_rows(c, """SELECT * FROM jl_reglas WHERE empresa_id = %s AND vigente_desde <= %s
                                            AND (vigente_hasta IS NULL OR vigente_hasta >= %s)
                                            ORDER BY vigente_desde DESC, id DESC""", (empresa_id, hasta, desde))
            marcas = ",".join(["%s"] * len(ids)) or "NULL"
            self.asignaciones = db.all_rows(c, f"""SELECT * FROM jl_asignaciones WHERE empleado_id IN ({marcas})
                                                   AND vigente_desde <= %s AND (vigente_hasta IS NULL OR vigente_hasta >= %s)
                                                   ORDER BY vigente_desde DESC, id DESC""", (*ids, hasta, desde)) if ids else []
            lct = db.one(c, "SELECT id FROM jl_convenios WHERE empresa_id = %s AND codigo = 'LCT'", (empresa_id,))
        self.lct_id = lct["id"] if lct else None

    @staticmethod
    def _vigente(filas, fecha, **filtro):
        for f in filas:
            if all(f.get(k) == v for k, v in filtro.items()) and f["vigente_desde"] <= fecha \
                    and (f["vigente_hasta"] is None or f["vigente_hasta"] >= fecha):
                return f
        return None

    def efectivas(self, empleado_id, fecha):
        """({campo: valor}, [ids de regla usados], convenio_id) del empleado en la fecha."""
        empleado = self.empleados[int(empleado_id)]
        asignacion = self._vigente(self.asignaciones, fecha, empleado_id=int(empleado_id))
        convenio_id = asignacion["convenio_id"] if asignacion else None
        niveles = {
            "empleado": self._vigente(self.reglas, fecha, alcance="empleado", empleado_id=int(empleado_id)),
            "convenio": self._vigente(self.reglas, fecha, alcance="convenio", convenio_id=convenio_id) if convenio_id else None,
            "sucursal": self._vigente(self.reglas, fecha, alcance="sucursal", sucursal_id=empleado.get("sucursal_id"))
            if empleado.get("sucursal_id") else None,
            "empresa": self._vigente(self.reglas, fecha, alcance="empresa"),
            "ley": self._vigente(self.reglas, fecha, alcance="convenio", convenio_id=self.lct_id) if self.lct_id else None,
        }
        valores, usadas = {}, []
        for clave in CAMPOS:
            for nivel in PRECEDENCIA:
                regla = niveles[nivel]
                if regla and regla.get(clave) not in (None, ""):
                    valores[clave] = regla[clave]
                    if regla["id"] not in usadas:
                        usadas.append(regla["id"])
                    break
        return valores, usadas, convenio_id
