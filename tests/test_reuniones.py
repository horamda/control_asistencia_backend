"""Modulo Reuniones: recurrencia, convocados, QR, cierre con ausentes y estadisticas."""
import datetime as dt
from pathlib import Path

import pytest
from flask import Flask

from services import reunion_service as svc
from tests.test_seguridad import database  # noqa: F401  (fixture de base aislada)

D = dt.date


def reunion(**kw):
    base = dict(id=1, empresa_id=1, nombre="Seguridad", frecuencia="semanal", dias_semana="2", mensual_tipo=None,
                dia_mes=None, semana_mes=None, hora_inicio="09:00", duracion_min=60, fecha_inicio=D(2026, 1, 1),
                fecha_fin=None, tolerancia_antes_min=15, tarde_despues_min=10, cierre_despues_min=None)
    base.update(kw)
    return base


# --- Recurrencia (sin base) -----------------------------------------------------------

def test_semanal_y_diaria_respetan_dias_y_vigencia():
    r = reunion(dias_semana="0,2", fecha_fin=D(2026, 10, 31))
    assert [f.isoformat() for f in svc.fechas(r, D(2026, 10, 12), D(2026, 10, 18))] == ["2026-10-12", "2026-10-14"]
    assert not svc.ocurre_en(r, D(2026, 11, 2))  # despues de la fecha de fin
    assert not svc.ocurre_en(reunion(fecha_inicio=D(2026, 10, 20)), D(2026, 10, 14))
    diaria = reunion(frecuencia="diaria", dias_semana="0,1,2,3,4")
    assert len(list(svc.fechas(diaria, D(2026, 10, 12), D(2026, 10, 18)))) == 5
    assert svc.describir(diaria) == "De lunes a viernes a las 09:00 (60 min)"
    assert svc.describir(reunion(dias_semana="0,2")) == "Todos los lunes y miércoles a las 09:00 (60 min)"


def test_mensual_dia_fijo_usa_el_ultimo_dia_en_meses_cortos():
    r = reunion(frecuencia="mensual", mensual_tipo="dia", dia_mes=31, dias_semana=None)
    assert svc.ocurre_en(r, D(2026, 2, 28)) and svc.ocurre_en(r, D(2026, 10, 31))
    assert not svc.ocurre_en(r, D(2026, 10, 30))
    assert svc.describir(r) == "El día 31 de cada mes a las 09:00 (60 min)"


def test_mensual_por_semana_primer_lunes_y_ultimo_viernes():
    primer_lunes = reunion(frecuencia="mensual", mensual_tipo="semana", semana_mes=1, dias_semana="0")
    assert [f.day for f in svc.fechas(primer_lunes, D(2026, 10, 1), D(2026, 12, 31))] == [5, 2, 7]
    ultimo_viernes = reunion(frecuencia="mensual", mensual_tipo="semana", semana_mes=5, dias_semana="4")
    assert [f.day for f in svc.fechas(ultimo_viernes, D(2026, 10, 1), D(2026, 11, 30))] == [30, 27]
    assert svc.describir(ultimo_viernes) == "El último viernes de cada mes a las 09:00 (60 min)"


def test_ventana_de_registro():
    h = svc.horarios(reunion(cierre_despues_min=30), D(2026, 10, 14))
    assert (h["ventana_desde"].time(), h["tarde_desde"].time(), h["ventana_hasta"].time(), h["fin"].time()) == (
        dt.time(8, 45), dt.time(9, 10), dt.time(9, 30), dt.time(10, 0))
    assert svc.horarios(reunion(), D(2026, 10, 14))["ventana_hasta"].time() == dt.time(10, 0)  # hasta el final


@pytest.mark.parametrize("cambios,mensaje", [
    (dict(dias_semana=[]), "al menos un día"),
    (dict(hora_inicio="23:30", duracion_min="60"), "mismo día"),
    (dict(tarde_despues_min="20", cierre_despues_min="10"), "cierre del registro"),
    (dict(frecuencia="mensual", mensual_tipo="dia", dia_mes="32"), "Día del mes"),
    (dict(nombre=""), "Nombre"),
])
def test_validacion_del_formulario(cambios, mensaje):
    data = dict(nombre="Seguridad", frecuencia="semanal", dias_semana=["2"], hora_inicio="09:00", duracion_min="60")
    data.update(cambios)
    with pytest.raises(svc.Error, match=mensaje):
        svc._validar(data)


def test_qr_rechaza_contenido_ajeno():
    with pytest.raises(svc.Error, match="no es de una reunión"):
        svc._leer_qr("https://ejemplo.com/?x=1")
    with pytest.raises(svc.Error):
        svc._leer_qr(svc.QR_PREFIX + "no-es-un-jwt")


# --- Flujo completo (base real, corre en CI) -------------------------------------------------

AHORA = {"valor": dt.datetime(2026, 10, 13, 8, 0)}


@pytest.fixture
def reuniones_db(database, monkeypatch):  # noqa: F811
    monkeypatch.setenv("JWT_SECRET", "reuniones-test-secret-0123456789abcdef0123456789")
    conn = database()
    c = conn.cursor()
    for sql in ("ALTER TABLE sectores ADD COLUMN empresa_id INT NOT NULL DEFAULT 1",
                "ALTER TABLE puestos ADD COLUMN empresa_id INT NOT NULL DEFAULT 1",
                "ALTER TABLE empleados ADD COLUMN dni VARCHAR(20) NULL",
                "ALTER TABLE sucursales ADD COLUMN empresa_id INT NOT NULL DEFAULT 1"):
        try:
            c.execute(sql)
        except Exception:
            pass  # la columna ya existe en el esquema base
    for sql in [
        "CREATE TABLE IF NOT EXISTS empleado_puestos (id INT AUTO_INCREMENT PRIMARY KEY, empleado_id INT, empresa_id INT,"
        " sector_id INT, puesto_id INT, activo TINYINT DEFAULT 1)",
        "CREATE TABLE IF NOT EXISTS vacaciones (id INT AUTO_INCREMENT PRIMARY KEY, empleado_id INT, fecha_desde DATE, fecha_hasta DATE)",
        "CREATE TABLE IF NOT EXISTS francos (id INT AUTO_INCREMENT PRIMARY KEY, empleado_id INT, fecha DATE)",
        "INSERT INTO sectores (id, nombre) VALUES (2, 'Almacen')",
        "INSERT INTO puestos (id, nombre) VALUES (2, 'Picker')",
        "UPDATE empleados SET sector_id=2, puesto_id=2 WHERE id=13",
        "INSERT INTO empleados (id, empresa_id, sucursal_id, sector_id, puesto_id, activo, legajo, nombre, apellido)"
        " VALUES (14, 1, 1, 2, 2, 1, '0014', 'No', 'Convocado')",
        "INSERT INTO vacaciones (empleado_id, fecha_desde, fecha_hasta) VALUES (12, '2026-10-10', '2026-10-20')",
        "UPDATE sucursales SET empresa_id=2 WHERE id=3",
        (Path(__file__).resolve().parents[1] / "migrations/20260723_02_asistencia_dias_no_laborables.sql")
        .read_text(encoding="utf-8").strip().rstrip(";"),
    ]:
        c.execute(sql)
    from scripts.migrate_20261016_01_reuniones import migrate_cursor
    from scripts.migrate_20261016_02_reuniones_sucursales import migrate_cursor as migrate_sedes
    from scripts.migrate_20261016_03_feriados import migrate_cursor as migrate_feriados, migrate_unificar
    for _ in range(2):  # idempotentes
        migrate_cursor(c)
        migrate_sedes(c)
        migrate_feriados(c)
        migrate_unificar(c)
    conn.commit()
    c.close()
    conn.close()
    AHORA["valor"] = dt.datetime(2026, 10, 13, 8, 0)
    monkeypatch.setattr(svc, "now_local", lambda: AHORA["valor"])
    return database


ADMIN = dict(empresa_id=1, user_id=99)


def emp(eid):
    with svc.db.transaction(read_only=True) as c:
        return svc.db.one(c, "SELECT * FROM empleados WHERE id=%s", (eid,))


def crear(**cambios):
    data = dict(nombre="Seguridad semanal", lugar="Sala 1", frecuencia="semanal", dias_semana=["2"], hora_inicio="09:00",
                duracion_min="60", tolerancia_antes_min="15", tarde_despues_min="10", qr_modo="ambos",
                reglas=["1:1"], empleados=["13"])
    data.update(cambios)
    return svc.guardar(ADMIN, data)


def test_flujo_qr_cierre_y_estadisticas(reuniones_db):
    rid = crear()
    with svc.db.transaction(read_only=True) as c:
        r = svc.obtener(c, ADMIN, rid)
        assert [e["id"] for e in svc.convocados(c, r)] == sorted([10, 11, 12, 13], key=lambda i: {
            10: "Perez", 11: "Garcia", 12: "Sucursal", 13: "Ajena"}[i])
    qr = svc.qr_fijo(r)
    assert svc.qr_fijo(dict(r)) == qr  # el QR impreso es siempre el mismo (misma imagen)

    AHORA["valor"] = dt.datetime(2026, 10, 14, 8, 30)
    with pytest.raises(svc.Error, match="Se habilita a las 08:45"):
        svc.registrar_qr(emp(10), qr)
    AHORA["valor"] = dt.datetime(2026, 10, 14, 8, 50)
    primero = svc.registrar_qr(emp(10), qr, lat=-34.6, lon=-58.4)
    assert primero["estado"] == "presente" and not primero["ya_registrado"]
    assert svc.registrar_qr(emp(10), qr)["ya_registrado"]  # idempotente
    with pytest.raises(svc.Error, match="No estás convocado"):
        svc.registrar_qr(emp(14), qr)
    with pytest.raises(svc.Error, match="otra empresa"):
        svc.registrar_qr(emp(20), qr)

    AHORA["valor"] = dt.datetime(2026, 10, 14, 9, 20)
    dinamico = svc.qr_dinamico(r, D(2026, 10, 14))
    assert svc.registrar_qr(emp(11), dinamico)["estado"] == "tarde"
    with pytest.raises(svc.Error, match="otra fecha"):
        svc.registrar_qr(emp(13), svc.qr_dinamico(r, D(2026, 10, 13)))

    AHORA["valor"] = dt.datetime(2026, 10, 14, 10, 1)
    with pytest.raises(svc.Error, match="cerró a las 10:00"):
        svc.registrar_qr(emp(13), qr)

    # Cierre: 13 ausente, 12 justificado por vacaciones. Idempotente.
    AHORA["valor"] = dt.datetime(2026, 10, 14, 10, 5)
    resumen = svc.cerrar_ocurrencias(ahora=AHORA["valor"])
    assert (resumen["cerradas"], resumen["ausentes"], resumen["justificados"]) == (1, 1, 1)
    assert svc.cerrar_ocurrencias(ahora=AHORA["valor"])["cerradas"] == 0

    d = svc.detalle(ADMIN, rid, desde=D(2026, 10, 1), hasta=D(2026, 10, 31))
    assert (d["total"]["convocatorias"], d["total"]["asistidas"], d["total"]["justificados"]) == (4, 2, 1)
    assert d["total"]["asistencia_pct"] == 66.7 and d["total"]["puntualidad_pct"] == 50.0
    assert d["ranking"][0]["empleado_id"] == 13  # el que falto, primero
    assert d["ocurrencias"][0]["estado"] == "cerrada" and d["ocurrencias"][0]["convocados"] == 4

    occ = svc.ocurrencia_detalle(ADMIN, rid, D(2026, 10, 14))
    assert occ["conteo"] == {"presente": 1, "tarde": 1, "ausente": 1, "justificado": 1, "pendiente": 0}

    # Correccion manual desde el panel.
    svc.marcar_manual(ADMIN, rid, D(2026, 10, 14), 13, "justificado", "Médico")
    assert svc.detalle(ADMIN, rid, desde=D(2026, 10, 1), hasta=D(2026, 10, 31))["total"]["asistencia_pct"] == 100.0

    # Empleado: estadisticas, historial y proximas (hoy registrado, la semana que viene pendiente).
    mias = svc.estadisticas_empleado(emp(11), D(2026, 10, 1), D(2026, 10, 31))
    assert mias["totales"]["tarde"] == 1 and mias["totales"]["asistencia_pct"] == 100.0
    assert mias["totales"]["horas_asistidas"] == 1.0 and mias["por_reunion"][0]["minutos_asistidos"] == 60
    assert svc.historial_empleado(emp(10))["items"][0]["estado"] == "presente"
    semana = svc.proximas(emp(10), 8, ahora=AHORA["valor"])
    prox = semana["items"]
    assert [(p["fecha"], p["estado"]) for p in prox] == [("2026-10-14", "presente"), ("2026-10-21", "pendiente")]
    assert semana["resumen"] == {"reuniones": 2, "minutos": 120, "horas": 2.0, "registradas": 1, "tarde": 0,
                                 "pendientes": 1, "ausentes": 0, "justificadas": 0, "canceladas": 0, "superpuestas": 0}
    assert svc.mis_reuniones(emp(14)) == [] and svc.mis_reuniones(emp(10))[0]["mis_estadisticas"]["horas_asistidas"] == 1.0
    assert svc.mis_reuniones(emp(13))[0]["proxima_fecha"] == "2026-10-14"
    assert svc.mis_reuniones(emp(14)) == []

    # Cancelar una fecha futura: la app la ve cancelada y el QR no registra.
    svc.cancelar_ocurrencia(ADMIN, rid, D(2026, 10, 21), "Feriado")
    prox = svc.proximas(emp(10), 8, ahora=AHORA["valor"])["items"]
    assert prox[1]["cancelada"] and prox[1]["motivo_cancelacion"] == "Feriado"
    AHORA["valor"] = dt.datetime(2026, 10, 21, 9, 0)
    with pytest.raises(svc.Error, match="cancelada"):
        svc.registrar_qr(emp(10), qr)

    # Regenerar el QR invalida el impreso. Con asistencias no se puede eliminar.
    svc.regenerar_qr(ADMIN, rid)
    with pytest.raises(svc.Error, match="ya no es válido"):
        svc.registrar_qr(emp(10), qr)
    with pytest.raises(svc.Error, match="desactivala"):
        svc.eliminar(ADMIN, rid)


def test_participantes_toda_la_empresa_y_validaciones(reuniones_db):
    rid = crear(reglas=["todos", "1"], empleados=["10"], qr_modo="fijo")
    with svc.db.transaction(read_only=True) as c:
        r = svc.obtener(c, ADMIN, rid)
        assert svc.reglas(c, rid) == [{"empleado_id": None, "sector_id": None, "puesto_id": None}]
        assert len(svc.convocados(c, r)) == 5  # empresa 1 completa, sin la 2
    with pytest.raises(svc.Error, match="QR impreso"):
        AHORA["valor"] = dt.datetime(2026, 10, 14, 9, 0)
        svc.registrar_qr(emp(10), svc.qr_dinamico(r, D(2026, 10, 14)))
    with pytest.raises(svc.Error, match="no pertenecen"):
        crear(empleados=["20"])
    with pytest.raises(svc.Error, match="al menos un participante"):
        crear(reglas=[], empleados=[])
    sin_uso = crear(nombre="Sin uso")
    svc.eliminar(ADMIN, sin_uso)
    with pytest.raises(svc.Error, match="no encontrada"):
        svc.eliminar(dict(empresa_id=2), rid)  # otra empresa no la ve


# --- Panel y API -------------------------------------------------------------------------------

@pytest.fixture
def client(reuniones_db, monkeypatch):
    import routes.carga_routes as carga_routes
    import utils.jwt_guard as jwt_guard
    import web.auth.decorators as auth
    from web.reuniones import routes

    app = Flask(__name__, template_folder=str(Path(__file__).resolve().parents[1] / "templates"))
    app.secret_key = "test"
    app.config["TESTING"] = True
    app.register_blueprint(routes.web)
    app.register_blueprint(routes.mobile)
    permisos = {"acciones": {"ver", "crear", "editar", "eliminar", "exportar"}}
    app.jinja_env.globals.update(csp_nonce=lambda: "n", csrf_token=lambda: "t",
                                 can_web=lambda code, action="ver": code == "reuniones" and action in permisos["acciones"],
                                 export_toolbar={"enabled": False, "items": []})
    monkeypatch.setattr(auth, "can_access_module", lambda uid, module, action="ver": module == "reuniones"
                        and action in permisos["acciones"])
    monkeypatch.setattr(routes, "_cached_web_user", lambda uid: dict(id=99, empresa_id=1, activo=1))
    monkeypatch.setattr(routes, "now_local", lambda: AHORA["valor"])
    monkeypatch.setattr(jwt_guard, "verificar_token", lambda token: dict(empleado_id=int(token)))
    monkeypatch.setattr(carga_routes, "get_by_id", emp)
    monkeypatch.setattr(routes, "log_audit", lambda *a, **kw: None)
    test_client = app.test_client()
    with test_client.session_transaction() as sess:
        sess["user_id"] = 99
    test_client.permisos = permisos
    return test_client


def test_panel_crud_y_pantallas(client):
    assert client.get("/reuniones/nueva").status_code == 200
    response = client.post("/reuniones/nueva", data={
        "nombre": "Diaria de turno", "frecuencia": "diaria", "dias_semana": ["0", "1", "2", "3", "4"],
        "hora_inicio": "07:30", "duracion_min": "15", "qr_modo": "ambos", "regla": ["2"], "empleado": ["10"]})
    assert response.status_code == 302
    rid = int(response.headers["Location"].rstrip("/").split("/")[-1])

    AHORA["valor"] = dt.datetime(2026, 10, 14, 7, 35)
    paginas = ["/reuniones/", f"/reuniones/{rid}", f"/reuniones/{rid}/editar", f"/reuniones/{rid}/qr",
               f"/reuniones/{rid}/qr/proyectar", f"/reuniones/{rid}/qr/vivo", f"/reuniones/{rid}/fecha/2026-10-14",
               "/reuniones/estadisticas", f"/reuniones/{rid}/exportar.csv", "/reuniones/estadisticas/exportar.csv"]
    for path in paginas:
        r = client.get(path)
        assert r.status_code == 200, (path, r.get_data(as_text=True)[:400])
    html = client.get(f"/reuniones/{rid}/qr/proyectar").get_data(as_text=True)
    assert 'hx-trigger="every 20s"' in html and "data:image/png;base64" in html
    assert "De lunes a viernes a las 07:30" in client.get("/reuniones/").get_data(as_text=True)

    # Error de validacion: vuelve al formulario conservando los datos.
    r = client.post(f"/reuniones/{rid}/editar", data={"nombre": "Diaria de turno", "frecuencia": "semanal",
                                                      "hora_inicio": "07:30", "duracion_min": "15", "regla": ["2"]})
    assert r.status_code == 400 and "Elegí al menos un día" in r.get_data(as_text=True)

    client.permisos["acciones"] = {"ver"}
    html = client.get(f"/reuniones/{rid}").get_data(as_text=True)
    assert f"/reuniones/{rid}/editar" not in html and f"/reuniones/{rid}/eliminar" not in html
    assert client.post(f"/reuniones/{rid}/eliminar").status_code == 403
    client.permisos["acciones"] = set()
    assert client.get("/reuniones/").status_code == 403


def test_api_mobile(client):
    rid = crear(nombre="Mensual", frecuencia="mensual", mensual_tipo="semana", semana_mes="2", dia_semana_mes="2")
    headers = {"Authorization": "Bearer 10"}
    assert client.get("/api/v1/mobile/reuniones", headers={}).status_code == 401

    AHORA["valor"] = dt.datetime(2026, 10, 14, 8, 0)  # 14/10 es el segundo miercoles
    lista = client.get("/api/v1/mobile/reuniones", headers=headers).json["items"]
    assert lista[0]["descripcion_frecuencia"] == "El segundo miércoles de cada mes a las 09:00 (60 min)"
    prox = client.get("/api/v1/mobile/reuniones/proximas?dias=7", headers=headers).json
    assert prox["items"][0]["estado"] == "pendiente" and prox["items"][0]["inicio"].startswith("2026-10-14T09:00")
    semana = client.get("/api/v1/mobile/reuniones/proximas?semana=actual", headers=headers).json
    assert (semana["desde"], semana["hasta"]) == ("2026-10-12", "2026-10-18")  # lunes a domingo
    assert semana["resumen"]["reuniones"] == 1 and semana["resumen"]["horas"] == 1.0

    with svc.db.transaction(read_only=True) as c:
        qr = svc.qr_fijo(svc.obtener(c, ADMIN, rid))
    AHORA["valor"] = dt.datetime(2026, 10, 14, 9, 2)
    r = client.post("/api/v1/mobile/reuniones/registrar", json={"qr": qr, "lat": -34.6, "lon": -58.4}, headers=headers)
    assert r.status_code == 201 and r.json["estado"] == "presente"
    r = client.post("/api/v1/mobile/reuniones/registrar", json={"qr": qr}, headers=headers)
    assert r.status_code == 200 and r.json["ya_registrado"]
    r = client.post("/api/v1/mobile/reuniones/registrar", json={"qr": qr}, headers={"Authorization": "Bearer 14"})
    assert r.status_code == 403 and "convocado" in r.json["error"]
    assert client.post("/api/v1/mobile/reuniones/registrar", json={"qr": qr, "lat": 200},
                       headers=headers).status_code == 400

    detalle = client.get(f"/api/v1/mobile/reuniones/{rid}", headers=headers).json
    assert detalle["historial"][0]["estado"] == "presente" and detalle["proximas_fechas"][:2] == ["2026-10-14", "2026-11-11"]
    assert client.get(f"/api/v1/mobile/reuniones/{rid}", headers={"Authorization": "Bearer 14"}).status_code == 404
    stats = client.get("/api/v1/mobile/reuniones/estadisticas?desde=2026-10-01&hasta=2026-10-31", headers=headers).json
    assert stats["totales"]["presentes"] == 1 and stats["por_reunion"][0]["nombre"] == "Mensual"
    hist = client.get("/api/v1/mobile/reuniones/historial", headers=headers).json
    assert hist["total"] == 1
    assert client.get("/api/v1/mobile/reuniones/historial?desde=mal", headers=headers).status_code == 400


def test_qr_de_reunion_en_la_fichada_da_un_mensaje_claro():
    from utils.jwt import QRTokenValidationError, extract_qr_token
    with pytest.raises(QRTokenValidationError) as exc:
        extract_qr_token(svc.QR_PREFIX + "eyJ.abc.def")
    assert exc.value.code == "qr_token_reunion"


# --- Sedes por sucursal -------------------------------------------------------------------------
# Empleados del fixture: 10, 11, 13 y 14 en Central (1); 12 en Otra (2); 20 es de otra empresa.

def test_misma_reunion_en_varias_sucursales(reuniones_db):
    import jwt as pyjwt
    rid = crear(reglas=["todos"], empleados=[], qr_modo="ambos", sedes=[
        dict(sucursal_id=1, lugar="Sala Central", hora_inicio="09:00"),
        dict(sucursal_id=2, lugar="Sala Norte", hora_inicio="10:00")])
    with svc.db.transaction(read_only=True) as c:
        base = svc.obtener(c, ADMIN, rid)
        central, norte = svc.sede(c, base, 1), svc.sede(c, base, 2)
        assert {e["id"] for e in svc.convocados(c, base, 1)} == {10, 11, 13, 14}
        assert [e["id"] for e in svc.convocados(c, base, 2)] == [12]
        with pytest.raises(svc.Error, match="no se hace en esa sucursal"):
            svc.sede(c, base, 3)
    assert (central["lugar"], norte["lugar"], svc._hhmm(svc._time(norte["hora_inicio"]))) == ("Sala Central", "Sala Norte", "10:00")

    # Cada empleado ve la reunion de su sucursal, con su hora y lugar.
    AHORA["valor"] = dt.datetime(2026, 10, 14, 8, 0)
    item = svc.proximas(emp(12), 1)["items"][0]
    assert (item["sucursal_nombre"], item["lugar"], item["inicio"]) == ("Otra", "Sala Norte", "2026-10-14T10:00:00-03:00")
    assert svc.mis_reuniones(emp(10))[0]["hora_inicio"] == "09:00"

    # El QR de otra sucursal se rechaza con un mensaje claro; el de la propia registra.
    AHORA["valor"] = dt.datetime(2026, 10, 14, 9, 55)
    with pytest.raises(svc.Error, match="Este QR es de la reunión en Central. La tuya es en Otra"):
        svc.registrar_qr(emp(12), svc.qr_fijo(central))
    assert svc.registrar_qr(emp(12), svc.qr_dinamico(norte, D(2026, 10, 14)))["estado"] == "presente"
    AHORA["valor"] = dt.datetime(2026, 10, 14, 8, 50)
    assert svc.registrar_qr(emp(10), svc.qr_fijo(central))["sucursal_nombre"] == "Central"
    # QR impreso antes de las sedes (sin sucursal): vale para la sede del empleado.
    legado = svc.QR_PREFIX + svc._token({"rid": rid, "emp": 1, "m": "fijo", "v": 1}, 600)
    assert pyjwt.decode(legado.split("t=")[1], options={"verify_signature": False}).get("s") is None
    assert svc.registrar_qr(emp(11), legado)["sucursal_nombre"] == "Central"

    # El cierre respeta la ventana de cada sede.
    assert svc.cerrar_ocurrencias(ahora=dt.datetime(2026, 10, 14, 10, 30))["cerradas"] == 1  # solo Central
    resumen = svc.cerrar_ocurrencias(ahora=dt.datetime(2026, 10, 14, 11, 5))
    assert (resumen["cerradas"], resumen["ausentes"]) == (1, 0)  # Norte: 12 ya estaba

    d = svc.detalle(ADMIN, rid, desde=D(2026, 10, 1), hasta=D(2026, 10, 31))
    assert {(x["sucursal_nombre"], x["convocatorias"]) for x in d["por_sede"]} == {("Central", 4), ("Otra", 1)}
    assert len(d["ocurrencias"]) == 2 and d["total"]["convocatorias"] == 5
    solo_norte = svc.detalle(ADMIN, rid, desde=D(2026, 10, 1), hasta=D(2026, 10, 31), sucursal_id=2)
    assert solo_norte["total"]["asistencia_pct"] == 100.0 and [e["empleado_id"] for e in solo_norte["ranking"]] == [12]
    occ = svc.ocurrencia_detalle(ADMIN, rid, D(2026, 10, 14), 2)
    assert occ["conteo"]["presente"] == 1 and [x["sucursal_id"] for x in occ["otras_sedes"]] == [1]
    stats = svc.estadisticas_empresa(ADMIN, D(2026, 10, 1), D(2026, 10, 31))
    assert {x["sucursal_nombre"] for x in stats["por_sucursal"]} == {"Central", "Otra"}
    assert svc.estadisticas_empresa(ADMIN, D(2026, 10, 1), D(2026, 10, 31), 2)["total"]["convocatorias"] == 1

    # Corregir y cancelar por sede; "todas" cancela en cada sucursal.
    svc.marcar_manual(ADMIN, rid, D(2026, 10, 14), 13, "justificado", "Médico", sucursal_id=1)
    svc.cancelar_ocurrencia(ADMIN, rid, D(2026, 10, 21), "Feriado", sucursal_id=None)
    AHORA["valor"] = dt.datetime(2026, 10, 15, 8, 0)
    assert all(p["cancelada"] for p in svc.proximas(emp(12), 7)["items"] + svc.proximas(emp(10), 7)["items"])


def test_empleado_de_otra_sucursal_no_esta_convocado(reuniones_db):
    rid = crear(reglas=["todos"], empleados=[], sedes=[dict(sucursal_id=2)])
    assert svc.mis_reuniones(emp(10)) == [] and len(svc.mis_reuniones(emp(12))) == 1
    with svc.db.transaction(read_only=True) as c:
        qr = svc.qr_fijo(svc.sede(c, svc.obtener(c, ADMIN, rid), 2))
        assert svc.contar_convocados(c, 1)[rid] == 1
    AHORA["valor"] = dt.datetime(2026, 10, 14, 9, 0)
    with pytest.raises(svc.Error, match="No estás convocado"):
        svc.registrar_qr(emp(10), qr)
    with pytest.raises(svc.Error, match="Sucursal inválida"):
        crear(sedes=[dict(sucursal_id=3)])  # sucursal de otra empresa
    with pytest.raises(svc.Error, match="mismo día"):
        crear(duracion_min="60", sedes=[dict(sucursal_id=1, hora_inicio="23:30")])


def test_panel_sedes(client):
    response = client.post("/reuniones/nueva", data={
        "nombre": "Semanal de ventas", "frecuencia": "semanal", "dias_semana": ["2"], "hora_inicio": "09:00",
        "duracion_min": "60", "qr_modo": "ambos", "regla": ["todos"], "sede": ["1", "2"],
        "sede_lugar_1": "Sala Central", "sede_hora_1": "", "sede_lugar_2": "", "sede_hora_2": "10:30"})
    assert response.status_code == 302
    rid = int(response.headers["Location"].rstrip("/").split("/")[-1])
    with svc.db.transaction(read_only=True) as c:
        assert [(x["sucursal_id"], x["lugar"], x["hora_inicio"]) for x in svc.sedes(c, rid)] == [
            (1, "Sala Central", None), (2, None, dt.timedelta(hours=10, minutes=30))]
    html = client.get(f"/reuniones/{rid}/qr").get_data(as_text=True)
    assert html.count('class="reu-qr-print"') == 2 and "Central" in html and "Otra" in html
    AHORA["valor"] = dt.datetime(2026, 10, 14, 10, 20)
    for path in [f"/reuniones/{rid}", f"/reuniones/{rid}?sucursal=2", f"/reuniones/{rid}/editar", "/reuniones/?sucursal=2",
                 f"/reuniones/{rid}/fecha/2026-10-14?sucursal=2", f"/reuniones/{rid}/qr/proyectar?sucursal=2",
                 "/reuniones/estadisticas?sucursal=1"]:
        r = client.get(path)
        assert r.status_code == 200, (path, r.get_data(as_text=True)[:300])
    assert "Sala Central" in client.get(f"/reuniones/{rid}").get_data(as_text=True)
    assert "10:30 a 11:30" in client.get(f"/reuniones/{rid}/qr/proyectar?sucursal=2").get_data(as_text=True)
    assert client.get(f"/reuniones/{rid}/fecha/2026-10-14?sucursal=3").status_code == 404


# --- Dias no laborables (calendario del reporte mensual) ------------------------------------------
# 12/10/2026 es lunes.

LUNES = D(2026, 10, 12)


def test_dia_no_laborable_pospone_al_siguiente_dia_habil():
    r = reunion(dias_semana="0", _feriados={LUNES: "Diversidad Cultural"})
    assert list(svc.fechas(r, D(2026, 10, 5), D(2026, 10, 19))) == [D(2026, 10, 5), D(2026, 10, 13), D(2026, 10, 19)]
    item = svc.info_fecha(r, D(2026, 10, 13))
    assert item["original"] == LUNES and not svc.ocurre_en(r, LUNES)
    assert svc.motivo_cambio(item) == "Pospuesta del lunes 12/10 por día no laborable (Diversidad Cultural)."
    sin_nombre = reunion(dias_semana="0", _feriados={LUNES: "Día no laborable"})
    assert svc.motivo_cambio(svc.info_fecha(sin_nombre, LUNES)) == "Pospuesta del lunes 12/10 por día no laborable."
    # La fecha pospuesta aparece aunque el rango empiece despues del dia no laborable.
    assert list(svc.fechas(r, D(2026, 10, 13), D(2026, 10, 13))) == [D(2026, 10, 13)]


def test_dia_no_laborable_salta_fines_de_semana_y_dias_seguidos():
    viernes = D(2026, 10, 16)
    r = reunion(dias_semana="4", _feriados={viernes: "Local", D(2026, 10, 19): "Otro"})
    assert svc.info_fecha(r, viernes)["fecha"] == D(2026, 10, 20)  # sabado, domingo y lunes no laborable
    sabado = reunion(dias_semana="5", _feriados={D(2026, 10, 17): "X"})
    assert svc.info_fecha(sabado, D(2026, 10, 17))["fecha"] == D(2026, 10, 19)  # siguiente dia habil


def test_dia_no_laborable_omitir_mantener_y_sin_duplicar_diarias():
    feriado = {LUNES: "Diversidad Cultural"}
    diaria = reunion(frecuencia="diaria", dias_semana="0,1,2,3,4", _feriados=feriado)
    assert list(svc.fechas(diaria, LUNES, D(2026, 10, 13))) == [D(2026, 10, 13)]  # el martes ya tenia la suya
    assert svc.info_fecha(diaria, LUNES)["omitida"]
    assert not list(svc.fechas(reunion(dias_semana="0", feriado_accion="omitir", _feriados=feriado), LUNES, LUNES))
    assert list(svc.fechas(reunion(dias_semana="0", feriado_accion="mantener", _feriados=feriado), LUNES, LUNES)) == [LUNES]
    fin = reunion(dias_semana="0", fecha_fin=LUNES, _feriados=feriado)
    assert not list(svc.fechas(fin, LUNES, D(2026, 10, 20)))  # no se pospone mas alla de la vigencia


def _no_laborable(empresa_id, sucursal_id, sector_id, fecha, motivo=None):
    with svc.db.transaction() as c:
        c.execute("INSERT INTO asistencia_dias_no_laborables (empresa_id, sucursal_id, sector_id, fecha, motivo)"
                  " VALUES (%s, %s, %s, %s, %s)", (empresa_id, sucursal_id, sector_id, fecha, motivo))


def test_reuniones_usan_el_calendario_del_reporte_mensual(reuniones_db, monkeypatch):
    from repositories import asistencia_dia_no_laborable_repository as repo
    from services import feriado_service as fer
    monkeypatch.setattr(repo, "get_db", reuniones_db)
    # Marcados como en produccion: general sin nombre, uno de la sucursal Norte y uno de un sector.
    repo.replace_month_dates(year=2026, month=10, dates={"2026-10-12", "2026-10-04"}, empresa_id=0)
    _no_laborable(1, 2, 0, "2026-10-19", "Aniversario Norte")
    _no_laborable(1, 0, 1, "2026-10-26")  # solo un sector: no mueve la reunion

    AHORA["valor"] = dt.datetime(2026, 10, 1, 8, 0)
    rid = crear(dias_semana=["0"], reglas=["todos"], empleados=[], qr_modo="fijo",
                sedes=[dict(sucursal_id=1), dict(sucursal_id=2)])
    # Central: el 12 pasa al 13. Norte: ademas su dia propio del 19 pasa al 20.
    central = [(p["fecha"], p["fecha_original"]) for p in svc.proximas(emp(10), 31)["items"]]
    assert central == [("2026-10-05", None), ("2026-10-13", "2026-10-12"), ("2026-10-19", None), ("2026-10-26", None)]
    norte = svc.proximas(emp(12), 21)["items"]
    assert [(p["fecha"], p["fecha_original"]) for p in norte] == [
        ("2026-10-05", None), ("2026-10-13", "2026-10-12"), ("2026-10-20", "2026-10-19")]
    assert norte[1]["motivo_cambio"] == "Pospuesta del lunes 12/10 por día no laborable."
    assert norte[2]["motivo_cambio"] == "Pospuesta del lunes 19/10 por día no laborable (Aniversario Norte)."

    with svc.db.transaction(read_only=True) as c:
        qr = svc.qr_fijo(svc.sede(c, svc.obtener(c, ADMIN, rid), 1))
    AHORA["valor"] = dt.datetime(2026, 10, 12, 9, 0)
    with pytest.raises(svc.Error, match=r"Hoy es día no laborable: la reunión se pasó al martes 13/10"):
        svc.registrar_qr(emp(10), qr)
    AHORA["valor"] = dt.datetime(2026, 10, 13, 9, 0)
    assert svc.registrar_qr(emp(10), qr)["fecha"] == "2026-10-13"
    occ = svc.ocurrencia_detalle(ADMIN, rid, D(2026, 10, 13), 1)
    assert occ["ocurrencia"]["fecha_original"] == LUNES and "día no laborable" in occ["cambio"]
    with pytest.raises(svc.Error, match="Pospuesta del lunes 12/10"):
        svc.ocurrencia_detalle(ADMIN, rid, LUNES, 1)
    assert svc.historial_empleado(emp(10))["items"][0]["fecha_original"] == "2026-10-12"

    # Al guardar el calendario mensual, las fechas futuras sin registros se reprograman.
    with svc.db.transaction() as c:
        norte_sede = svc.sede(c, svc.obtener(c, ADMIN, rid), 2)
        assert svc.ocurrencia(c, norte_sede, D(2026, 10, 20))["fecha_original"] == D(2026, 10, 19)
        c.execute("DELETE FROM asistencia_dias_no_laborables WHERE motivo='Aniversario Norte'")
    fer.reprogramar_reuniones(1, D(2026, 10, 13))
    assert [p["fecha"] for p in svc.proximas(emp(12), 10)["items"]][-1] == "2026-10-19"


def test_calendario_mensual_conserva_nombres(reuniones_db, monkeypatch):
    from repositories import asistencia_dia_no_laborable_repository as repo
    monkeypatch.setattr(repo, "get_db", reuniones_db)
    _no_laborable(0, 0, 0, "2026-10-12", "Diversidad Cultural")
    # El editor del reporte mensual guarda el mes completo: el dia que sigue marcado conserva su nombre.
    repo.replace_month_dates(year=2026, month=10, dates={"2026-10-12", "2026-10-26"}, empresa_id=0)
    assert repo.get_dates(year=2026, month=10, empresa_id=1) == {"2026-10-12", "2026-10-26"}
    with svc.db.transaction(read_only=True) as c:
        nombres = {str(r["fecha"]): r["motivo"] for r in svc.db.all_rows(c, "SELECT fecha, motivo FROM asistencia_dias_no_laborables")}
    assert nombres == {"2026-10-12": "Diversidad Cultural", "2026-10-26": None}
    repo.replace_month_dates(year=2026, month=10, dates={"2026-10-26"}, empresa_id=0)
    assert repo.get_dates(year=2026, month=10, empresa_id=1) == {"2026-10-26"}


def test_migracion_traspasa_la_tabla_feriados_anterior(reuniones_db):
    from scripts.migrate_20261016_03_feriados import migrate_unificar
    conn = reuniones_db()
    c = conn.cursor()
    c.execute("CREATE TABLE feriados (id INT PRIMARY KEY, empresa_id INT, sucursal_id INT, fecha DATE, nombre VARCHAR(150), creado_por INT)")
    c.execute("INSERT INTO asistencia_dias_no_laborables (empresa_id, sucursal_id, sector_id, fecha) VALUES (1,0,0,'2026-11-11')")
    c.execute("INSERT INTO feriados VALUES (1,1,0,'2026-11-11','San Martín de Tours',99), (2,1,2,'2026-11-20','Aniversario',99)")
    migrate_unificar(c)
    migrate_unificar(c)  # ya no existe: no hace nada
    c.execute("SELECT fecha, sucursal_id, motivo FROM asistencia_dias_no_laborables ORDER BY fecha")
    assert [(str(f), s, m) for f, s, m in c.fetchall()] == [("2026-11-11", 0, "San Martín de Tours"), ("2026-11-20", 2, "Aniversario")]
    c.execute("SHOW TABLES LIKE 'feriados'")
    assert c.fetchall() == []
    conn.commit()
    c.close()
    conn.close()


# --- Superposiciones -------------------------------------------------------------------------------

def test_superposiciones_aviso_y_justificacion(reuniones_db):
    # A: miercoles 09:00-10:00 para toda la empresa. B: miercoles 09:30-10:30 solo para el empleado 10.
    a = crear(nombre="Seguridad", reglas=["todos"], empleados=[])
    b = crear(nombre="Ventas", hora_inicio="09:30", reglas=[], empleados=["10"])
    tarde = crear(nombre="Tarde", hora_inicio="15:00", reglas=["todos"], empleados=[])  # no se pisa
    hoy = D(2026, 10, 13)
    conflictos = svc.conflictos(ADMIN, a, desde=hoy, dias=14)
    assert [(g["nombre"], g["fechas"], g["empleados"], g["horario"]) for g in conflictos] == [("Ventas", 2, 1, "09:30 a 10:30")]
    assert svc.conflictos(ADMIN, tarde, desde=hoy, dias=14) == []

    # La app marca la superposicion en las dos.
    AHORA["valor"] = dt.datetime(2026, 10, 14, 8, 0)
    semana = svc.proximas(emp(10), 1)
    assert semana["resumen"]["superpuestas"] == 2
    assert {x["nombre"] for i in semana["items"] for x in i["superpuesta_con"]} == {"Seguridad", "Ventas"}
    assert all(not i["superpuesta_con"] for i in svc.proximas(emp(11), 1)["items"])

    # Asiste a B; al cerrar A, su ausencia en A queda justificada.
    with svc.db.transaction(read_only=True) as c:
        qr_b = svc.qr_fijo(svc.sede(c, svc.obtener(c, ADMIN, b), 0))
    AHORA["valor"] = dt.datetime(2026, 10, 14, 9, 25)
    svc.registrar_qr(emp(10), qr_b)
    svc.cerrar_ocurrencias(ahora=dt.datetime(2026, 10, 14, 10, 5))
    with svc.db.transaction(read_only=True) as c:
        fila = svc.db.one(c, "SELECT estado, observaciones FROM reunion_asistencias WHERE reunion_id=%s AND empleado_id=10", (a,))
    assert fila["estado"] == "justificado" and "Ventas" in fila["observaciones"]

    # Al reves: A cierra primero (queda ausente) y despues registra en una superpuesta que sigue abierta.
    d = crear(nombre="Comite", hora_inicio="09:50", duracion_min="40", reglas=[], empleados=["11"])
    AHORA["valor"] = dt.datetime(2026, 10, 21, 10, 5)
    svc.cerrar_ocurrencias(ahora=AHORA["valor"])
    consulta = "SELECT estado, observaciones FROM reunion_asistencias WHERE reunion_id=%s AND empleado_id=11 AND fecha='2026-10-21'"
    with svc.db.transaction(read_only=True) as c:
        assert svc.db.one(c, consulta, (a,))["estado"] == "ausente"
        qr_d = svc.qr_fijo(svc.sede(c, svc.obtener(c, ADMIN, d), 0))
    AHORA["valor"] = dt.datetime(2026, 10, 21, 10, 10)
    svc.registrar_qr(emp(11), qr_d)
    with svc.db.transaction(read_only=True) as c:
        fila = svc.db.one(c, consulta, (a,))
    assert fila["estado"] == "justificado" and "Comite" in fila["observaciones"]
    AHORA["valor"] = dt.datetime(2026, 10, 13, 8, 0)
    assert svc.reuniones_con_superposicion(ADMIN)[a] >= 1


def test_panel_avisa_superposicion_al_guardar(client):
    crear(nombre="Seguridad", reglas=["todos"], empleados=[])
    r = client.post("/reuniones/nueva", data={"nombre": "Ventas", "frecuencia": "semanal", "dias_semana": ["2"],
                                             "hora_inicio": "09:30", "duracion_min": "60", "qr_modo": "fijo",
                                             "empleado": ["10"]}, follow_redirects=True)
    html = r.get_data(as_text=True)
    assert "se superpone con «Seguridad» (09:00 a 10:00)" in html
    assert "Se superpone con otras reuniones" in html
