"""Notificaciones push (Firebase Cloud Messaging) y avisos de reuniones."""
import base64
import datetime as dt
import json

import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from services import push_service as push
from services import reunion_avisos as avisos
from services import reunion_service as svc
from tests.test_reuniones import ADMIN, AHORA, crear, emp, reuniones_db  # noqa: F401  (fixtures)
from tests.test_seguridad import database  # noqa: F401

D = dt.date


@pytest.fixture
def clave_rsa():
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pem = key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                            serialization.NoEncryption()).decode()
    return key, pem


@pytest.fixture
def firebase(monkeypatch, clave_rsa):
    cuenta = {"project_id": "fichaya-test", "client_email": "push@fichaya-test.iam.gserviceaccount.com",
              "private_key": clave_rsa[1], "token_uri": "https://oauth2.googleapis.com/token"}
    monkeypatch.setenv("FIREBASE_SERVICE_ACCOUNT", json.dumps(cuenta))
    push._token_cache.update(valor=None, vence=0)
    return cuenta


# --- Configuracion y API de Google (sin red) ---------------------------------------------------------

def test_credenciales_y_config(monkeypatch, firebase):
    assert push.activo() and push.credenciales()["project_id"] == "fichaya-test"
    monkeypatch.delenv("FIREBASE_SERVICE_ACCOUNT")
    monkeypatch.setenv("FIREBASE_SERVICE_ACCOUNT_B64", base64.b64encode(json.dumps(firebase).encode()).decode())
    assert push.activo()
    monkeypatch.setenv("FIREBASE_SERVICE_ACCOUNT_B64", base64.b64encode(b'{"project_id": "x"}').decode())
    assert not push.activo()  # incompleta
    monkeypatch.delenv("FIREBASE_SERVICE_ACCOUNT_B64")
    assert not push.activo()
    monkeypatch.setenv("FIREBASE_WEB_CONFIG", '{"apiKey": "pub", "projectId": "fichaya-test"}')
    monkeypatch.setenv("FIREBASE_WEB_VAPID_KEY", "BAbc")
    assert push.config_web() == {"activo": False, "web": {"apiKey": "pub", "projectId": "fichaya-test"},
                                 "vapid_key": "BAbc", "canal_android": "reuniones"}


def test_token_oauth_y_envio(monkeypatch, firebase, clave_rsa):
    llamadas = []

    def fake_post(url, data, headers, timeout=10):
        llamadas.append((url, data, headers))
        if "oauth2" in url:
            assertion = dict(x.split("=", 1) for x in data.decode().split("&"))["assertion"]
            claims = jwt.decode(assertion, clave_rsa[0].public_key(), algorithms=["RS256"], audience=firebase["token_uri"])
            assert claims["iss"] == firebase["client_email"] and claims["scope"] == push.SCOPE
            return 200, {"access_token": "ya29.token", "expires_in": 3600}
        if b'"token": "vencido' in data:
            return 404, {"error": {"status": "NOT_FOUND", "message": "Requested entity was not found.",
                                   "details": [{"errorCode": "UNREGISTERED"}]}}
        return 200, {"name": "projects/fichaya-test/messages/1"}

    monkeypatch.setattr(push, "_post", fake_post)
    monkeypatch.setenv("FRONTEND_WEB_URL", "https://app.fichaya.test/")
    ok = push.enviar_a_token(firebase, "token-valido-0123456789", "Hola", "Cuerpo", {"ruta": "/reuniones/3"})
    assert ok == (True, None, False)
    mensaje = json.loads(llamadas[-1][1])["message"]
    assert llamadas[-1][0].endswith("/projects/fichaya-test/messages:send")
    assert llamadas[-1][2]["Authorization"] == "Bearer ya29.token"
    assert mensaje["android"]["notification"]["channel_id"] == "reuniones"
    assert mensaje["webpush"]["fcm_options"]["link"] == "https://app.fichaya.test/reuniones/3"
    exito, error, invalido = push.enviar_a_token(firebase, "vencido-0123456789012", "Hola", "Cuerpo", {})
    assert not exito and invalido and error.startswith("404 NOT_FOUND")
    assert sum(1 for url, *_ in llamadas if "oauth2" in url) == 1  # token OAuth cacheado


# --- Dispositivos, cola y avisos (base real) -------------------------------------------------------------

@pytest.fixture
def push_db(reuniones_db, firebase):  # noqa: F811
    conn = reuniones_db()
    c = conn.cursor()
    from scripts.migrate_20261016_05_push import migrate_cursor
    migrate_cursor(c)
    migrate_cursor(c)  # idempotente
    conn.commit()
    c.close()
    conn.close()
    return reuniones_db


def _envios(estado=None):
    with svc.db.transaction(read_only=True) as c:
        sql = "SELECT * FROM push_envios" + (" WHERE estado=%s" if estado else "") + " ORDER BY id"
        return svc.db.all_rows(c, sql, (estado,) if estado else ())


def test_dispositivos_y_cola(push_db):
    t1, t2 = "a" * 40, "b" * 40
    push.registrar_dispositivo(emp(10), t1, "android", "1.21.0")
    push.registrar_dispositivo(emp(11), t2, "web")
    push.registrar_dispositivo(emp(11), t1, "android")  # el mismo telefono pasa al empleado 11
    with pytest.raises(svc.Error, match="Plataforma"):
        push.registrar_dispositivo(emp(10), "c" * 40, "ios")
    with svc.db.transaction(read_only=True) as c:
        assert svc.db.one(c, "SELECT COUNT(*) AS n FROM push_dispositivos WHERE empleado_id=11 AND activo=1")["n"] == 2

    with svc.db.transaction() as c:
        assert push.encolar(c, 1, [11, 12], "prueba", "Hola", "Cuerpo", {"ruta": "/"}, clave="x") == 2
        assert push.encolar(c, 1, [11], "prueba", "Hola", "Cuerpo", clave="x") == 0  # misma clave: no duplica
    enviados = []

    def fake_enviar(cred, token, titulo, cuerpo, datos):
        enviados.append((token, datos["tipo"]))
        if token == t2:
            return False, "404 NOT_FOUND", True  # token web vencido
        return True, None, False

    resumen = push.procesar_cola(enviar=fake_enviar)
    assert resumen == {"enviados": 1, "errores": 0, "sin_dispositivo": 1}
    assert sorted(enviados) == sorted([(t1, "prueba"), (t2, "prueba")])
    with svc.db.transaction(read_only=True) as c:
        assert svc.db.one(c, "SELECT activo FROM push_dispositivos WHERE token_hash=%s", (push._hash(t2),))["activo"] == 0
    assert push.procesar_cola(enviar=fake_enviar)["enviados"] == 0  # nada pendiente

    # Reintentos: tres fallos y queda en error.
    with svc.db.transaction() as c:
        push.encolar(c, 1, [11], "prueba", "Hola", "Cuerpo", clave="y")
    for _ in range(3):
        push.procesar_cola(enviar=lambda *a: (False, "503 UNAVAILABLE", False))
    assert [e["estado"] for e in _envios() if e["clave"] == "y:11"] == ["error"]
    assert push.quitar_dispositivo(emp(11), t1)


def test_avisos_de_reuniones(push_db):
    AHORA["valor"] = dt.datetime(2026, 10, 13, 8, 0)
    rid = crear(nombre="Seguridad", reglas=["todos"], empleados=[])
    assert avisos.reunion_guardada(ADMIN, rid, nueva=True) == 5  # toda la empresa 1
    aviso = _envios()[0]
    assert aviso["titulo"] == "Nueva reunión" and aviso["cuerpo"].startswith("Seguridad: Todos los miércoles a las 09:00")
    assert json.loads(aviso["datos"]) == {"reunion_id": str(rid), "ruta": f"/reuniones/{rid}"}

    # Editar sin cambiar horario/dias/lugar no avisa; cambiar el horario si.
    antes = avisos.firma(ADMIN, rid)
    datos = dict(nombre="Seguridad (nuevo nombre)", lugar="Sala 1", frecuencia="semanal", dias_semana=["2"],
                 hora_inicio="09:00", duracion_min="60", qr_modo="ambos", reglas=["todos"], empleados=[])
    svc.guardar(ADMIN, datos, rid)
    assert avisos.reunion_guardada(ADMIN, rid, nueva=False, antes=antes) == 0
    antes = avisos.firma(ADMIN, rid)
    svc.guardar(ADMIN, dict(datos, hora_inicio="10:00"), rid)
    assert avisos.reunion_guardada(ADMIN, rid, nueva=False, antes=antes) == 5

    # Cancelacion y cambio de horario de una fecha.
    svc.cancelar_ocurrencia(ADMIN, rid, D(2026, 10, 21), "Feriado")
    assert avisos.fecha_cancelada(ADMIN, rid, D(2026, 10, 21), None, "Feriado") == 5
    assert "Se canceló Seguridad (nuevo nombre) del miércoles 21/10: Feriado" in [e["cuerpo"] for e in _envios()]
    svc.reprogramar_ocurrencia(ADMIN, rid, D(2026, 10, 14), "11:00")
    assert avisos.fecha_reprogramada(ADMIN, rid, D(2026, 10, 14), None) == 5
    assert any(e["cuerpo"].endswith("del miércoles 14/10 pasa a las 11:00.") for e in _envios())

    # Recordatorio 30 min antes, solo a quien no registro, una vez.
    with svc.db.transaction(read_only=True) as c:
        qr = svc.qr_fijo(svc.sede(c, svc.obtener(c, ADMIN, rid), 0))
    assert avisos.recordatorios(dt.datetime(2026, 10, 14, 10, 0)) == 0  # faltan 60 min
    AHORA["valor"] = dt.datetime(2026, 10, 14, 10, 46)  # el registro abre 10:45 (horario cambiado a 11:00)
    svc.registrar_qr(emp(10), qr)
    assert avisos.recordatorios(dt.datetime(2026, 10, 14, 10, 46)) == 4  # sin el 10, que ya registro
    assert avisos.recordatorios(dt.datetime(2026, 10, 14, 10, 50)) == 0  # no repite
    recordatorio = [e for e in _envios() if e["tipo"] == "recordatorio"][0]
    assert recordatorio["titulo"] == "Seguridad (nuevo nombre) a las 11:00"
    assert recordatorio["cuerpo"] == "Empieza en 14 min en Sala 1. Escaneá el QR al llegar."


def test_sin_firebase_no_encola(push_db, monkeypatch):
    monkeypatch.delenv("FIREBASE_SERVICE_ACCOUNT")
    rid = crear(reglas=["todos"], empleados=[])
    assert avisos.reunion_guardada(ADMIN, rid, nueva=True) == 0
    assert push.procesar_cola() == {"enviados": 0, "errores": 0, "sin_dispositivo": 0}
    assert _envios() == []


def test_endpoints_app_y_panel(push_db, monkeypatch):
    from pathlib import Path
    from flask import Flask
    import routes.carga_routes as carga_routes
    import utils.jwt_guard as jwt_guard
    import web.auth.decorators as auth
    from web.push import routes as rutas

    app = Flask(__name__, template_folder=str(Path(__file__).resolve().parents[1] / "templates"))
    app.secret_key = "test"
    app.register_blueprint(rutas.web)
    app.register_blueprint(rutas.mobile)
    app.jinja_env.globals.update(csp_nonce=lambda: "n", csrf_token=lambda: "t", can_web=lambda *a: False,
                                 export_toolbar={"enabled": False, "items": []})
    monkeypatch.setattr(jwt_guard, "verificar_token", lambda token: dict(empleado_id=int(token)))
    monkeypatch.setattr(carga_routes, "get_by_id", emp)
    monkeypatch.setattr(auth, "can_access_module", lambda *a, **kw: True)
    monkeypatch.setattr(rutas, "_cached_web_user", lambda uid: dict(id=99, empresa_id=1, activo=1))
    monkeypatch.setattr(rutas, "log_audit", lambda *a, **kw: None)
    monkeypatch.setattr(push, "enviar_a_token", lambda *a: (True, None, False))
    client = app.test_client()
    headers = {"Authorization": "Bearer 10"}

    assert client.get("/api/v1/mobile/push/config", headers=headers).json["activo"] is True
    r = client.post("/api/v1/mobile/push/dispositivo", json={"token": "t" * 40, "plataforma": "web"}, headers=headers)
    assert r.status_code == 200 and r.json == {"registrado": True, "activo": True}
    assert client.post("/api/v1/mobile/push/dispositivo", json={"token": "x"}, headers=headers).status_code == 400
    assert client.post("/api/v1/mobile/push/dispositivo", json={"token": "t" * 40}).status_code == 401

    with client.session_transaction() as sess:
        sess["user_id"] = 99
    html = client.get("/notificaciones-push/").get_data(as_text=True)
    assert "Conectado" in html and "fichaya-test" in html and "Enviar prueba" in html
    monkeypatch.setattr(push, "enviar_a_token", lambda *a: (True, None, False))
    r = client.post("/notificaciones-push/prueba", data={"empleado_id": "10"})
    assert r.status_code == 302 and _envios()[-1]["estado"] == "enviado"
    assert client.delete("/api/v1/mobile/push/dispositivo", json={"token": "t" * 40}, headers=headers).json == {"quitado": True}
