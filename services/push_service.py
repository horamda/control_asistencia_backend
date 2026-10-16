"""Notificaciones push con Firebase Cloud Messaging (API HTTP v1), para Android y la app web.

Configuracion (variables de entorno, sin ellas todo queda desactivado y no se encola nada):
  FIREBASE_SERVICE_ACCOUNT      JSON de la cuenta de servicio (o FIREBASE_SERVICE_ACCOUNT_B64 en base64)
  FIREBASE_WEB_CONFIG           JSON de configuracion web de Firebase (apiKey, projectId, ...), publico
  FIREBASE_WEB_VAPID_KEY        clave publica VAPID para web push, publica
  FRONTEND_WEB_URL              URL de la app web, para abrir la pantalla al tocar la notificacion

Flujo: el panel encola (push_envios) y el scheduler envia cada minuto, asi las pantallas no esperan a
Firebase. Los tokens que Firebase da por invalidos se desactivan solos."""

import base64
import datetime as dt
import hashlib
import json
import logging
import os
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

import jwt

from repositories import carga_repository as db
from services.carga_service import CargaError as Error, now_local

logger = logging.getLogger(__name__)

SCOPE = "https://www.googleapis.com/auth/firebase.messaging"
PLATAFORMAS = ("android", "web")
MAX_INTENTOS = 3
CANAL_ANDROID = "reuniones"
_token_cache = {"valor": None, "vence": 0.0}
_lock = threading.Lock()


# --- Configuracion -----------------------------------------------------------------------------

def credenciales():
    raw = os.getenv("FIREBASE_SERVICE_ACCOUNT", "").strip()
    if not raw and os.getenv("FIREBASE_SERVICE_ACCOUNT_B64", "").strip():
        try:
            raw = base64.b64decode(os.environ["FIREBASE_SERVICE_ACCOUNT_B64"]).decode("utf-8")
        except ValueError:
            logger.error("push_config_b64_invalida")
            return None
    if not raw:
        return None
    try:
        data = json.loads(raw)
    except ValueError:
        logger.error("push_config_json_invalido")
        return None
    if not all(data.get(k) for k in ("project_id", "client_email", "private_key")):
        logger.error("push_config_incompleta")
        return None
    return data


def activo():
    return credenciales() is not None


def config_web():
    """Datos publicos para que la app web se registre (no incluye secretos)."""
    try:
        web = json.loads(os.getenv("FIREBASE_WEB_CONFIG", "") or "null")
    except ValueError:
        web = None
    return dict(activo=activo(), web=web if isinstance(web, dict) else None,
                vapid_key=os.getenv("FIREBASE_WEB_VAPID_KEY") or None, canal_android=CANAL_ANDROID)


# --- Dispositivos ------------------------------------------------------------------------------

def _hash(token):
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def registrar_dispositivo(empleado, token, plataforma, app_version=None):
    """Alta o actualizacion del token del dispositivo. Si el token estaba a nombre de otro empleado
    (telefono compartido o cambio de sesion), pasa al empleado actual."""
    token = str(token or "").strip()
    if not 20 <= len(token) <= 1024:
        raise Error("Token de notificaciones inválido.")
    plataforma = str(plataforma or "").strip().lower()
    if plataforma not in PLATAFORMAS:
        raise Error("Plataforma inválida (android o web).")
    ahora = now_local()
    with db.transaction() as c:
        c.execute(
            """INSERT INTO push_dispositivos (empresa_id, empleado_id, token, token_hash, plataforma, app_version,
                                              activo, creado_at, ultimo_uso_at)
               VALUES (%s,%s,%s,%s,%s,%s,1,%s,%s)
               ON DUPLICATE KEY UPDATE empresa_id=VALUES(empresa_id), empleado_id=VALUES(empleado_id),
                 plataforma=VALUES(plataforma), app_version=VALUES(app_version), activo=1, error=NULL,
                 ultimo_uso_at=VALUES(ultimo_uso_at)""",
            (empleado["empresa_id"], empleado["id"], token, _hash(token), plataforma,
             (str(app_version)[:40] if app_version else None), ahora, ahora))
    return dict(registrado=True, activo=activo())


def quitar_dispositivo(empleado, token):
    """Al cerrar sesion: el dispositivo deja de recibir avisos de este empleado."""
    with db.transaction() as c:
        c.execute("UPDATE push_dispositivos SET activo=0 WHERE token_hash=%s AND empleado_id=%s",
                  (_hash(str(token or "").strip()), empleado["id"]))
        return c.rowcount > 0


# --- Cola ----------------------------------------------------------------------------------------

def encolar(c, empresa_id, empleado_ids, tipo, titulo, cuerpo, datos=None, clave=None):
    """Agrega avisos a la cola dentro de la transaccion del llamador. clave evita duplicados
    (se le suma el empleado). Sin Firebase configurado no hace nada. Devuelve cuantos encolo."""
    ids = sorted({int(i) for i in empleado_ids or [] if i})
    if not ids or not activo():
        return 0
    ahora = now_local()
    texto = json.dumps({k: str(v) for k, v in (datos or {}).items() if v is not None}, ensure_ascii=False)
    nuevos = 0
    for eid in ids:
        c.execute("""INSERT IGNORE INTO push_envios (empresa_id, empleado_id, tipo, clave, titulo, cuerpo, datos,
                                                    estado, creado_at)
                     VALUES (%s,%s,%s,%s,%s,%s,%s,'pendiente',%s)""",
                  (empresa_id, eid, tipo, f"{clave}:{eid}"[:150] if clave else None, titulo[:120], cuerpo[:500],
                   texto, ahora))
        nuevos += c.rowcount
    return nuevos


def encolar_ahora(empresa_id, empleado_ids, tipo, titulo, cuerpo, datos=None, clave=None):
    """Igual que encolar, en su propia transaccion. Un error de push nunca rompe la accion del panel."""
    if not activo():
        return 0
    try:
        with db.transaction() as c:
            return encolar(c, empresa_id, empleado_ids, tipo, titulo, cuerpo, datos, clave)
    except Exception:
        logger.warning("push_encolar_error", exc_info=True, extra={"extra": {"tipo": tipo}})
        return 0


# --- Envio (FCM HTTP v1) ---------------------------------------------------------------------------

def _post(url, data, headers, timeout=10):
    request = urllib.request.Request(url, data=data, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310 (URLs de Google fijas)
            return response.status, json.loads(response.read().decode("utf-8") or "{}")
    except urllib.error.HTTPError as exc:
        try:
            cuerpo = json.loads(exc.read().decode("utf-8") or "{}")
        except ValueError:
            cuerpo = {}
        return exc.code, cuerpo


def _access_token(cred):
    """Token OAuth de la cuenta de servicio (JWT RS256 firmado), cacheado hasta 5 min antes de vencer."""
    with _lock:
        if _token_cache["valor"] and _token_cache["vence"] > time.time() + 300:
            return _token_cache["valor"]
        ahora = int(time.time())
        token_uri = cred.get("token_uri") or "https://oauth2.googleapis.com/token"
        assertion = jwt.encode({"iss": cred["client_email"], "scope": SCOPE, "aud": token_uri, "iat": ahora,
                                "exp": ahora + 3600}, cred["private_key"], algorithm="RS256")
        status, data = _post(token_uri, urllib.parse.urlencode(
            {"grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer", "assertion": assertion}).encode(),
            {"Content-Type": "application/x-www-form-urlencoded"})
        if status != 200 or not data.get("access_token"):
            raise RuntimeError(f"No se pudo autenticar con Firebase ({status}): {data.get('error_description') or data.get('error')}")
        _token_cache.update(valor=data["access_token"], vence=time.time() + int(data.get("expires_in", 3600)))
        return _token_cache["valor"]


def _mensaje(token, titulo, cuerpo, datos):
    mensaje = {
        "token": token,
        "notification": {"title": titulo, "body": cuerpo},
        "data": datos,
        "android": {"priority": "HIGH", "notification": {"channel_id": CANAL_ANDROID}},
    }
    imagen = datos.get("imagen") or ""
    if imagen.startswith("https://"):
        # Android: miniatura a la derecha y la imagen grande al expandir. Web: imagen grande.
        mensaje["notification"]["image"] = imagen
    base = (os.getenv("FRONTEND_WEB_URL") or "").rstrip("/")
    if base.startswith("https://"):
        mensaje["webpush"] = {"fcm_options": {"link": base + datos.get("ruta", "/")}}
    return {"message": mensaje}


def enviar_a_token(cred, token, titulo, cuerpo, datos):
    """Devuelve (ok, error, invalido). invalido=True si Firebase indica que el token ya no sirve."""
    status, data = _post(
        f"https://fcm.googleapis.com/v1/projects/{cred['project_id']}/messages:send",
        json.dumps(_mensaje(token, titulo, cuerpo, datos)).encode("utf-8"),
        {"Authorization": f"Bearer {_access_token(cred)}", "Content-Type": "application/json; charset=utf-8"})
    if status == 200:
        return True, None, False
    error = data.get("error") or {}
    codigos = {d.get("errorCode") for d in error.get("details") or [] if isinstance(d, dict)}
    invalido = status == 404 or "UNREGISTERED" in codigos or (status == 400 and "INVALID_ARGUMENT" in codigos)
    return False, f"{status} {error.get('status') or ''} {error.get('message') or ''}".strip()[:255], invalido


def procesar_cola(limite=200, *, enviar=None):
    """Envia los avisos pendientes. Llamado por el scheduler cada minuto."""
    enviar = enviar or enviar_a_token  # se resuelve al llamar (no al definir la funcion)
    cred = credenciales()
    if not cred:
        return dict(enviados=0, errores=0, sin_dispositivo=0)
    resumen = dict(enviados=0, errores=0, sin_dispositivo=0)
    with db.transaction() as c:
        # Un envio que quedo 'enviando' (proceso cortado a mitad) vuelve a la cola.
        c.execute("UPDATE push_envios SET estado='reintentar' WHERE estado='enviando' AND creado_at < %s",
                  (now_local() - dt.timedelta(minutes=10),))
        pendientes = db.all_rows(c, """SELECT * FROM push_envios WHERE estado IN ('pendiente','reintentar') AND intentos < %s
                                       ORDER BY id LIMIT %s""", (MAX_INTENTOS, int(limite)))
    for envio in pendientes:
        # Reserva atomica: si otro proceso (scheduler / boton de prueba) ya lo tomo, se saltea.
        with db.transaction() as c:
            c.execute("UPDATE push_envios SET estado='enviando' WHERE id=%s AND estado IN ('pendiente','reintentar')",
                      (envio["id"],))
            if not c.rowcount:
                continue
        with db.transaction(read_only=True) as c:
            dispositivos = db.all_rows(c, "SELECT id, token FROM push_dispositivos WHERE empleado_id=%s AND activo=1",
                                       (envio["empleado_id"],))
        if not dispositivos:
            estado, error, ok = "sin_dispositivo", None, 0
            resumen["sin_dispositivo"] += 1
        else:
            try:
                datos = json.loads(envio["datos"] or "{}")
            except ValueError:
                datos = {}
            datos = {str(k): str(v) for k, v in dict(datos, tipo=envio["tipo"]).items()}
            ok, errores = 0, []
            for d in dispositivos:
                try:
                    exito, error, invalido = enviar(cred, d["token"], envio["titulo"], envio["cuerpo"], datos)
                except Exception as exc:  # red, autenticacion
                    exito, error, invalido = False, str(exc)[:255], False
                if exito:
                    ok += 1
                else:
                    errores.append(error)
                    if invalido:
                        with db.transaction() as c:
                            c.execute("UPDATE push_dispositivos SET activo=0, error=%s WHERE id=%s", (error, d["id"]))
            if ok:
                estado, error = "enviado", None
                resumen["enviados"] += 1
            else:
                estado = "reintentar" if envio["intentos"] + 1 < MAX_INTENTOS else "error"
                error = (errores[0] if errores else None)
                resumen["errores"] += 1
        with db.transaction() as c:
            c.execute("""UPDATE push_envios SET estado=%s, error=%s, intentos=intentos+1, dispositivos=%s,
                         enviado_at=%s WHERE id=%s""",
                      (estado, error, ok, now_local() if estado == "enviado" else None, envio["id"]))
    if any(resumen.values()):
        logger.info("push_cola", extra={"extra": resumen})
    return resumen


# --- Panel ------------------------------------------------------------------------------------------

def estado_panel(who):
    cred = credenciales()
    with db.transaction(read_only=True) as c:
        dispositivos = db.all_rows(c, """SELECT plataforma, COUNT(*) AS n, COUNT(DISTINCT empleado_id) AS empleados
                                         FROM push_dispositivos WHERE empresa_id=%s AND activo=1 GROUP BY plataforma""",
                                   (who["empresa_id"],))
        envios = db.all_rows(c, """SELECT p.*, e.apellido, e.nombre FROM push_envios p
                                   LEFT JOIN empleados e ON e.id = p.empleado_id
                                   WHERE p.empresa_id=%s ORDER BY p.id DESC LIMIT 30""", (who["empresa_id"],))
        resumen = {row["estado"]: int(row["n"]) for row in db.all_rows(
            c, """SELECT estado, COUNT(*) AS n FROM push_envios WHERE empresa_id=%s AND creado_at >= %s GROUP BY estado""",
            (who["empresa_id"], now_local() - dt.timedelta(days=7)))}
        con_dispositivo = db.all_rows(c, """SELECT DISTINCT e.id, e.apellido, e.nombre, e.legajo FROM empleados e
                                            JOIN push_dispositivos d ON d.empleado_id = e.id AND d.activo = 1
                                            WHERE e.empresa_id=%s ORDER BY e.apellido, e.nombre""", (who["empresa_id"],))
    web = config_web()
    return dict(activo=cred is not None, project_id=cred.get("project_id") if cred else None,
                web_configurada=bool(web["web"] and web["vapid_key"]), frontend_url=os.getenv("FRONTEND_WEB_URL") or None,
                dispositivos=dispositivos, envios=envios, resumen=resumen, con_dispositivo=con_dispositivo)


def enviar_prueba(who, empleado_id):
    if not activo():
        raise Error("Firebase no está configurado.")
    with db.transaction() as c:
        empleado = db.one(c, "SELECT id FROM empleados WHERE id=%s AND empresa_id=%s", (int(empleado_id), who["empresa_id"]))
        if not empleado:
            raise Error("Empleado inválido.")
        encolar(c, who["empresa_id"], [empleado["id"]], "prueba", "Notificación de prueba",
                "Si ves este mensaje, las notificaciones de FichaYa funcionan en este dispositivo.", {"ruta": "/"})
    return procesar_cola(limite=50)
