"""Feriados y dias no laborables: el mismo calendario del reporte mensual de asistencia
(asistencia_dias_no_laborables), con nombre (motivo) para mostrar.

Alcances: (0, 0, 0) todas las empresas; (empresa, 0, 0) toda la empresa; (empresa, sucursal, 0) una
sucursal; los de un sector se usan en los reportes de asistencia pero no mueven una reunion entera.
Las reuniones usan este calendario para posponer u omitir las fechas que caen en un dia no laborable."""

import datetime as dt
import json
import logging
import urllib.request

from repositories import carga_repository as db
from services.carga_service import CargaError as Error, now_local

logger = logging.getLogger(__name__)

API_NACIONALES = "https://api.argentinadatos.com/v1/feriados/{anio}"
# Los "puentes turisticos" son no laborables optativos para el sector privado: no se importan.
TIPOS_IMPORTADOS = {"inamovible", "trasladable"}
SIN_NOMBRE = "Día no laborable"
_ALCANCE = "((d.empresa_id = 0 AND d.sucursal_id = 0 AND d.sector_id = 0) OR d.empresa_id = %s)"


def mapa(c, empresa_id):
    """{sucursal_id: {fecha: nombre}} de los dias que mueven reuniones; la clave 0 aplica a todas."""
    salida = {}
    for row in db.all_rows(c, f"""SELECT d.sucursal_id, d.fecha, d.motivo FROM asistencia_dias_no_laborables d
                                   WHERE {_ALCANCE} AND d.sector_id = 0""", (empresa_id,)):
        salida.setdefault(int(row["sucursal_id"] or 0), {})[row["fecha"]] = row["motivo"] or SIN_NOMBRE
    return salida


def de_sucursal(mapa_feriados, sucursal_id):
    """Dias no laborables que aplican a una sucursal (los generales mas los propios)."""
    feriados = dict(mapa_feriados.get(0, {}))
    if sucursal_id:
        feriados.update(mapa_feriados.get(int(sucursal_id), {}))
    return feriados


def listar(who, anio):
    with db.transaction(read_only=True) as c:
        return db.all_rows(
            c, f"""SELECT d.*, su.nombre AS sucursal_nombre, se.nombre AS sector_nombre
                   FROM asistencia_dias_no_laborables d
                   LEFT JOIN sucursales su ON su.id = d.sucursal_id
                   LEFT JOIN sectores se ON se.id = d.sector_id
                   WHERE {_ALCANCE} AND d.fecha BETWEEN %s AND %s
                   ORDER BY d.fecha, d.empresa_id, su.nombre, se.nombre""",
            (who["empresa_id"], dt.date(anio, 1, 1), dt.date(anio, 12, 31)))


def reprogramar(c, empresa_id, desde):
    """Las fechas futuras de reuniones sin registros se recalculan con el calendario nuevo.
    empresa_id None (o 0) = todas las empresas."""
    sql = """DELETE o FROM reunion_ocurrencias o WHERE o.estado='programada' AND o.fecha >= %s
             AND NOT EXISTS (SELECT 1 FROM reunion_asistencias a WHERE a.ocurrencia_id=o.id)"""
    args = [desde]
    if empresa_id:
        sql += " AND o.empresa_id=%s"
        args.append(int(empresa_id))
    try:
        c.execute(sql, tuple(args))
    except Exception as exc:  # instalaciones sin el modulo de reuniones
        if getattr(exc, "errno", None) != 1146:
            raise


def reprogramar_reuniones(empresa_id, desde):
    with db.transaction() as c:
        reprogramar(c, empresa_id, desde)


def _desde(fecha):
    return min(fecha, now_local().date())


def guardar(who, data):
    try:
        fecha = dt.date.fromisoformat(str(data.get("fecha") or ""))
    except ValueError:
        raise Error("Fecha inválida.")
    nombre = str(data.get("nombre") or "").strip()[:255]
    if not nombre:
        raise Error("Indicá el nombre del feriado.")
    sucursal_id = int(data["sucursal_id"]) if str(data.get("sucursal_id") or "").isdigit() else 0
    with db.transaction() as c:
        if sucursal_id and not db.one(c, "SELECT id FROM sucursales WHERE id=%s AND empresa_id=%s",
                                      (sucursal_id, who["empresa_id"])):
            raise Error("Sucursal inválida.")
        # Ya marcado para todos (o para la empresa): no hace falta repetirlo.
        if db.one(c, f"""SELECT d.id FROM asistencia_dias_no_laborables d WHERE {_ALCANCE} AND d.sector_id = 0
                         AND d.sucursal_id IN (0, %s) AND d.fecha = %s""", (who["empresa_id"], sucursal_id, fecha)):
            raise Error("Ese día ya está marcado como no laborable. Podés cambiarle el nombre en la lista.", 409)
        db.insert(c, "asistencia_dias_no_laborables", dict(
            empresa_id=who["empresa_id"], sucursal_id=sucursal_id, sector_id=0, fecha=fecha, motivo=nombre,
            created_by_usuario_id=who.get("user_id")))
        reprogramar(c, who["empresa_id"], _desde(fecha))
    return fecha


def _propio(c, who, dia_id):
    row = db.one(c, f"SELECT d.* FROM asistencia_dias_no_laborables d WHERE d.id=%s AND {_ALCANCE}",
                 (int(dia_id), who["empresa_id"]))
    if not row:
        raise Error("Día no encontrado.", 404)
    return row


def renombrar(who, dia_id, nombre):
    nombre = str(nombre or "").strip()[:255]
    with db.transaction() as c:
        row = _propio(c, who, dia_id)
        c.execute("UPDATE asistencia_dias_no_laborables SET motivo=%s WHERE id=%s", (nombre or None, row["id"]))
    return row


def eliminar(who, dia_id):
    with db.transaction() as c:
        row = _propio(c, who, dia_id)
        c.execute("DELETE FROM asistencia_dias_no_laborables WHERE id=%s", (row["id"],))
        reprogramar(c, row["empresa_id"], _desde(row["fecha"]))
    return row


def descargar_nacionales(anio):
    request = urllib.request.Request(API_NACIONALES.format(anio=int(anio)),
                                     headers={"Accept": "application/json", "User-Agent": "FichaYa"})
    with urllib.request.urlopen(request, timeout=10) as response:  # noqa: S310 (URL fija)
        return json.loads(response.read().decode("utf-8"))


def importar_nacionales(who, anio, *, fetch=None):
    """Marca los feriados nacionales del año para todas las empresas. Los dias que ya estaban
    marcados sin nombre lo reciben; los que tienen nombre no se tocan."""
    anio = int(anio)
    if not 2000 <= anio <= 2100:
        raise Error("Año inválido.")
    try:
        datos = (fetch or descargar_nacionales)(anio)
    except Exception:
        logger.warning("feriados_importar_error", exc_info=True, extra={"extra": {"anio": anio}})
        raise Error("No se pudo consultar el calendario oficial. Probá más tarde o cargalos a mano.", 502)
    nuevos = nombrados = existentes = omitidos = 0
    with db.transaction() as c:
        for item in datos if isinstance(datos, list) else []:
            try:
                fecha = dt.date.fromisoformat(str(item.get("fecha")))
            except ValueError:
                fecha = None
            if str(item.get("tipo") or "").lower() not in TIPOS_IMPORTADOS or not fecha or fecha.year != anio:
                omitidos += 1
                continue
            nombre = str(item.get("nombre") or "Feriado")[:255]
            previo = db.one(c, """SELECT id, motivo FROM asistencia_dias_no_laborables
                                  WHERE empresa_id=0 AND sucursal_id=0 AND sector_id=0 AND fecha=%s""", (fecha,))
            if not previo:
                db.insert(c, "asistencia_dias_no_laborables", dict(
                    empresa_id=0, sucursal_id=0, sector_id=0, fecha=fecha, motivo=nombre,
                    created_by_usuario_id=who.get("user_id")))
                nuevos += 1
            elif not previo["motivo"]:
                c.execute("UPDATE asistencia_dias_no_laborables SET motivo=%s WHERE id=%s", (nombre, previo["id"]))
                nombrados += 1
            else:
                existentes += 1
        if nuevos:
            reprogramar(c, None, now_local().date())
    return dict(nuevos=nuevos, nombrados=nombrados, existentes=existentes, omitidos=omitidos)
