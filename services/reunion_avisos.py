"""Avisos push de reuniones (solo si Firebase esta configurado; nunca rompen la accion del panel).

- Reunion nueva o cambio de horario / dias / lugar: a los convocados de cada sede, con su horario.
- Fecha cancelada, reactivada o con horario cambiado: a los convocados de la sede afectada.
- Recordatorio 30 minutos antes a quien todavia no registro (scheduler cada 5 minutos)."""

import datetime as dt
import logging

from repositories import carga_repository as db
from services import push_service
from services import reunion_service as s
from services.carga_service import now_local

logger = logging.getLogger(__name__)
ANTICIPACION_MIN = 30


def _dia(fecha):
    return f"{s.DIAS[fecha.weekday()].lower()} {fecha:%d/%m}"


def _datos(reunion_id, fecha=None):
    datos = {"reunion_id": reunion_id, "ruta": f"/reuniones/{reunion_id}"}
    if fecha:
        datos["fecha"] = fecha.isoformat()
    return datos


def firma(who, reunion_id):
    """Lo que el empleado ve de la reunion (por sede): si cambia al editar, se avisa."""
    try:
        with db.transaction(read_only=True) as c:
            base = s.obtener(c, who, reunion_id)
            return (bool(base["activa"]), tuple((x["sucursal_id"], s.describir(x), x.get("lugar") or "")
                                               for x in s.sedes_efectivas(c, base)))
    except Exception:
        return None


def reunion_guardada(who, reunion_id, *, nueva, antes=None):
    if not push_service.activo():
        return 0
    try:
        actual = firma(who, reunion_id)
        if not actual or not actual[0] or (not nueva and actual == antes):
            return 0
        tipo, titulo = ("reunion_nueva", "Nueva reunión") if nueva else ("reunion_cambio", "Cambió una reunión")
        total = 0
        with db.transaction() as c:
            base = s.obtener(c, who, reunion_id)
            marca = f"{base['updated_at']:%Y%m%d%H%M%S}" if base.get("updated_at") else ""
            for x in s.sedes_efectivas(c, base):
                ids = [e["id"] for e in s.convocados(c, x, x["sucursal_id"] or None)]
                lugar = f" · {x['lugar']}" if x.get("lugar") else ""
                total += push_service.encolar(c, base["empresa_id"], ids, tipo, titulo,
                                              f"{base['nombre']}: {s.describir(x)}{lugar}", _datos(reunion_id),
                                              clave=f"{tipo}:{reunion_id}:{x['sucursal_id']}:{marca}")
        return total
    except Exception:
        logger.warning("reunion_aviso_error", exc_info=True, extra={"extra": {"reunion_id": reunion_id}})
        return 0


def _por_sede(who, reunion_id, fecha, sucursal_id, armar, tipo):
    """Encola un aviso por cada sede afectada (sucursal_id None = todas las que tienen esa fecha)."""
    if not push_service.activo():
        return 0
    try:
        total = 0
        with db.transaction() as c:
            base = s.obtener(c, who, reunion_id)
            sedes = s.sedes_efectivas(c, base)
            if sucursal_id is not None:
                sedes = [x for x in sedes if x["sucursal_id"] == int(sucursal_id or 0)]
            for x in sedes:
                occ = s.ocurrencia(c, x, fecha, crear=False)
                if not occ and not s.ocurre_en(x, fecha):
                    continue
                titulo, cuerpo = armar(base, x, occ)
                ids = [e["id"] for e in s.convocados(c, x, x["sucursal_id"] or None)]
                total += push_service.encolar(c, base["empresa_id"], ids, tipo, titulo, cuerpo, _datos(reunion_id, fecha),
                                              clave=f"{tipo}:{reunion_id}:{x['sucursal_id']}:{fecha}:{now_local():%Y%m%d%H%M%S}")
        return total
    except Exception:
        logger.warning("reunion_aviso_error", exc_info=True, extra={"extra": {"reunion_id": reunion_id, "tipo": tipo}})
        return 0


def fecha_cancelada(who, reunion_id, fecha, sucursal_id, motivo, *, reactivada=False):
    fecha = s._date(fecha)
    if reactivada:
        return _por_sede(who, reunion_id, fecha, sucursal_id, lambda b, x, o: (
            "Reunión reactivada", f"{b['nombre']} del {_dia(fecha)} vuelve a estar programada."), "reunion_reactivada")
    detalle = f": {motivo.strip()}" if (motivo or "").strip() else "."
    return _por_sede(who, reunion_id, fecha, sucursal_id, lambda b, x, o: (
        "Reunión cancelada", f"Se canceló {b['nombre']} del {_dia(fecha)}{detalle}"), "reunion_cancelada")


def fecha_reprogramada(who, reunion_id, fecha, sucursal_id, *, restaurada=False):
    fecha = s._date(fecha)

    def armar(base, x, occ):
        hora = s._hhmm(occ["inicio"]) if occ else s._hhmm(s.horarios(x, fecha)["inicio"])
        if restaurada:
            return "Cambio de horario", f"{base['nombre']} del {_dia(fecha)} vuelve a su horario: {hora}."
        return "Cambio de horario", f"{base['nombre']} del {_dia(fecha)} pasa a las {hora}."
    return _por_sede(who, reunion_id, fecha, sucursal_id, armar, "reunion_horario")


def recordatorios(ahora=None, anticipacion=ANTICIPACION_MIN):
    """Encola el recordatorio de las reuniones que empiezan en los proximos minutos, a quien todavia no
    registro. Una sola vez por fecha, sede y empleado (clave)."""
    if not push_service.activo():
        return 0
    ahora = ahora or now_local()
    hasta = ahora + dt.timedelta(minutes=anticipacion)
    total = 0
    with db.transaction(read_only=True) as c:
        reuniones = db.all_rows(c, "SELECT * FROM reuniones WHERE activa = 1")
    for base in reuniones:
        try:
            with db.transaction() as c:
                for x in s.sedes_efectivas(c, base):
                    occ = s.ocurrencia(c, x, ahora.date(), crear=False)
                    if not occ and not s.ocurre_en(x, ahora.date()):
                        continue
                    if occ and occ["estado"] != "programada":
                        continue
                    h = occ or s.horarios(x, ahora.date())
                    if not ahora < h["inicio"] <= hasta:
                        continue
                    registrados = {r["empleado_id"] for r in db.all_rows(
                        c, "SELECT empleado_id FROM reunion_asistencias WHERE ocurrencia_id=%s", (occ["id"],))} if occ else set()
                    ids = [e["id"] for e in s.convocados(c, x, x["sucursal_id"] or None) if e["id"] not in registrados]
                    minutos = max(1, int((h["inicio"] - ahora).total_seconds() // 60))
                    lugar = f" en {x['lugar']}" if x.get("lugar") else ""
                    total += push_service.encolar(
                        c, base["empresa_id"], ids, "recordatorio", f"{base['nombre']} a las {s._hhmm(h['inicio'])}",
                        f"Empieza en {minutos} min{lugar}. Escaneá el QR al llegar.", _datos(base["id"], ahora.date()),
                        clave=f"rec:{base['id']}:{x['sucursal_id']}:{ahora.date()}")
        except Exception:
            logger.warning("reunion_recordatorio_error", exc_info=True, extra={"extra": {"reunion_id": base["id"]}})
    return total
