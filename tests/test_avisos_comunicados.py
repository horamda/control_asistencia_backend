"""Avisos push fuera de Reuniones (salida pendiente, resoluciones) y modulo Comunicados."""
import datetime as dt
import json
from pathlib import Path

import pytest
from flask import Flask

from services import avisos_push as avisos
from services import comunicado_service as com
from services import egreso_automatico_service as egreso
from services import push_service as push
from services import reunion_service as svc
from tests.test_push import _envios, clave_rsa, firebase, push_db  # noqa: F401  (fixtures)
from tests.test_reuniones import ADMIN, emp, reuniones_db  # noqa: F401
from tests.test_seguridad import database  # noqa: F401

HOY = dt.date(2026, 10, 14)
TABLAS = [
    """CREATE TABLE asistencias (id INT AUTO_INCREMENT PRIMARY KEY, empresa_id INT, empleado_id INT, fecha DATE,
       hora_entrada TIME NULL, hora_salida TIME NULL)""",
    """CREATE TABLE configuracion_empresa (empresa_id INT PRIMARY KEY, egreso_automatico_activo TINYINT,
       egreso_automatico_horas DECIMAL(4,2))""",
    """CREATE TABLE epp_pedidos (id INT AUTO_INCREMENT PRIMARY KEY, empresa_id INT, empleado_id INT, estado VARCHAR(30),
       revision INT DEFAULT 1)""",
    """CREATE TABLE epp_lineas (id INT AUTO_INCREMENT PRIMARY KEY, pedido_id INT, cantidad INT, aprobada INT NULL,
       motivo VARCHAR(1000) NOT NULL DEFAULT '')""",
    """CREATE TABLE reintegro_solicitudes (id INT AUTO_INCREMENT PRIMARY KEY, empresa_id INT, empleado_id INT,
       estado VARCHAR(20), revision INT DEFAULT 1, total_aprobado DECIMAL(14,2) DEFAULT 0, motivo TEXT NULL)""",
    """CREATE TABLE reintegro_recordatorios (id INT AUTO_INCREMENT PRIMARY KEY, empresa_id INT, empleado_id INT,
       periodo DATE, mensaje VARCHAR(500), creado_at DATETIME, leido_at DATETIME NULL)""",
    """CREATE TABLE adelantos (id INT AUTO_INCREMENT PRIMARY KEY, empresa_id INT, empleado_id INT, estado VARCHAR(20),
       periodo_month TINYINT)""",
    """CREATE TABLE pedidos_mercaderia (id INT AUTO_INCREMENT PRIMARY KEY, empresa_id INT, empleado_id INT,
       estado VARCHAR(20), periodo_month TINYINT, motivo_rechazo VARCHAR(255) NULL)""",
]


@pytest.fixture
def base(push_db, monkeypatch):  # noqa: F811
    conn = push_db()
    c = conn.cursor()
    for sql in TABLAS:
        c.execute(sql)
    from scripts.migrate_20261016_06_comunicados import migrate_cursor
    migrate_cursor(c)
    migrate_cursor(c)  # idempotente
    from scripts.migrate_20261016_08_comunicados_imagen import migrate_cursor as migrate_imagen
    migrate_imagen(c)
    migrate_imagen(c)  # idempotente
    from scripts.migrate_20261016_10_comunicados_imagen_push import migrate_cursor as migrate_imagen_push
    migrate_imagen_push(c)
    migrate_imagen_push(c)  # idempotente
    conn.commit()
    c.close()
    conn.close()
    avisos._previstas.update(fecha=None, fin={})
    monkeypatch.setattr(com, "now_local", lambda: dt.datetime(2026, 10, 14, 9, 30, 15))
    for eid in (10, 11, 12, 13):
        push.registrar_dispositivo(emp(eid), f"token-{eid}".ljust(30, "x"), "android")
    return push_db


def _sql(sql, args=()):
    with svc.db.transaction() as c:
        c.execute(sql, args)
        return c.lastrowid


def _avisos(tipo):
    return [e for e in _envios() if e["tipo"] == tipo]


# --- Salida pendiente ---------------------------------------------------------------------------

def test_salida_pendiente_una_vez_despues_del_margen(base, monkeypatch):
    bloques = {10: [{"entrada": "08:00", "salida": "17:00"}]}  # 11 sin horario: ingreso + horas de la empresa
    monkeypatch.setattr(egreso, "_bloques", lambda eid, fecha: bloques.get(eid, []))
    _sql("INSERT INTO configuracion_empresa VALUES (1, 1, 6)")
    a10 = _sql("INSERT INTO asistencias (empresa_id, empleado_id, fecha, hora_entrada) VALUES (1, 10, %s, '08:02:00')", (HOY,))
    _sql("INSERT INTO asistencias (empresa_id, empleado_id, fecha, hora_entrada) VALUES (1, 11, %s, '09:00:00')", (HOY,))
    _sql("INSERT INTO asistencias (empresa_id, empleado_id, fecha, hora_entrada, hora_salida)"
         " VALUES (1, 12, %s, '08:00:00', '16:00:00')", (HOY,))  # ya ficho la salida
    _sql("INSERT INTO asistencias (empresa_id, empleado_id, fecha, hora_entrada) VALUES (1, 13, %s, '08:00:00')",
         (HOY - dt.timedelta(days=1),))  # de ayer: la cierra el egreso automatico

    assert avisos.salidas_pendientes(dt.datetime(2026, 10, 14, 15, 29)) == 0  # 11: 15:00 + 30 min todavia no
    assert avisos.salidas_pendientes(dt.datetime(2026, 10, 14, 15, 30)) == 1
    assert avisos.salidas_pendientes(dt.datetime(2026, 10, 14, 17, 29)) == 0
    assert avisos.salidas_pendientes(dt.datetime(2026, 10, 14, 17, 31)) == 1  # 10: 17:00 + 30 min
    assert avisos.salidas_pendientes(dt.datetime(2026, 10, 14, 20, 0)) == 0  # no repite
    enviados = {e["empleado_id"]: e for e in _avisos("salida_pendiente")}
    assert sorted(enviados) == [10, 11]
    assert enviados[10]["titulo"] == "¿Te olvidaste de fichar la salida?"
    assert enviados[10]["cuerpo"] == ("Entraste a las 08:02 y tu salida prevista era a las 17:00. Registrala en la app."
                                      " Si no, esta noche se cierra sola a las 17:00 y cuenta como olvido de fichada.")
    assert enviados[11]["cuerpo"].startswith("Entraste a las 09:00 y tu salida prevista era a las 15:00.")
    assert json.loads(enviados[10]["datos"]) == {"asistencia_id": str(a10), "fecha": "2026-10-14", "ruta": "/asistencia"}


def test_salida_pendiente_sin_egreso_automatico_ni_dispositivo(base, monkeypatch):
    monkeypatch.setattr(egreso, "_bloques", lambda eid, fecha: [])
    _sql("INSERT INTO configuracion_empresa VALUES (1, 0, 8)")
    _sql("INSERT INTO asistencias (empresa_id, empleado_id, fecha, hora_entrada) VALUES (1, 10, %s, '08:00:00')", (HOY,))
    _sql("INSERT INTO asistencias (empresa_id, empleado_id, fecha, hora_entrada) VALUES (1, 14, %s, '08:00:00')", (HOY,))
    assert avisos.salidas_pendientes(dt.datetime(2026, 10, 14, 16, 45)) == 1  # 14 no tiene la app
    aviso = _avisos("salida_pendiente")[0]
    assert aviso["empleado_id"] == 10 and "se cierra sola" not in aviso["cuerpo"]


# --- Resoluciones -------------------------------------------------------------------------------

def test_avisos_de_resoluciones(base):
    pid = _sql("INSERT INTO epp_pedidos (empresa_id, empleado_id, estado, revision) VALUES (1, 10, 'aprobado', 2)")
    _sql("INSERT INTO epp_lineas (pedido_id, cantidad, aprobada, motivo) VALUES (%s, 3, 1, 'Stock limitado'),"
         " (%s, 1, 1, 'Stock limitado')", (pid, pid))
    assert avisos.epp_resuelto(pid) == 1
    assert avisos.epp_resuelto(pid) == 0  # misma revision: no duplica
    _sql("UPDATE epp_pedidos SET estado='parcial', revision=3 WHERE id=%s", (pid,))
    assert avisos.epp_entregado(pid, 77) == 1
    rid = _sql("INSERT INTO reintegro_solicitudes (empresa_id, empleado_id, estado, revision, total_aprobado)"
               " VALUES (1, 11, 'aprobada', 2, 15300.5)")
    assert avisos.reintegro_actualizado(rid) == 1
    _sql("UPDATE reintegro_solicitudes SET estado='devuelta', revision=3, motivo='Falta el ticket' WHERE id=%s", (rid,))
    assert avisos.reintegro_actualizado(rid) == 1
    _sql("UPDATE reintegro_solicitudes SET estado='cancelada', revision=4 WHERE id=%s", (rid,))
    assert avisos.reintegro_actualizado(rid) == 0  # cancelar no avisa
    aid = _sql("INSERT INTO adelantos (empresa_id, empleado_id, estado, periodo_month) VALUES (1, 12, 'aprobado', 10)")
    assert avisos.adelanto_resuelto(aid) == 1
    mid = _sql("INSERT INTO pedidos_mercaderia (empresa_id, empleado_id, estado, periodo_month, motivo_rechazo)"
               " VALUES (1, 13, 'rechazado', 10, 'Sin stock')")
    assert avisos.pedido_mercaderia_resuelto(mid) == 1

    textos = [(e["tipo"], e["titulo"], e["cuerpo"]) for e in _envios()]
    assert textos == [
        ("epp_resuelto", "Pedido de EPP aprobado con cambios",
         f"De tu pedido N° {pid} se aprobaron 2 de 4 unidades. Motivo: Stock limitado"),
        ("epp_entregado", "Entrega parcial de EPP",
         f"Se registró una entrega parcial de tu pedido N° {pid}. El resto queda pendiente."),
        ("reintegro", "Viáticos aprobados", f"Tu rendición N° {rid} fue aprobada por $ 15.300,50."),
        ("reintegro", "Viáticos para corregir", f"Te devolvieron la rendición N° {rid} para corregir. Motivo: Falta el ticket"),
        ("adelanto", "Adelanto aprobado", "Tu pedido de adelanto de octubre fue aprobado."),
        ("pedido_mercaderia", "Pedido de mercadería rechazado", "Tu pedido de mercadería de octubre fue rechazado. Motivo: Sin stock"),
    ]
    assert json.loads(_envios()[0]["datos"]) == {"pedido_id": str(pid), "estado": "aprobado", "ruta": f"/epp/{pid}"}


def test_recordatorio_de_viaticos_y_sin_firebase(base, monkeypatch):
    periodo = dt.date(2026, 9, 1)
    for eid, leido in ((10, None), (11, "2026-10-05 10:00:00")):
        _sql("INSERT INTO reintegro_recordatorios (empresa_id, empleado_id, periodo, mensaje, creado_at, leido_at)"
             " VALUES (1, %s, %s, 'Recordá completar tus viáticos', '2026-10-05 08:00:00', %s)", (eid, periodo, leido))
    assert avisos.recordatorio_viaticos(periodo, "Recordá completar tus viáticos") == 1
    assert avisos.recordatorio_viaticos(periodo, "Recordá completar tus viáticos") == 0
    monkeypatch.delenv("FIREBASE_SERVICE_ACCOUNT")
    assert avisos.epp_resuelto(1) == 0 and avisos.salidas_pendientes() == 0


def test_un_error_del_aviso_no_rompe_la_accion(base, monkeypatch):
    monkeypatch.setattr(avisos.db, "transaction", lambda **kw: (_ for _ in ()).throw(RuntimeError("caida")))
    assert avisos.adelanto_resuelto(1) == 0


# --- Comunicados ----------------------------------------------------------------------------------

def test_comunicados_destinatarios_bandeja_y_lectura(base):
    with pytest.raises(com.Error, match="Elegí a quién"):
        com.enviar(ADMIN, dict(titulo="Hola", mensaje="Texto"))
    with pytest.raises(com.Error, match="título"):
        com.enviar(ADMIN, dict(titulo=" ", mensaje="Texto", reglas=["todos"]))
    assert com.vista_previa(ADMIN, dict(reglas=["todos"])) == 5  # empresa 1, activos
    assert com.vista_previa(ADMIN, dict(reglas=["todos"], sucursales=["2"])) == 1
    assert com.vista_previa(ADMIN, dict(reglas=["2"])) == 2  # sector Almacen: 13 y 14
    with pytest.raises(com.Error, match="Sucursal"):
        com.vista_previa(ADMIN, dict(reglas=["todos"], sucursales=["3"]))  # de otra empresa

    cid, total = com.enviar(ADMIN, dict(titulo="Corte de luz", mensaje="El jueves no hay luz.\nTraigan linterna.",
                                        reglas=["2:2"], empleados=["10"]))
    assert total == 3
    with svc.db.transaction(read_only=True) as c:
        guardado = svc.db.one(c, "SELECT * FROM comunicados WHERE id=%s", (cid,))
    assert guardado["alcance"] == "Almacen · Picker; 1 persona" and guardado["destinatarios"] == 3
    push_enviados = _avisos("comunicado")
    assert sorted(e["empleado_id"] for e in push_enviados) == [10, 13, 14]
    assert json.loads(push_enviados[0]["datos"]) == {"comunicado_id": str(cid), "ruta": f"/comunicados/{cid}"}

    bandeja = com.mis_comunicados(emp(10))
    assert bandeja["no_leidos"] == 1 and bandeja["items"][0]["titulo"] == "Corte de luz"
    assert com.mis_comunicados(emp(11))["total"] == 0  # no estaba entre los destinatarios
    leido = com.leer(emp(10), cid)
    assert leido["leido"] and leido["leido_at"] == "2026-10-14T09:30:15"
    assert com.leer(emp(10), cid)["leido_at"] == "2026-10-14T09:30:15"  # la primera lectura queda
    with pytest.raises(com.Error, match="no encontrado"):
        com.leer(emp(11), cid)
    assert com.leer_todos(emp(13)) == 1

    panel = com.listado(ADMIN)
    assert panel["items"][0]["leidos"] == 2 and panel["items"][0]["leidos_pct"] == 67
    detalle = com.detalle(ADMIN, cid, "pendientes")
    assert [p["id"] for p in detalle["personas"]] == [14] and detalle["leidos"] == 2
    with pytest.raises(com.Error):
        com.detalle(dict(ADMIN, empresa_id=2), cid)

    com.eliminar(ADMIN, cid)
    assert com.mis_comunicados(emp(10))["total"] == 0


@pytest.fixture
def client(base, monkeypatch):
    import routes.carga_routes as carga_routes
    import utils.jwt_guard as jwt_guard
    import web.auth.decorators as auth
    from web.comunicados import routes

    app = Flask(__name__, template_folder=str(Path(__file__).resolve().parents[1] / "templates"))
    app.secret_key = "test"
    app.register_blueprint(routes.web)
    app.register_blueprint(routes.mobile)
    app.jinja_env.globals.update(csp_nonce=lambda: "n", csrf_token=lambda: "t",
                                 can_web=lambda code, action="ver": code == "comunicados",
                                 export_toolbar={"enabled": False, "items": []})
    monkeypatch.setattr(auth, "can_access_module", lambda uid, module, action="ver": module == "comunicados")
    monkeypatch.setattr(routes, "_cached_web_user", lambda uid: dict(id=99, empresa_id=1, activo=1))
    monkeypatch.setattr(routes, "log_audit", lambda *a, **kw: None)
    monkeypatch.setattr(jwt_guard, "verificar_token", lambda token: dict(empleado_id=int(token)))
    monkeypatch.setattr(carga_routes, "get_by_id", emp)
    test_client = app.test_client()
    with test_client.session_transaction() as sess:
        sess["user_id"] = 99
    return test_client


def test_panel_y_api_de_comunicados(client):
    html = client.get("/comunicados/").get_data(as_text=True)
    assert "Todavía no enviaste comunicados" in html
    html = client.get("/comunicados/nuevo").get_data(as_text=True)
    assert 'data-reu-verbo="Llega a"' in html and "Enviar comunicado" in html and "Toda la empresa" in html

    r = client.post("/comunicados/nuevo", data={"titulo": "Sin destino", "mensaje": "x"})
    assert r.status_code == 400 and "Elegí a quién enviarlo" in r.get_data(as_text=True)
    assert 'value="Sin destino"' in r.get_data(as_text=True)  # conserva lo escrito

    r = client.post("/comunicados/nuevo", data={"titulo": "Uniforme nuevo", "mensaje": "Desde el lunes.",
                                                 "regla": ["todos"], "sede": ["1"]})
    assert r.status_code == 302
    cid = int(r.headers["Location"].rstrip("/").split("/")[-1])
    html = client.get(f"/comunicados/{cid}").get_data(as_text=True)
    assert "Uniforme nuevo" in html and "Toda la empresa · Sucursal Central" in html and "0%" in html

    headers = {"Authorization": "Bearer 10"}
    bandeja = client.get("/api/v1/mobile/comunicados", headers=headers).json
    assert bandeja["no_leidos"] == 1 and bandeja["items"][0]["id"] == cid and bandeja["items"][0]["leido"] is False
    assert client.get(f"/api/v1/mobile/comunicados/{cid}", headers=headers).json["leido"] is True
    assert client.get("/api/v1/mobile/comunicados", headers=headers).json["no_leidos"] == 0
    assert client.post(f"/api/v1/mobile/comunicados/{cid}/leido", headers={"Authorization": "Bearer 12"}).status_code == 404
    assert client.post("/api/v1/mobile/comunicados/leer-todos", headers={"Authorization": "Bearer 11"}).json == {"marcados": 1}
    assert client.get("/api/v1/mobile/comunicados").status_code == 401

    assert client.post(f"/comunicados/{cid}/eliminar").status_code == 302
    assert client.get("/api/v1/mobile/comunicados", headers=headers).json["total"] == 0
