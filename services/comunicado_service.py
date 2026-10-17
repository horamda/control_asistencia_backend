"""Comunicados del panel a los empleados: aviso push y bandeja en la app, con quien lo leyo.

Destinatarios con las mismas reglas que los convocados de Reuniones: toda la empresa, sector, sector:puesto,
puesto en cualquier sector (cuenta el puesto principal y los adicionales) y personas puntuales; opcionalmente
solo de algunas sucursales. Se resuelven al enviar: quien ingresa despues no lo recibe.

Una imagen opcional se guarda en dos versiones JPEG: una para la app, ajustada al celular sin recortar
(IMAGEN_APP_MAX), y otra 2:1 para la notificacion (IMAGEN_PUSH_TAMANO): Android la muestra apaisada y
recortaria una imagen cuadrada o vertical, asi que va entera sobre un fondo desenfocado de ella misma.
Firebase la descarga sin login, asi que el push lleva un link firmado que vence a los IMAGEN_PUSH_DIAS."""

import datetime as dt
import hashlib
import hmac
import io
import time
import warnings

from flask import current_app, url_for
from PIL import Image, ImageEnhance, ImageFilter, ImageOps, UnidentifiedImageError

from repositories import carga_repository as db
from services import push_service
from services.carga_service import MAX_PHOTO_BYTES, CargaError as Error, now_local
from services.reunion_service import _marcas, _participantes

TITULO_MAX = 120
MENSAJE_MAX = 2000
POR_PAGINA = 20
IMAGEN_PUSH_DIAS = 7
IMAGEN_APP_MAX = (1080, 1920)  # ancho de un celular Full HD; afiches verticales hasta 16:9
IMAGEN_PUSH_TAMANO = (1024, 512)  # proporcion de la notificacion expandida de Android
_COLUMNAS = "c.id, c.empresa_id, c.titulo, c.mensaje, c.alcance, c.destinatarios, c.creado_por, c.creado_at"


def _texto(data, campo, maximo, nombre):
    valor = str(data.get(campo) or "").strip()
    if not valor:
        raise Error(f"Escribí {nombre}.")
    if len(valor) > maximo:
        raise Error(f"{nombre.capitalize()}: máximo {maximo} caracteres.")
    return valor


def _sucursales(c, empresa_id, pedidas):
    ids = {int(x) for x in pedidas or [] if str(x).isdigit()}
    if not ids:
        return {}
    filas = db.all_rows(c, f"SELECT id, nombre FROM sucursales WHERE empresa_id=%s AND id IN ({_marcas(ids)})",
                        (empresa_id, *ids))
    if len(filas) != len(ids):
        raise Error("Sucursal inválida.")
    return {f["id"]: f["nombre"] for f in filas}


def destinatarios(c, empresa_id, reglas, sucursales=()):
    """IDs de empleados activos alcanzados por las reglas (tuplas de _participantes) y las sucursales."""
    empleados = db.all_rows(c, "SELECT id, sucursal_id, sector_id, puesto_id FROM empleados WHERE empresa_id=%s AND activo=1",
                            (empresa_id,))
    combos = {e["id"]: {(e["sector_id"], e["puesto_id"])} for e in empleados}
    for extra in db.all_rows(c, """SELECT ep.empleado_id, ep.sector_id, ep.puesto_id FROM empleado_puestos ep
                                   JOIN empleados e ON e.id = ep.empleado_id
                                   WHERE e.empresa_id=%s AND e.activo=1 AND ep.activo=1""", (empresa_id,)):
        combos.setdefault(extra["empleado_id"], set()).add((extra["sector_id"], extra["puesto_id"]))
    personas = {r[0] for r in reglas if r[0]}
    grupos = [(s, p) for e, s, p in reglas if not e]

    def alcanzado(eid):
        return eid in personas or any((s is None or s == cs) and (p is None or p == cp)
                                      for s, p in grupos for cs, cp in combos.get(eid, ()))

    return sorted(e["id"] for e in empleados if (not sucursales or e["sucursal_id"] in sucursales) and alcanzado(e["id"]))


def _alcance(c, empresa_id, reglas, sucursales):
    """Texto legible de a quien se envio (queda guardado tal cual)."""
    partes = []
    if (None, None, None) in reglas:
        partes.append("Toda la empresa")
    else:
        sectores = {f["id"]: f["nombre"] for f in db.all_rows(c, "SELECT id, nombre FROM sectores WHERE empresa_id=%s",
                                                               (empresa_id,))}
        puestos = {f["id"]: f["nombre"] for f in db.all_rows(c, "SELECT id, nombre FROM puestos WHERE empresa_id=%s",
                                                              (empresa_id,))}
        grupos = []
        for e, s, p in sorted(reglas, key=str):
            if e:
                continue
            if s and p:
                grupos.append(f"{sectores.get(s, s)} · {puestos.get(p, p)}")
            elif s:
                grupos.append(f"Sector {sectores.get(s, s)}")
            else:
                grupos.append(f"{puestos.get(p, p)} (cualquier sector)")
        partes.extend(grupos)
        personas = sum(1 for e, _, _ in reglas if e)
        if personas:
            partes.append("1 persona" if personas == 1 else f"{personas} personas")
    texto = "; ".join(partes)
    if sucursales:
        texto += " · " + ("Sucursal " if len(sucursales) == 1 else "Sucursales ") + ", ".join(sorted(sucursales.values()))
    return texto[:500]


def _reglas(c, empresa_id, data):
    if not data.get("reglas") and not data.get("empleados"):
        raise Error("Elegí a quién enviarlo: toda la empresa, sectores, puestos o personas.")
    return _participantes(c, empresa_id, data)


def vista_previa(who, data):
    """Cuantos empleados recibirian el comunicado (sin enviarlo)."""
    with db.transaction(read_only=True) as c:
        reglas = _reglas(c, who["empresa_id"], data)
        return len(destinatarios(c, who["empresa_id"], reglas, _sucursales(c, who["empresa_id"], data.get("sucursales"))))


def _jpeg(imagen, calidad):
    buffer = io.BytesIO()
    imagen.save(buffer, format="JPEG", quality=calidad, optimize=True, progressive=True)
    return buffer.getvalue()


def _version_app(imagen):
    """Para la pantalla del celular: entra en IMAGEN_APP_MAX sin recortar ni agrandar."""
    copia = imagen.copy()
    copia.thumbnail(IMAGEN_APP_MAX, Image.Resampling.LANCZOS)
    return _jpeg(copia, 82)


def _version_push(imagen):
    """2:1 para la notificacion: la imagen entera, centrada sobre una version desenfocada de si misma."""
    fondo = ImageOps.fit(imagen, IMAGEN_PUSH_TAMANO, Image.Resampling.LANCZOS)
    fondo = ImageEnhance.Brightness(fondo.filter(ImageFilter.GaussianBlur(24))).enhance(0.85)
    frente = imagen.copy()
    frente.thumbnail(IMAGEN_PUSH_TAMANO, Image.Resampling.LANCZOS)
    fondo.paste(frente, ((fondo.width - frente.width) // 2, (fondo.height - frente.height) // 2))
    return _jpeg(fondo, 80)


def _imagen_subida(archivo):
    """(version app, version push) de la imagen elegida en el panel, o (None, None) si no se adjunto.

    Mismas reglas que las fotos de carga (formato, 5 MB, 20 megapixeles, rotacion segun el EXIF), pero
    redimensiona una sola vez desde el original para no perder calidad."""
    if archivo is None or not getattr(archivo, "filename", ""):
        return None, None
    crudo = archivo.read(MAX_PHOTO_BYTES + 1)
    if not crudo or len(crudo) > MAX_PHOTO_BYTES:
        raise Error("La imagen debe tener contenido y pesar hasta 5 MB.")
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(crudo)) as origen:
                if origen.format not in {"JPEG", "PNG", "WEBP"} or origen.width * origen.height > 20_000_000:
                    raise Error("Use una imagen JPG, PNG o WEBP de hasta 20 megapíxeles.")
                origen.load()
                imagen = ImageOps.exif_transpose(origen).convert("RGB")
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError, Image.DecompressionBombWarning):
        raise Error("El archivo no es una imagen válida.") from None
    return _version_app(imagen), _version_push(imagen)


def firma_imagen(cid, vence):
    clave = str(current_app.secret_key or "").encode()
    return hmac.new(clave, f"comunicado-imagen:{int(cid)}:{int(vence)}".encode(), hashlib.sha256).hexdigest()[:32]


def url_imagen_push(cid, ahora=None, base_url=None):
    """Link publico y firmado a la imagen, para que Firebase la muestre en la notificacion. Fuera de un request
    (comunicados programados, que envia el scheduler) se arma con la base guardada al programarlo."""
    vence = int(ahora if ahora is not None else time.time()) + IMAGEN_PUSH_DIAS * 86400
    firma = firma_imagen(cid, vence)
    if base_url:
        url = f"{base_url.rstrip('/')}/comunicados/imagen-push/{int(cid)}/{vence}/{firma}.jpg"
    else:
        try:
            url = url_for("comunicados.imagen_push", comunicado_id=int(cid), vence=vence, firma=firma, _external=True)
        except RuntimeError:  # fuera de un request no hay URL publica conocida
            return None
    # Firebase solo descarga imagenes por HTTPS.
    return url if url.startswith("https://") else None


def enviar(who, data, imagen=None):
    contenido, contenido_push = _imagen_subida(imagen)
    return enviar_contenido(who, data, contenido, contenido_push)


def enviar_contenido(who, data, contenido=None, contenido_push=None, *, programado_id=None, base_url=None):
    """Envia el comunicado con la imagen ya procesada (la usan el panel y los comunicados programados)."""
    titulo = _texto(data, "titulo", TITULO_MAX, "el título")
    mensaje = _texto(data, "mensaje", MENSAJE_MAX, "el mensaje")
    with db.transaction() as c:
        reglas = _reglas(c, who["empresa_id"], data)
        sucursales = _sucursales(c, who["empresa_id"], data.get("sucursales"))
        ids = destinatarios(c, who["empresa_id"], reglas, sucursales)
        if not ids:
            raise Error("Con esa selección no hay empleados activos para recibir el comunicado.")
        cid = db.insert(c, "comunicados", dict(empresa_id=who["empresa_id"], titulo=titulo, mensaje=mensaje,
                                                imagen=contenido, imagen_push=contenido_push,
                                                alcance=_alcance(c, who["empresa_id"], reglas, sucursales),
                                                destinatarios=len(ids), creado_por=who.get("user_id"),
                                                programado_id=programado_id, creado_at=now_local()))
        for i in range(0, len(ids), 500):
            lote = ids[i:i + 500]
            c.executemany("INSERT INTO comunicado_destinatarios (comunicado_id, empleado_id) VALUES (%s, %s)",
                          [(cid, eid) for eid in lote])
    cuerpo = mensaje if len(mensaje) <= 180 else mensaje[:177].rstrip() + "…"
    datos = {"comunicado_id": cid, "ruta": f"/comunicados/{cid}"}
    if contenido:
        datos["imagen"] = url_imagen_push(cid, base_url=base_url)
    push_service.encolar_ahora(who["empresa_id"], ids, "comunicado", titulo, cuerpo, datos, f"comunicado:{cid}")
    return cid, len(ids)


# --- Panel ------------------------------------------------------------------------------------------

def listado(who, page=1):
    page = max(1, int(page or 1))
    with db.transaction(read_only=True) as c:
        total = int(db.one(c, "SELECT COUNT(*) AS n FROM comunicados WHERE empresa_id=%s", (who["empresa_id"],))["n"])
        items = db.all_rows(c, """SELECT c.id, c.titulo, c.mensaje, c.alcance, c.destinatarios, c.creado_at,
                                         MAX(c.imagen IS NOT NULL) AS tiene_imagen, MAX(c.programado_id) AS programado_id,
                                         COALESCE(SUM(d.leido_at IS NOT NULL), 0) AS leidos
                                  FROM comunicados c
                                  LEFT JOIN comunicado_destinatarios d ON d.comunicado_id = c.id
                                  WHERE c.empresa_id=%s
                                  GROUP BY c.id, c.titulo, c.mensaje, c.alcance, c.destinatarios, c.creado_at
                                  ORDER BY c.id DESC LIMIT %s OFFSET %s""",
                            (who["empresa_id"], POR_PAGINA, (page - 1) * POR_PAGINA))
    for item in items:
        item["leidos"] = int(item["leidos"])
        item["leidos_pct"] = round(100 * item["leidos"] / item["destinatarios"]) if item["destinatarios"] else 0
    return dict(items=items, page=page, pages=max(1, -(-total // POR_PAGINA)), total=total)


def _obtener(c, who, cid):
    fila = db.one(c, f"""SELECT {_COLUMNAS}, (c.imagen IS NOT NULL) AS tiene_imagen FROM comunicados c
                          WHERE c.id=%s AND c.empresa_id=%s""", (int(cid), who["empresa_id"]))
    if not fila:
        raise Error("Comunicado no encontrado.", 404)
    return fila


def detalle(who, cid, estado=None):
    with db.transaction(read_only=True) as c:
        comunicado = _obtener(c, who, cid)
        # El push de cada destinatario tiene clave "comunicado:<id>:<empleado>" (unica, indexada).
        sql = """SELECT e.id, e.apellido, e.nombre, e.legajo, s.nombre AS sector_nombre, su.nombre AS sucursal_nombre,
                        d.leido_at, p.estado AS push_estado, p.recibido_at, p.abierto_at
                 FROM comunicado_destinatarios d JOIN empleados e ON e.id = d.empleado_id
                 LEFT JOIN sectores s ON s.id = e.sector_id LEFT JOIN sucursales su ON su.id = e.sucursal_id
                 LEFT JOIN push_envios p ON p.clave = CONCAT('comunicado:', d.comunicado_id, ':', d.empleado_id)
                 WHERE d.comunicado_id=%s"""
        if estado == "leidos":
            sql += " AND d.leido_at IS NOT NULL"
        elif estado == "pendientes":
            sql += " AND d.leido_at IS NULL"
        personas = db.all_rows(c, sql + " ORDER BY d.leido_at IS NULL, e.apellido, e.nombre", (comunicado["id"],))
        leidos = int(db.one(c, """SELECT COUNT(*) AS n FROM comunicado_destinatarios
                                  WHERE comunicado_id=%s AND leido_at IS NOT NULL""", (comunicado["id"],))["n"])
        recibidos = int(db.one(c, """SELECT COUNT(*) AS n FROM push_envios
                                     WHERE clave LIKE %s AND recibido_at IS NOT NULL""",
                               (f"comunicado:{comunicado['id']}:%",))["n"])
    for persona in personas:
        persona["push_estado"] = _estado_envio(persona["push_estado"]) if persona["push_estado"] else None
    return dict(comunicado=comunicado, personas=personas, leidos=leidos, recibidos=recibidos, estado=estado or "")


def imagen(who, cid, version="app"):
    """Imagen para el panel (misma empresa); version "push" es la 2:1 de la notificacion."""
    columna = "COALESCE(imagen_push, imagen)" if version == "push" else "imagen"
    with db.transaction(read_only=True) as c:
        fila = db.one(c, f"SELECT {columna} AS contenido FROM comunicados WHERE id=%s AND empresa_id=%s",
                      (int(cid), who["empresa_id"]))
    if not fila or not fila["contenido"]:
        raise Error("Imagen no encontrada.", 404)
    return fila


def imagen_push(cid, vence, firma, ahora=None):
    """Imagen por link firmado (sin login) mientras no venza."""
    ahora = int(ahora if ahora is not None else time.time())
    if int(vence) < ahora or not hmac.compare_digest(str(firma), firma_imagen(cid, vence)):
        raise Error("Imagen no encontrada.", 404)
    with db.transaction(read_only=True) as c:
        fila = db.one(c, "SELECT COALESCE(imagen_push, imagen) AS contenido FROM comunicados WHERE id=%s", (int(cid),))
    if not fila or not fila["contenido"]:
        raise Error("Imagen no encontrada.", 404)
    return fila


def eliminar(who, cid):
    """Lo quita de la bandeja de la app (el aviso push ya enviado no se puede retirar)."""
    with db.transaction() as c:
        comunicado = _obtener(c, who, cid)
        c.execute("DELETE FROM comunicado_destinatarios WHERE comunicado_id=%s", (comunicado["id"],))
        c.execute("DELETE FROM comunicados WHERE id=%s", (comunicado["id"],))
        c.execute("DELETE FROM push_envios WHERE clave LIKE %s AND estado IN ('pendiente','reintentar')",
                  (f"comunicado:{comunicado['id']}:%",))
    return comunicado


# --- Historial de avisos automaticos ------------------------------------------------------------------

# Avisos que el sistema manda solo (los comunicados y las pruebas del panel quedan afuera).
TIPOS_AUTOMATICOS = {
    "salida_pendiente": "Salida sin fichar",
    "recordatorio": "Recordatorio de reunión",
    "reunion_nueva": "Reunión nueva",
    "reunion_cambio": "Reunión modificada",
    "reunion_cancelada": "Reunión cancelada",
    "reunion_reactivada": "Reunión reactivada",
    "reunion_horario": "Cambio de horario de reunión",
    "epp_resuelto": "EPP resuelto",
    "epp_entregado": "EPP entregado",
    "reintegro": "Viáticos",
    "reintegro_recordatorio": "Recordatorio de viáticos",
    "adelanto": "Adelanto",
    "pedido_mercaderia": "Pedido de mercadería",
    "justificacion": "Justificación",
    "vacaciones": "Vacaciones",
    "feedback_asignado": "Feedback asignado",
    "feedback_resuelto": "Feedback resuelto",
    "trivia_nueva": "Trivia nueva",
    "trivia_recordatorio": "Recordatorio de trivia",
    "revision_pendiente": "Para revisar (RR. HH., jefes, seguridad)",
    "seguridad_resultado": "Resultado de reporte de seguridad",
    "seguridad_accion": "Acción de seguridad",
}
ESTADOS_ENVIO = {"enviado": "Enviado", "sin_dispositivo": "Sin dispositivo", "error": "Error", "pendiente": "En cola"}
# Confirmados por la app (ver push_service.registrar_acuse); un enviado sin acuse puede no haber llegado.
ACUSES = {"recibido": "Recibido", "abierto": "Abierto"}
_EN_COLA = ("pendiente", "reintentar", "enviando")
HISTORIAL_POR_PAGINA = 50
HISTORIAL_DIAS = 30


def _fecha_filtro(valor):
    try:
        return dt.date.fromisoformat(str(valor or "").strip()[:10])
    except ValueError:
        return None


def _estado_envio(estado):
    return "pendiente" if estado in _EN_COLA else estado


def automaticos(who, filtros):
    """Historial de avisos automaticos de la empresa con filtros y resumen por estado."""
    hoy = now_local().date()
    hasta = _fecha_filtro(filtros.get("hasta")) or hoy
    desde = _fecha_filtro(filtros.get("desde")) or hasta - dt.timedelta(days=HISTORIAL_DIAS - 1)
    if desde > hasta:
        desde, hasta = hasta, desde
    tipo = filtros.get("tipo") if filtros.get("tipo") in TIPOS_AUTOMATICOS else ""
    estado = filtros.get("estado") if filtros.get("estado") in {**ESTADOS_ENVIO, **ACUSES} else ""
    buscar = str(filtros.get("q") or "").strip()[:80]
    try:
        page = max(1, int(filtros.get("page") or 1))
    except (TypeError, ValueError):
        page = 1

    tipos = (tipo,) if tipo else tuple(TIPOS_AUTOMATICOS)
    where = ["p.empresa_id=%s", "p.creado_at >= %s", "p.creado_at < %s", f"p.tipo IN ({_marcas(tipos)})"]
    args = [who["empresa_id"], desde, hasta + dt.timedelta(days=1), *tipos]
    if buscar:
        like = f"%{buscar}%"
        where.append("(e.apellido LIKE %s OR e.nombre LIKE %s OR e.legajo LIKE %s"
                     " OR CONCAT_WS(' ', e.apellido, e.nombre) LIKE %s)")
        args += [like] * 4
    base = "FROM push_envios p LEFT JOIN empleados e ON e.id = p.empleado_id WHERE " + " AND ".join(where)

    with db.transaction(read_only=True) as c:
        resumen = dict.fromkeys({**ESTADOS_ENVIO, **ACUSES}, 0)
        for fila in db.all_rows(c, f"""SELECT p.estado, COUNT(*) AS n, COALESCE(SUM(p.recibido_at IS NOT NULL), 0) AS recibidos,
                                              COALESCE(SUM(p.abierto_at IS NOT NULL), 0) AS abiertos
                                       {base} GROUP BY p.estado""", tuple(args)):
            clave = _estado_envio(fila["estado"])
            resumen[clave] = resumen.get(clave, 0) + int(fila["n"])
            resumen["recibido"] = resumen.get("recibido", 0) + int(fila["recibidos"])
            resumen["abierto"] = resumen.get("abierto", 0) + int(fila["abiertos"])
        if estado == "recibido":
            base += " AND p.recibido_at IS NOT NULL"
        elif estado == "abierto":
            base += " AND p.abierto_at IS NOT NULL"
        elif estado == "pendiente":
            base += f" AND p.estado IN ({_marcas(_EN_COLA)})"
            args += list(_EN_COLA)
        elif estado:
            base += " AND p.estado=%s"
            args.append(estado)
        total = int(db.one(c, f"SELECT COUNT(*) AS n {base}", tuple(args))["n"])
        items = db.all_rows(c, f"""SELECT p.id, p.tipo, p.titulo, p.cuerpo, p.estado, p.error, p.creado_at, p.enviado_at,
                                          p.recibido_at, p.abierto_at, p.empleado_id, e.apellido, e.nombre, e.legajo
                                   {base} ORDER BY p.id DESC LIMIT %s OFFSET %s""",
                            (*args, HISTORIAL_POR_PAGINA, (page - 1) * HISTORIAL_POR_PAGINA))
    for item in items:
        item["tipo_nombre"] = TIPOS_AUTOMATICOS.get(item["tipo"], item["tipo"])
        item["estado"] = _estado_envio(item["estado"])
    return dict(items=items, page=page, pages=max(1, -(-total // HISTORIAL_POR_PAGINA)), total=total,
                resumen=resumen, tipos=TIPOS_AUTOMATICOS, estados=ESTADOS_ENVIO, acuses=ACUSES,
                filtros=dict(tipo=tipo, estado=estado, q=buscar, desde=desde.isoformat(), hasta=hasta.isoformat()))


# --- App del empleado ---------------------------------------------------------------------------------

def _item(fila):
    imagen_url = f"/api/v1/mobile/comunicados/{fila['id']}/imagen" if fila.get("tiene_imagen") else None
    return dict(id=fila["id"], titulo=fila["titulo"], mensaje=fila["mensaje"], imagen_url=imagen_url,
                fecha=fila["creado_at"].isoformat(timespec="seconds"), leido=fila["leido_at"] is not None,
                leido_at=fila["leido_at"].isoformat(timespec="seconds") if fila["leido_at"] else None)


def mis_comunicados(empleado, page=1):
    page = max(1, int(page or 1))
    with db.transaction(read_only=True) as c:
        filas = db.all_rows(c, """SELECT c.id, c.titulo, c.mensaje, c.creado_at, d.leido_at,
                                         (c.imagen IS NOT NULL) AS tiene_imagen
                                  FROM comunicado_destinatarios d JOIN comunicados c ON c.id = d.comunicado_id
                                  WHERE d.empleado_id=%s AND c.empresa_id=%s
                                  ORDER BY c.id DESC LIMIT %s OFFSET %s""",
                            (empleado["id"], empleado["empresa_id"], POR_PAGINA, (page - 1) * POR_PAGINA))
        cuenta = db.one(c, """SELECT COUNT(*) AS total, COALESCE(SUM(d.leido_at IS NULL), 0) AS no_leidos
                              FROM comunicado_destinatarios d JOIN comunicados c ON c.id = d.comunicado_id
                              WHERE d.empleado_id=%s AND c.empresa_id=%s""", (empleado["id"], empleado["empresa_id"]))
    total = int(cuenta["total"])
    return dict(items=[_item(f) for f in filas], no_leidos=int(cuenta["no_leidos"]), total=total, page=page,
                pages=max(1, -(-total // POR_PAGINA)))


def leer(empleado, cid):
    """Devuelve el comunicado y lo marca como leido (la primera vez queda la fecha)."""
    with db.transaction() as c:
        fila = db.one(c, """SELECT c.id, c.titulo, c.mensaje, c.creado_at, d.leido_at,
                                   (c.imagen IS NOT NULL) AS tiene_imagen
                            FROM comunicado_destinatarios d JOIN comunicados c ON c.id = d.comunicado_id
                            WHERE d.comunicado_id=%s AND d.empleado_id=%s AND c.empresa_id=%s""",
                      (int(cid), empleado["id"], empleado["empresa_id"]))
        if not fila:
            raise Error("Comunicado no encontrado.", 404)
        if fila["leido_at"] is None:
            fila["leido_at"] = now_local().replace(microsecond=0)
            c.execute("UPDATE comunicado_destinatarios SET leido_at=%s WHERE comunicado_id=%s AND empleado_id=%s",
                      (fila["leido_at"], fila["id"], empleado["id"]))
    return _item(fila)


def imagen_empleado(empleado, cid):
    """Imagen para la app: solo si el comunicado es para este empleado."""
    with db.transaction(read_only=True) as c:
        fila = db.one(c, """SELECT c.imagen AS contenido
                            FROM comunicado_destinatarios d JOIN comunicados c ON c.id = d.comunicado_id
                            WHERE d.comunicado_id=%s AND d.empleado_id=%s AND c.empresa_id=%s""",
                      (int(cid), empleado["id"], empleado["empresa_id"]))
    if not fila or not fila["contenido"]:
        raise Error("Imagen no encontrada.", 404)
    return fila


def leer_todos(empleado):
    with db.transaction() as c:
        c.execute("""UPDATE comunicado_destinatarios d JOIN comunicados c ON c.id = d.comunicado_id
                     SET d.leido_at=%s WHERE d.empleado_id=%s AND c.empresa_id=%s AND d.leido_at IS NULL""",
                  (now_local().replace(microsecond=0), empleado["id"], empleado["empresa_id"]))
        return c.rowcount
