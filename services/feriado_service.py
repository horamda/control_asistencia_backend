"""Calendario de feriados de la empresa: nacionales (importados), propios o de una sucursal.

Lo usan las reuniones para posponer u omitir las fechas que caen en feriado."""

import datetime as dt
import json
import logging
import urllib.request

from repositories import carga_repository as db
from services.carga_service import CargaError as Error, now_local

logger = logging.getLogger(__name__)

API_NACIONALES = "https://api.argentinadatos.com/v1/feriados/{anio}"
# Los "puentes turisticos" son no laborables optativos para el sector privado: no se importan.
TIPOS_IMPORTADOS = {"inamovible": "nacional", "trasladable": "nacional"}
TIPOS = ("nacional", "empresa", "sucursal")


def mapa(c, empresa_id):
    """{sucursal_id: {fecha: nombre}}; la clave 0 son los feriados de toda la empresa."""
    salida = {}
    for row in db.all_rows(c, "SELECT sucursal_id, fecha, nombre FROM feriados WHERE empresa_id=%s", (empresa_id,)):
        salida.setdefault(int(row["sucursal_id"]), {})[row["fecha"]] = row["nombre"]
    return salida


def de_sucursal(mapa_feriados, sucursal_id):
    """Feriados que aplican a una sucursal (los generales mas los propios)."""
    feriados = dict(mapa_feriados.get(0, {}))
    if sucursal_id:
        feriados.update(mapa_feriados.get(int(sucursal_id), {}))
    return feriados


def listar(who, anio):
    with db.transaction(read_only=True) as c:
        return db.all_rows(
            c, """SELECT f.*, su.nombre AS sucursal_nombre FROM feriados f
                  LEFT JOIN sucursales su ON su.id = f.sucursal_id
                  WHERE f.empresa_id=%s AND f.fecha BETWEEN %s AND %s ORDER BY f.fecha, su.nombre""",
            (who["empresa_id"], dt.date(anio, 1, 1), dt.date(anio, 12, 31)))


def _reprogramar(c, empresa_id, desde):
    """Las fechas futuras sin registros se recalculan con el calendario nuevo."""
    c.execute("""DELETE o FROM reunion_ocurrencias o WHERE o.empresa_id=%s AND o.estado='programada' AND o.fecha >= %s
                 AND NOT EXISTS (SELECT 1 FROM reunion_asistencias a WHERE a.ocurrencia_id=o.id)""", (empresa_id, desde))


def guardar(who, data):
    try:
        fecha = dt.date.fromisoformat(str(data.get("fecha") or ""))
    except ValueError:
        raise Error("Fecha inválida.")
    nombre = str(data.get("nombre") or "").strip()[:150]
    if not nombre:
        raise Error("Indicá el nombre del feriado.")
    sucursal_id = int(data["sucursal_id"]) if str(data.get("sucursal_id") or "").isdigit() else 0
    with db.transaction() as c:
        if sucursal_id and not db.one(c, "SELECT id FROM sucursales WHERE id=%s AND empresa_id=%s",
                                      (sucursal_id, who["empresa_id"])):
            raise Error("Sucursal inválida.")
        if db.one(c, "SELECT id FROM feriados WHERE empresa_id=%s AND sucursal_id=%s AND fecha=%s",
                  (who["empresa_id"], sucursal_id, fecha)):
            raise Error("Ya hay un feriado cargado en esa fecha.", 409)
        db.insert(c, "feriados", dict(empresa_id=who["empresa_id"], sucursal_id=sucursal_id, fecha=fecha, nombre=nombre,
                                      tipo="sucursal" if sucursal_id else "empresa", origen="manual",
                                      creado_por=who.get("user_id"), created_at=now_local()))
        _reprogramar(c, who["empresa_id"], min(fecha, now_local().date()))
    return fecha


def eliminar(who, feriado_id):
    with db.transaction() as c:
        row = db.one(c, "SELECT * FROM feriados WHERE id=%s AND empresa_id=%s", (int(feriado_id), who["empresa_id"]))
        if not row:
            raise Error("Feriado no encontrado.", 404)
        c.execute("DELETE FROM feriados WHERE id=%s", (row["id"],))
        _reprogramar(c, who["empresa_id"], min(row["fecha"], now_local().date()))
    return row


def descargar_nacionales(anio):
    request = urllib.request.Request(API_NACIONALES.format(anio=int(anio)),
                                     headers={"Accept": "application/json", "User-Agent": "FichaYa"})
    with urllib.request.urlopen(request, timeout=10) as response:  # noqa: S310 (URL fija)
        return json.loads(response.read().decode("utf-8"))


def importar_nacionales(who, anio, *, fetch=None):
    """Importa los feriados nacionales del año. No pisa los cargados a mano."""
    anio = int(anio)
    if not 2000 <= anio <= 2100:
        raise Error("Año inválido.")
    try:
        datos = (fetch or descargar_nacionales)(anio)
    except Exception:
        logger.warning("feriados_importar_error", exc_info=True, extra={"extra": {"anio": anio}})
        raise Error("No se pudo consultar el calendario oficial. Probá más tarde o cargalos a mano.", 502)
    nuevos = existentes = omitidos = 0
    with db.transaction() as c:
        for item in datos if isinstance(datos, list) else []:
            tipo = TIPOS_IMPORTADOS.get(str(item.get("tipo") or "").lower())
            try:
                fecha = dt.date.fromisoformat(str(item.get("fecha")))
            except ValueError:
                fecha = None
            if not tipo or not fecha or fecha.year != anio:
                omitidos += 1
                continue
            c.execute("""INSERT IGNORE INTO feriados (empresa_id, sucursal_id, fecha, nombre, tipo, origen, creado_por, created_at)
                         VALUES (%s, 0, %s, %s, %s, 'importado', %s, %s)""",
                      (who["empresa_id"], fecha, str(item.get("nombre") or "Feriado")[:150], tipo, who.get("user_id"),
                       now_local()))
            if c.rowcount:
                nuevos += 1
            else:
                existentes += 1
        if nuevos:
            _reprogramar(c, who["empresa_id"], now_local().date())
    return dict(nuevos=nuevos, existentes=existentes, omitidos=omitidos)
