"""Bandeja de notificaciones del empleado (campana de la app): lo que pasa queda guardado aunque el push falle.

Cada novedad relevante (comunicado, solicitud resuelta, feedback, reunion, ...) crea una fila por destinatario en
empleado_notificaciones, en la misma transaccion en que se encola el push (push_service.encolar). El push solo avisa;
la bandeja es la fuente de verdad del contador de no leidas y de las lecturas, compartidas entre dispositivos.

- Una fila por (empleado, clave del evento): los reintentos del push y un evento repetido no la duplican.
- Una solicitud que sigue pendiente no genera filas nuevas: solo se crean ante un evento (envio, resolucion, cambio).
- Los recordatorios efimeros (reunion por empezar, salida sin fichar, trivia por cerrar, viaticos del dia 5,
  accion de seguridad por vencer) salen solo por push: ver SOLO_PUSH.
- Leer una notificacion no cambia el tramite. Los comunicados sincronizan su lectura con comunicado_destinatarios."""

import datetime as dt
import json
import logging
import uuid

from repositories import carga_repository as db
from services.carga_service import CargaError as Error, now_local

logger = logging.getLogger(__name__)

POR_PAGINA = 20
POR_PAGINA_MAX = 50

# tipo de push -> (modulo, tipo de referencia, campo de datos con el id del registro). modulo es el filtro de la app.
CATALOGO = {
    "comunicado": ("comunicados", "comunicado", "comunicado_id"),
    "adelanto": ("adelantos", "adelanto", "adelanto_id"),
    "pedido_mercaderia": ("pedidos_mercaderia", "pedido_mercaderia", "pedido_id"),
    "feedback_asignado": ("feedback", "feedback", "feedback_id"),
    "feedback_resuelto": ("feedback", "feedback", "feedback_id"),
    "reintegro": ("reintegros", "reintegro", "solicitud_id"),
    "reunion_nueva": ("reuniones", "reunion", "reunion_id"),
    "reunion_cambio": ("reuniones", "reunion", "reunion_id"),
    "reunion_cancelada": ("reuniones", "reunion", "reunion_id"),
    "reunion_reactivada": ("reuniones", "reunion", "reunion_id"),
    "reunion_horario": ("reuniones", "reunion", "reunion_id"),
    "justificacion": ("justificaciones", "justificacion", "justificacion_id"),
    "vacaciones": ("vacaciones", "vacaciones", "movimiento_id"),
    "epp_resuelto": ("epp", "epp", "pedido_id"),
    "epp_entregado": ("epp", "epp", "pedido_id"),
    "seguridad_resultado": ("seguridad", "seguridad_evento", "evento_id"),
    "seguridad_accion": ("seguridad", "seguridad_accion", "accion_id"),
    "trivia_nueva": ("trivias", "trivia", "trivia_id"),
    "revision_pendiente": ("revisiones", None, "registro_id"),  # referencia segun datos.modulo (_referencia)
}
# Solo push, sin bandeja: recordatorios que pierden sentido pasado el momento y la notificacion de prueba.
SOLO_PUSH = frozenset({"prueba", "salida_pendiente", "recordatorio", "trivia_recordatorio", "reintegro_recordatorio"})

# Solicitudes para revisar (a jefes / RR. HH. / Seguridad): modulo de la regla -> tipo de referencia.
_REVISION = {"justificaciones": "justificacion", "vacaciones": "vacaciones", "reintegros": "reintegro",
             "epp": "epp", "seguridad_higiene": "seguridad_evento"}

# Acceso al registro relacionado: (SQL con id [y empresa], usa empresa, columnas de quien puede verlo).
# Sin columnas = alcanza con que exista en la empresa (la pantalla de destino valida el resto).
_REFERENCIAS = {
    "comunicado": ("""SELECT d.empleado_id AS a FROM comunicado_destinatarios d JOIN comunicados c ON c.id = d.comunicado_id
                      WHERE d.comunicado_id = %s AND c.empresa_id = %s""", True, ("a",)),
    "adelanto": ("SELECT empleado_id AS a FROM adelantos WHERE id = %s AND empresa_id = %s", True, ("a",)),
    "pedido_mercaderia": ("SELECT empleado_id AS a FROM pedidos_mercaderia WHERE id = %s AND empresa_id = %s", True, ("a",)),
    "feedback": ("""SELECT empleado_id AS a, responsable_id AS b, jefe_directo_id AS c FROM feedbacks
                    WHERE id = %s AND empresa_id = %s""", True, ("a", "b", "c")),
    "reintegro": ("SELECT empleado_id AS a FROM reintegro_solicitudes WHERE id = %s AND empresa_id = %s", True, ("a",)),
    "reunion": ("SELECT id FROM reuniones WHERE id = %s AND empresa_id = %s", True, ()),
    "justificacion": ("""SELECT j.empleado_id AS a FROM justificaciones j JOIN empleados e ON e.id = j.empleado_id
                         WHERE j.id = %s AND e.empresa_id = %s""", True, ("a",)),
    "vacaciones": ("SELECT empleado_id AS a FROM vacaciones_movimientos WHERE id = %s AND empresa_id = %s", True, ("a",)),
    "epp": ("SELECT empleado_id AS a FROM epp_pedidos WHERE id = %s AND empresa_id = %s", True, ("a",)),
    "seguridad_evento": ("SELECT reportante_id AS a FROM sh_eventos WHERE id = %s AND empresa_id = %s", True, ("a",)),
    "seguridad_accion": ("""SELECT a.responsable_id AS a FROM sh_acciones a JOIN sh_eventos ev ON ev.id = a.evento_id
                            WHERE a.id = %s AND ev.empresa_id = %s""", True, ("a",)),
    "trivia": ("SELECT id FROM trivias WHERE id = %s", False, ()),  # las trivias son de todas las empresas
}

_COLUMNAS = """id, tipo, modulo, titulo, mensaje, referencia_tipo, referencia_id, ruta, datos, creado_at, leido_at"""


# --- Alta (desde push_service.encolar) ---------------------------------------------------------------

def en_bandeja(tipo):
    return tipo in CATALOGO and tipo not in SOLO_PUSH


def _referencia(tipo, datos, clave):
    """(modulo, referencia_tipo, referencia_id) del evento."""
    modulo, referencia_tipo, campo = CATALOGO[tipo]
    if tipo == "revision_pendiente":
        modulo_revision = str(datos.get("modulo") or "")
        if modulo_revision == "pedidos_empleados":
            referencia_tipo = "adelanto" if str(clave or "").startswith("revision:adelanto:") else "pedido_mercaderia"
        else:
            referencia_tipo = _REVISION.get(modulo_revision)
    try:
        referencia_id = int(datos[campo]) if datos.get(campo) not in (None, "") else None
    except (TypeError, ValueError):
        referencia_id = None
    return modulo, (referencia_tipo if referencia_id else None), referencia_id


def guardar(c, empresa_id, empleado_ids, tipo, titulo, mensaje, datos=None, clave=None):
    """Crea la notificacion de cada empleado (una sola vez por clave) en la transaccion del llamador.
    Devuelve ({empleado_id: notificacion_id}, nuevas)."""
    ids = sorted({int(i) for i in empleado_ids or [] if i})
    if not ids:
        return {}, 0
    datos = dict(datos or {})
    clave = str(clave)[:150] if clave else f"{tipo}:{uuid.uuid4().hex}"  # sin clave no hay deduplicacion posible
    modulo, referencia_tipo, referencia_id = _referencia(tipo, datos, clave)
    ruta = str(datos.get("ruta") or "")[:200] or None
    # La imagen del push es un link firmado que vence: la app usa la del comunicado.
    extra = {k: str(v) for k, v in datos.items() if v is not None and k not in ("ruta", "imagen")}
    texto = json.dumps(extra, ensure_ascii=False) if extra else None
    ahora = now_local().replace(microsecond=0)
    nuevas = 0
    for i in range(0, len(ids), 500):
        lote = ids[i:i + 500]
        c.executemany(
            """INSERT IGNORE INTO empleado_notificaciones
                 (empresa_id, empleado_id, tipo, modulo, titulo, mensaje, referencia_tipo, referencia_id, ruta, datos,
                  clave, creado_at)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
            [(empresa_id, eid, tipo, modulo, str(titulo)[:120], str(mensaje)[:500], referencia_tipo, referencia_id,
              ruta, texto, clave, ahora) for eid in lote])
        nuevas += max(c.rowcount, 0)
    por_empleado = {}
    for i in range(0, len(ids), 500):
        lote = ids[i:i + 500]
        marcas = ",".join(["%s"] * len(lote))
        for fila in db.all_rows(c, f"""SELECT id, empleado_id FROM empleado_notificaciones
                                       WHERE clave = %s AND empleado_id IN ({marcas})""", (clave, *lote)):
            por_empleado[int(fila["empleado_id"])] = int(fila["id"])
    return por_empleado, nuevas


# --- Sincronizacion con comunicados (endpoints viejos y borrado desde el panel) ------------------------

def marcar_referencia_leida(c, empleado_id, referencia_tipo, referencia_ids, cuando):
    ids = sorted({int(i) for i in referencia_ids or []})
    if not ids:
        return 0
    marcas = ",".join(["%s"] * len(ids))
    c.execute(f"""UPDATE empleado_notificaciones SET leido_at = %s
                  WHERE empleado_id = %s AND referencia_tipo = %s AND referencia_id IN ({marcas}) AND leido_at IS NULL""",
              (cuando, int(empleado_id), referencia_tipo, *ids))
    return c.rowcount


def marcar_tipo_leido(c, empleado, referencia_tipo, cuando):
    c.execute("""UPDATE empleado_notificaciones SET leido_at = %s
                 WHERE empleado_id = %s AND empresa_id = %s AND referencia_tipo = %s AND leido_at IS NULL""",
              (cuando, empleado["id"], empleado["empresa_id"], referencia_tipo))
    return c.rowcount


def eliminar_referencia(c, empresa_id, referencia_tipo, referencia_id):
    c.execute("DELETE FROM empleado_notificaciones WHERE empresa_id = %s AND referencia_tipo = %s AND referencia_id = %s",
              (empresa_id, referencia_tipo, int(referencia_id)))


# --- API de la app (empresa y empleado salen del token) --------------------------------------------------

def _iso(valor):
    if valor is None:
        return None
    if isinstance(valor, dt.datetime):
        return valor.replace(microsecond=0).isoformat(timespec="seconds")
    return str(valor).replace(" ", "T")[:19]


def _item(fila):
    try:
        parametros = json.loads(fila["datos"] or "{}")
    except ValueError:
        parametros = {}
    referencia = None
    if fila["referencia_tipo"]:
        referencia = dict(tipo=fila["referencia_tipo"], id=int(fila["referencia_id"]))
    return dict(id=int(fila["id"]), tipo=fila["tipo"], modulo=fila["modulo"], titulo=fila["titulo"],
                mensaje=fila["mensaje"], creado_at=_iso(fila["creado_at"]), leida=fila["leido_at"] is not None,
                leido_at=_iso(fila["leido_at"]), referencia=referencia,
                destino=dict(ruta=fila["ruta"] or "/notificaciones", parametros=parametros))


def _base(empleado):
    return "empleado_id = %s AND empresa_id = %s", [int(empleado["id"]), int(empleado["empresa_id"])]


def _no_leidas(c, empleado):
    donde, args = _base(empleado)
    return int(db.one(c, f"SELECT COUNT(*) AS n FROM empleado_notificaciones WHERE {donde} AND leido_at IS NULL",
                      tuple(args))["n"])


def _entero(valor, nombre, minimo=1):
    if valor in (None, ""):
        return None
    try:
        numero = int(valor)
    except (TypeError, ValueError):
        raise Error(f"{nombre} inválido.") from None
    if numero < minimo:
        raise Error(f"{nombre} inválido.")
    return numero


def _modulo(valor):
    valor = str(valor or "").strip()
    if not valor:
        return None
    if valor not in {m for m, _, _ in CATALOGO.values()}:
        raise Error("Módulo inválido.")
    return valor


def listado(empleado, estado=None, modulo=None, antes_de=None, limite=None):
    """De la mas reciente a la mas antigua (por id). Paginado por cursor: antes_de = siguiente de la pagina anterior.
    corte = la notificacion mas nueva del empleado al consultar: es el hasta_id para "leer todas"."""
    estado = str(estado or "todas").strip().lower()
    if estado not in ("todas", "no_leidas", "leidas"):
        raise Error("Estado inválido (todas, no_leidas o leidas).")
    modulo = _modulo(modulo)
    antes_de = _entero(antes_de, "Cursor")
    limite = min(_entero(limite, "Límite") or POR_PAGINA, POR_PAGINA_MAX)
    donde, args = _base(empleado)
    if estado == "no_leidas":
        donde += " AND leido_at IS NULL"
    elif estado == "leidas":
        donde += " AND leido_at IS NOT NULL"
    if modulo:
        donde += " AND modulo = %s"
        args.append(modulo)
    if antes_de:
        donde += " AND id < %s"
        args.append(antes_de)
    with db.transaction(read_only=True) as c:
        filas = db.all_rows(c, f"""SELECT {_COLUMNAS} FROM empleado_notificaciones WHERE {donde}
                                   ORDER BY id DESC LIMIT %s""", (*args, limite + 1))
        no_leidas = _no_leidas(c, empleado)
        base, base_args = _base(empleado)
        corte = db.one(c, f"SELECT MAX(id) AS id FROM empleado_notificaciones WHERE {base}", tuple(base_args))["id"]
    hay_mas = len(filas) > limite
    filas = filas[:limite]
    return dict(items=[_item(f) for f in filas], no_leidas=no_leidas, corte=int(corte) if corte else None,
                siguiente=int(filas[-1]["id"]) if hay_mas else None, limite=limite)


def resumen(empleado):
    donde, args = _base(empleado)
    with db.transaction(read_only=True) as c:
        por_modulo = db.all_rows(c, f"""SELECT modulo, COUNT(*) AS n FROM empleado_notificaciones
                                        WHERE {donde} AND leido_at IS NULL GROUP BY modulo""", tuple(args))
        ultima = db.one(c, f"SELECT MAX(id) AS id FROM empleado_notificaciones WHERE {donde}", tuple(args))["id"]
    modulos = {f["modulo"]: int(f["n"]) for f in por_modulo}
    return dict(no_leidas=sum(modulos.values()), por_modulo=modulos, ultima_id=int(ultima) if ultima else None)


def _propia(c, empleado, notificacion_id):
    donde, args = _base(empleado)
    fila = db.one(c, f"SELECT {_COLUMNAS} FROM empleado_notificaciones WHERE id = %s AND {donde}",
                  (int(notificacion_id), *args))
    if not fila:
        raise Error("Notificación no encontrada.", 404)  # tambien si es de otro empleado o empresa
    return fila


def _disponible(c, empleado, fila):
    """True si el registro relacionado existe y este empleado puede verlo; False si no; None si no aplica."""
    if not fila["referencia_tipo"] or fila["referencia_tipo"] not in _REFERENCIAS:
        return None
    sql, usa_empresa, columnas = _REFERENCIAS[fila["referencia_tipo"]]
    args = (int(fila["referencia_id"]), int(empleado["empresa_id"])) if usa_empresa else (int(fila["referencia_id"]),)
    try:
        filas = db.all_rows(c, sql, args)
    except Exception:  # tabla de un modulo no instalado: el mensaje se muestra igual
        logger.warning("notificacion_referencia_error", exc_info=True,
                       extra={"extra": {"referencia_tipo": fila["referencia_tipo"]}})
        return None
    if not filas:
        return False
    # Solicitudes para revisar: el destinatario es quien aprueba; la pantalla de revision valida su permiso.
    if not columnas or fila["tipo"] == "revision_pendiente":
        return True
    return any(int(f[col] or 0) == int(empleado["id"]) for f in filas for col in columnas)


def detalle(empleado, notificacion_id):
    """No la marca como leida. referencia.disponible = false si el tramite ya no existe o no es accesible."""
    with db.transaction(read_only=True) as c:
        fila = _propia(c, empleado, notificacion_id)
        disponible = _disponible(c, empleado, fila)
        no_leidas = _no_leidas(c, empleado)
    item = _item(fila)
    if item["referencia"]:
        item["referencia"]["disponible"] = disponible
    return dict(item, no_leidas=no_leidas)


def leer(empleado, notificacion_id):
    """Idempotente: la primera lectura guarda la fecha; las siguientes devuelven la misma."""
    with db.transaction() as c:
        fila = _propia(c, empleado, notificacion_id)
        if fila["leido_at"] is None:
            cuando = now_local().replace(microsecond=0)
            c.execute("UPDATE empleado_notificaciones SET leido_at = %s WHERE id = %s AND leido_at IS NULL",
                      (cuando, fila["id"]))
            if c.rowcount:
                fila = dict(fila, leido_at=cuando)
                if fila["referencia_tipo"] == "comunicado":
                    c.execute("""UPDATE comunicado_destinatarios SET leido_at = %s
                                 WHERE comunicado_id = %s AND empleado_id = %s AND leido_at IS NULL""",
                              (cuando, fila["referencia_id"], empleado["id"]))
            else:  # otro dispositivo la leyo en el medio
                fila = _propia(c, empleado, notificacion_id)
        no_leidas = _no_leidas(c, empleado)
    item = _item(fila)
    return dict(item, no_leidas=no_leidas)


def leer_todas(empleado, hasta_id, modulo=None):
    """Marca leidas solo las notificaciones con id <= hasta_id (el corte que la app recibio): lo que llego despues
    sigue sin leer. Idempotente."""
    hasta_id = _entero(hasta_id, "hasta_id")
    if not hasta_id:
        raise Error("Falta hasta_id (el corte del listado).")
    modulo = _modulo(modulo)
    donde, args = _base(empleado)
    donde += " AND leido_at IS NULL AND id <= %s"
    args.append(hasta_id)
    if modulo:
        donde += " AND modulo = %s"
        args.append(modulo)
    cuando = now_local().replace(microsecond=0)
    with db.transaction() as c:
        comunicados = [int(f["referencia_id"]) for f in db.all_rows(
            c, f"""SELECT referencia_id FROM empleado_notificaciones
                   WHERE {donde} AND referencia_tipo = 'comunicado'""", tuple(args))]
        c.execute(f"UPDATE empleado_notificaciones SET leido_at = %s WHERE {donde}", (cuando, *args))
        marcadas = max(c.rowcount, 0)
        for i in range(0, len(comunicados), 500):
            lote = comunicados[i:i + 500]
            marcas = ",".join(["%s"] * len(lote))
            c.execute(f"""UPDATE comunicado_destinatarios SET leido_at = %s
                          WHERE empleado_id = %s AND leido_at IS NULL AND comunicado_id IN ({marcas})""",
                      (cuando, empleado["id"], *lote))
        no_leidas = _no_leidas(c, empleado)
    return dict(marcadas=marcadas, no_leidas=no_leidas, hasta_id=hasta_id)
