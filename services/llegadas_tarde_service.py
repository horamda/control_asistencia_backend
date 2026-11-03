"""Reporte de llegadas tarde por periodo, sucursal, sector y persona/legajo.

Cada tramo del dia (ingreso de la manana, vuelta del almuerzo...) se compara con el bloque de su horario
esperado: es tarde si entra despues del inicio del bloque + la tolerancia, igual que el estado "tarde" de la
asistencia. Los minutos de atraso se cuentan desde el inicio del bloque. Se recalcula porque un dia con
llegada tarde y salida anticipada queda guardado como "salida_anticipada"."""

import datetime as dt
from collections import defaultdict

from repositories import carga_repository as db
from utils.asistencia import _is_within_blocks, _to_minutes, get_horario_esperado

MAX_DIAS = 366


def _hhmm(minutos):
    return f"{minutos // 60:02d}:{minutos % 60:02d}"


def _periodo(desde, hasta):
    if desde > hasta:
        desde, hasta = hasta, desde
    if (hasta - desde).days >= MAX_DIAS:
        raise ValueError("El período máximo es de un año.")
    return desde, hasta


def reporte(*, desde, hasta, empresa_id=None, sucursal_id=None, sector_id=None, q=None, horario=get_horario_esperado):
    desde, hasta = _periodo(desde, hasta)
    where = ["a.fecha BETWEEN %s AND %s", "a.hora_entrada IS NOT NULL"]
    args = [desde, hasta]
    for campo, valor in (("e.empresa_id", empresa_id), ("e.sucursal_id", sucursal_id), ("e.sector_id", sector_id)):
        if valor:
            where.append(f"{campo} = %s")
            args.append(int(valor))
    texto = (q or "").strip()
    if texto:
        where.append("(e.legajo = %s OR CONCAT(e.apellido, ' ', e.nombre) LIKE %s OR CONCAT(e.nombre, ' ', e.apellido) LIKE %s)")
        args += [texto, f"%{texto}%", f"%{texto}%"]
    filtro = " AND ".join(where)
    with db.transaction(read_only=True) as c:
        # Solo los tramos que pueden ser tarde: la regla ya los dejo como tarde o como salida anticipada.
        candidatos = db.all_rows(
            c,
            f"""SELECT a.id, a.fecha, a.empleado_id, a.hora_entrada, e.legajo, e.apellido, e.nombre,
                       s.nombre AS sector_nombre, su.nombre AS sucursal_nombre
                FROM asistencias a JOIN empleados e ON e.id = a.empleado_id
                LEFT JOIN sectores s ON s.id = e.sector_id LEFT JOIN sucursales su ON su.id = e.sucursal_id
                WHERE {filtro} AND a.estado IN ('tarde', 'salida_anticipada')
                ORDER BY a.fecha, e.apellido, e.nombre, a.hora_entrada""",
            tuple(args))
        trabajados = {r["empleado_id"]: int(r["dias"]) for r in db.all_rows(
            c,
            f"""SELECT a.empleado_id, COUNT(DISTINCT a.fecha) AS dias
                FROM asistencias a JOIN empleados e ON e.id = a.empleado_id
                WHERE {filtro} GROUP BY a.empleado_id""",
            tuple(args))}

    esperados = {}
    detalle = []
    for row in candidatos:
        fecha = row["fecha"] if isinstance(row["fecha"], dt.date) else dt.date.fromisoformat(str(row["fecha"])[:10])
        clave = (row["empleado_id"], fecha)
        if clave not in esperados:
            esperados[clave] = horario(row["empleado_id"], fecha.isoformat()) or {}
        esperado = esperados[clave]
        entrada = _to_minutes(row["hora_entrada"])
        dentro, inicio, _ = _is_within_blocks(esperado.get("bloques") or [], entrada)
        tolerancia = int(esperado.get("tolerancia") or 0)
        if not dentro or entrada <= inicio + tolerancia:
            continue
        detalle.append(dict(row, fecha=fecha, entrada=_hhmm(entrada), esperada=_hhmm(inicio), tolerancia=tolerancia,
                            atraso=entrada - inicio))

    personas = {}
    for d in detalle:
        p = personas.setdefault(d["empleado_id"], dict(
            empleado_id=d["empleado_id"], legajo=d["legajo"], apellido=d["apellido"], nombre=d["nombre"],
            sector_nombre=d["sector_nombre"], sucursal_nombre=d["sucursal_nombre"], veces=0, dias=set(), minutos=0,
            maximo=0))
        p["veces"] += 1
        p["dias"].add(d["fecha"])
        p["minutos"] += d["atraso"]
        p["maximo"] = max(p["maximo"], d["atraso"])
    for p in personas.values():
        p["dias"] = len(p["dias"])
        p["dias_trabajados"] = trabajados.get(p["empleado_id"], p["dias"])
        p["pct"] = round(100 * p["dias"] / p["dias_trabajados"]) if p["dias_trabajados"] else 0
        p["promedio"] = round(p["minutos"] / p["veces"])
    ranking = sorted(personas.values(), key=lambda p: (-p["veces"], -p["minutos"], p["apellido"] or ""))

    def agrupar(campo):
        grupos = defaultdict(lambda: dict(veces=0, minutos=0, personas=set()))
        for d in detalle:
            g = grupos[d[campo] or "Sin asignar"]
            g["veces"] += 1
            g["minutos"] += d["atraso"]
            g["personas"].add(d["empleado_id"])
        return sorted(({"nombre": k, "veces": v["veces"], "minutos": v["minutos"], "personas": len(v["personas"])}
                       for k, v in grupos.items()), key=lambda g: -g["veces"])

    minutos = sum(d["atraso"] for d in detalle)
    totales = dict(veces=len(detalle), personas=len(personas), minutos=minutos,
                   promedio=round(minutos / len(detalle)) if detalle else 0,
                   empleados_con_asistencia=len(trabajados))
    return dict(desde=desde, hasta=hasta, totales=totales, ranking=ranking, detalle=detalle,
                por_sector=agrupar("sector_nombre"), por_sucursal=agrupar("sucursal_nombre"))


def excel(datos):
    """Libro con el resumen por persona, por sector/sucursal y el detalle de cada llegada tarde."""
    import io
    from openpyxl import Workbook
    from openpyxl.styles import Font

    libro = Workbook()
    hojas = (
        ("Por persona", ["Legajo", "Apellido y nombre", "Sector", "Sucursal", "Llegadas tarde", "Días tarde",
                         "Días trabajados", "% días", "Minutos totales", "Promedio (min)", "Máximo (min)"],
         [[p["legajo"], f"{p['apellido']} {p['nombre']}", p["sector_nombre"], p["sucursal_nombre"], p["veces"], p["dias"],
           p["dias_trabajados"], p["pct"] / 100, p["minutos"], p["promedio"], p["maximo"]] for p in datos["ranking"]]),
        ("Por sector", ["Sector", "Llegadas tarde", "Personas", "Minutos totales"],
         [[g["nombre"], g["veces"], g["personas"], g["minutos"]] for g in datos["por_sector"]]),
        ("Por sucursal", ["Sucursal", "Llegadas tarde", "Personas", "Minutos totales"],
         [[g["nombre"], g["veces"], g["personas"], g["minutos"]] for g in datos["por_sucursal"]]),
        ("Detalle", ["Fecha", "Legajo", "Apellido y nombre", "Sector", "Sucursal", "Hora esperada", "Tolerancia (min)",
                     "Ingreso", "Atraso (min)"],
         [[d["fecha"], d["legajo"], f"{d['apellido']} {d['nombre']}", d["sector_nombre"], d["sucursal_nombre"],
           d["esperada"], d["tolerancia"], d["entrada"], d["atraso"]] for d in datos["detalle"]]),
    )
    for i, (titulo, encabezado, filas) in enumerate(hojas):
        hoja = libro.active if i == 0 else libro.create_sheet()
        hoja.title = titulo
        hoja.append([f"Llegadas tarde del {datos['desde']:%d/%m/%Y} al {datos['hasta']:%d/%m/%Y}"])
        hoja.append([])
        hoja.append(encabezado)
        for celda in hoja[3]:
            celda.font = Font(bold=True)
        for fila in filas:
            hoja.append(fila)
        if titulo == "Por persona":
            for celda in hoja["H"][3:]:
                celda.number_format = "0%"
        if titulo == "Detalle":
            for celda in hoja["A"][3:]:
                celda.number_format = "DD/MM/YYYY"
        for columna in hoja.columns:
            hoja.column_dimensions[columna[2].column_letter].width = max(12, min(40, max(
                len(str(c.value or "")) for c in columna[2:]) + 2))
        hoja.freeze_panes = "A4"
    salida = io.BytesIO()
    libro.save(salida)
    return salida.getvalue()
