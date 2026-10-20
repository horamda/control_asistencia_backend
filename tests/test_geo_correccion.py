"""Ubicacion de la sucursal: las fichadas nuevas se validan contra la ubicacion actual de la sucursal del QR y las
anteriores se corrigen guardando los valores previos.

MySQL real (SH_TEST_DB_PORT) para la correccion; la validacion se prueba sin base."""
import datetime as dt
from pathlib import Path

import pytest
from flask import Flask

from services import sucursal_geo_service as geo
from tests.test_seguridad import database  # noqa: F401  (fixture)

DOLORES = (-36.3226892, -57.6801836)  # ubicacion vieja (calle Chascomus 588, Dolores)
COSTA = (-36.7212921, -56.6776091)  # ubicacion real de la sucursal
OTRA = (-35.575272, -57.978698)  # QR de otra sucursal


# --- Validacion de fichadas nuevas: la sucursal manda ------------------------------------------------------------

def test_valida_contra_la_ubicacion_actual_de_la_sucursal(monkeypatch):
    import repositories.sucursal_repository as repo
    from routes import mobile_v1_routes as rutas

    app = Flask(__name__)
    sucursales = {1: dict(id=1, latitud=COSTA[0], longitud=COSTA[1], radio_permitido_m=100),
                  2: dict(id=2, latitud=None, longitud=None, radio_permitido_m=None),
                  3: dict(id=3, latitud=COSTA[0], longitud=COSTA[1], radio_permitido_m=None)}
    monkeypatch.setattr(repo, "get_by_id", lambda sid: sucursales.get(sid))
    qr = dict(sucursal_id=1, lat=DOLORES[0], lon=DOLORES[1], radio_m=30.0)
    with app.app_context():
        assert rutas._geo_ref_actual_de_sucursal(qr) == dict(sucursal_id=1, lat=COSTA[0], lon=COSTA[1], radio_m=100.0)
        assert rutas._geo_ref_actual_de_sucursal(dict(qr, sucursal_id=2)) == dict(qr, sucursal_id=2)  # sin ubicacion
        assert rutas._geo_ref_actual_de_sucursal(dict(qr, sucursal_id=3))["radio_m"] == 30.0  # sin radio: el del QR
        assert rutas._geo_ref_actual_de_sucursal(dict(qr, sucursal_id=None)) == dict(qr, sucursal_id=None)
        assert rutas._geo_ref_actual_de_sucursal(None) is None
        # De punta a punta: el empleado en la costa queda dentro aunque el QR impreso diga Dolores.
        geo_ok = rutas._validar_geo_scan_qr(dict(id=10, sucursal_id=1), dict(geo_ref=qr), COSTA[0] + 0.0003, COSTA[1])
        assert geo_ok["gps_ok"] is True and geo_ok["distancia_m"] < 40 and geo_ok["tolerancia_m"] == 100.0

        def falla(sid):
            raise RuntimeError("sin base")

        monkeypatch.setattr(repo, "get_by_id", falla)
        assert rutas._geo_ref_actual_de_sucursal(qr) == qr  # si no se puede consultar, queda lo del QR


# --- Correccion de fichadas anteriores --------------------------------------------------------------------------

@pytest.fixture
def corr(database, monkeypatch):  # noqa: F811
    conn = database()
    c = conn.cursor()
    for sql in [
        "ALTER TABLE sucursales ADD COLUMN empresa_id INT NOT NULL DEFAULT 1",
        "ALTER TABLE sucursales ADD COLUMN latitud DECIMAL(10,7) NULL",
        "ALTER TABLE sucursales ADD COLUMN longitud DECIMAL(10,7) NULL",
        "ALTER TABLE sucursales ADD COLUMN radio_permitido_m INT NULL",
        f"UPDATE sucursales SET latitud = {COSTA[0]}, longitud = {COSTA[1]}, radio_permitido_m = 100 WHERE id = 1",
        "CREATE TABLE IF NOT EXISTS usuarios (id INT PRIMARY KEY, usuario VARCHAR(60))",
        "INSERT INTO usuarios VALUES (99, 'admin')",
        "CREATE TABLE qr_puerta_historial (id BIGINT AUTO_INCREMENT PRIMARY KEY, sucursal_id INT, geo_lat DECIMAL(10,7),"
        " geo_lon DECIMAL(10,7), tolerancia_m INT, fecha DATETIME, expira_at DATETIME, activo TINYINT DEFAULT 1)",
        f"INSERT INTO qr_puerta_historial (sucursal_id, geo_lat, geo_lon, tolerancia_m, fecha, expira_at) VALUES"
        f" (1, {DOLORES[0]}, {DOLORES[1]}, 30, '2026-06-01', '2027-06-01'), (2, {OTRA[0]}, {OTRA[1]}, 30, '2026-06-01', '2027-06-01')",
        "CREATE TABLE asistencias (id INT AUTO_INCREMENT PRIMARY KEY, empresa_id INT, empleado_id INT, fecha DATE,"
        " hora_entrada TIME NULL, hora_salida TIME NULL, gps_ok_entrada TINYINT NULL, gps_distancia_entrada_m DECIMAL(10,2) NULL,"
        " gps_tolerancia_entrada_m DECIMAL(10,2) NULL, gps_ref_lat_entrada DECIMAL(10,7) NULL, gps_ref_lon_entrada DECIMAL(10,7) NULL,"
        " gps_ok_salida TINYINT NULL, gps_distancia_salida_m DECIMAL(10,2) NULL, gps_tolerancia_salida_m DECIMAL(10,2) NULL,"
        " gps_ref_lat_salida DECIMAL(10,7) NULL, gps_ref_lon_salida DECIMAL(10,7) NULL)",
        "CREATE TABLE asistencia_marcas (id BIGINT AUTO_INCREMENT PRIMARY KEY, empresa_id INT, empleado_id INT, asistencia_id INT,"
        " fecha DATE, hora TIME, accion VARCHAR(10), lat DECIMAL(10,7) NULL, lon DECIMAL(10,7) NULL, gps_ok TINYINT NULL,"
        " gps_distancia_m DECIMAL(10,2) NULL, gps_tolerancia_m DECIMAL(10,2) NULL, gps_ref_lat DECIMAL(10,7) NULL,"
        " gps_ref_lon DECIMAL(10,7) NULL, observaciones VARCHAR(500) NULL)",
        "CREATE TABLE eventos_seguridad (id BIGINT AUTO_INCREMENT PRIMARY KEY, empleado_id INT, empresa_id INT,"
        " tipo_evento VARCHAR(50), fecha_operacion DATE, hora_operacion TIME, alerta_fraude TINYINT DEFAULT 1, payload_json JSON NULL)",
        f"INSERT INTO asistencias (id, empresa_id, empleado_id, fecha, hora_entrada, hora_salida, gps_ok_entrada, gps_ok_salida)"
        f" VALUES (1, 1, 10, '2026-10-15', '08:02', '17:01', 0, 0)",
        # Dos fichadas del 10 en la costa validadas contra Dolores (fuera), una vieja fuera del periodo, una del 11 en
        # otro lugar (sigue fuera) y una del 12 validada contra el QR de otra sucursal (no se toca).
        f"INSERT INTO asistencia_marcas (empresa_id, empleado_id, asistencia_id, fecha, hora, accion, lat, lon, gps_ok,"
        f" gps_distancia_m, gps_tolerancia_m, gps_ref_lat, gps_ref_lon, observaciones) VALUES"
        f" (1, 10, 1, '2026-10-15', '08:02', 'ingreso', {COSTA[0] + 0.0002}, {COSTA[1]}, 0, 99483, 30, {DOLORES[0]}, {DOLORES[1]}, 'gps_ok=0;alerta_fraude=1'),"
        f" (1, 10, 1, '2026-10-15', '17:01', 'egreso', {COSTA[0]}, {COSTA[1] + 0.0003}, 0, 99480, 30, {DOLORES[0]}, {DOLORES[1]}, NULL),"
        f" (1, 10, NULL, '2026-01-10', '08:00', 'ingreso', {COSTA[0]}, {COSTA[1]}, 0, 99483, 30, {DOLORES[0]}, {DOLORES[1]}, NULL),"
        f" (1, 11, NULL, '2026-10-16', '08:00', 'ingreso', -34.6, -58.4, 0, 250000, 30, {DOLORES[0]}, {DOLORES[1]}, NULL),"
        f" (1, 12, NULL, '2026-10-16', '08:00', 'ingreso', {OTRA[0]}, {OTRA[1]}, 1, 5, 30, {OTRA[0]}, {OTRA[1]}, NULL)",
        "INSERT INTO eventos_seguridad (empleado_id, empresa_id, tipo_evento, fecha_operacion, hora_operacion) VALUES"
        " (10, 1, 'qr_geo_fuera_rango', '2026-10-15', '08:02'), (11, 1, 'qr_geo_fuera_rango', '2026-10-16', '08:00')",
    ]:
        c.execute(sql)
    from scripts.migrate_20261020_01_geo_correcciones import migrate_cursor
    migrate_cursor(c)
    migrate_cursor(c)  # idempotente
    conn.commit()
    c.close()
    conn.close()
    monkeypatch.setattr(geo, "now_local", lambda: dt.datetime(2026, 10, 20, 10, 0))
    return database


def _sucursal():
    with geo.db.transaction(read_only=True) as c:
        return geo.db.one(c, "SELECT * FROM sucursales WHERE id = 1")


def _filas(sql, args=()):
    with geo.db.transaction(read_only=True) as c:
        return geo.db.all_rows(c, sql, args)


def test_vista_previa_y_correccion_con_traza(corr):
    vista = geo.vista_correccion(_sucursal(), "2026-07-01", "2026-10-20")
    assert (vista["total"], vista["fuera_antes"], vista["dentro_despues"], vista["pasan_a_dentro"], vista["quedan_fuera"]) == (3, 3, 2, 2, 1)
    with pytest.raises(geo.CorreccionError, match="motivo"):
        geo.corregir(dict(user_id=99), _sucursal(), "2026-07-01", "2026-10-20", " ")
    resultado = geo.corregir(dict(user_id=99), _sucursal(), "2026-07-01", "2026-10-20", "Coordenadas mal cargadas")
    assert (resultado["corregidas"], resultado["pasan_a_dentro"], resultado["eventos_anulados"]) == (3, 2, 1)
    marcas = {(m["empleado_id"], str(m["hora"]), str(m["fecha"])): m for m in _filas("SELECT * FROM asistencia_marcas")}
    ingreso = marcas[(10, "8:02:00", "2026-10-15")]
    assert ingreso["gps_ok"] == 1 and float(ingreso["gps_distancia_m"]) < 40 and float(ingreso["gps_tolerancia_m"]) == 100
    assert (float(ingreso["gps_ref_lat"]), float(ingreso["gps_ref_lon"])) == COSTA
    assert ingreso["observaciones"].startswith("gps_ok=0;alerta_fraude=1 | geo corregido 20/10/2026: gps_ok=1")
    assert marcas[(11, "8:00:00", "2026-10-16")]["gps_ok"] == 0  # estaba en otro lugar: sigue fuera (recalculado)
    assert marcas[(10, "8:00:00", "2026-01-10")]["gps_ok"] == 0  # fuera del periodo: no se toca
    assert marcas[(12, "8:00:00", "2026-10-16")]["gps_distancia_m"] == 5  # QR de otra sucursal: no se toca
    resumen = _filas("SELECT * FROM asistencias WHERE id = 1")[0]
    assert (resumen["gps_ok_entrada"], resumen["gps_ok_salida"]) == (1, 1)
    eventos = {e["empleado_id"]: e for e in _filas("SELECT * FROM eventos_seguridad")}
    assert eventos[10]["alerta_fraude"] == 0 and "corregida" in eventos[10]["payload_json"]
    assert eventos[11]["alerta_fraude"] == 1  # sigue fuera: el evento queda
    traza = _filas("SELECT * FROM asistencia_marcas_geo_correcciones ORDER BY marca_id")
    assert len(traza) == 3 and {t["lote"] for t in traza} == {resultado["lote"]}
    assert traza[0]["antes_gps_ok"] == 0 and float(traza[0]["antes_distancia_m"]) == 99483 and traza[0]["despues_gps_ok"] == 1
    assert traza[0]["evento_anulado_id"] == eventos[10]["id"] and traza[0]["usuario_id"] == 99
    # Repetir no cambia nada: ya estan validadas contra la ubicacion actual.
    assert geo.vista_correccion(_sucursal(), "2026-07-01", "2026-10-20")["total"] == 0
    assert geo.corregir(dict(user_id=99), _sucursal(), "2026-07-01", "2026-10-20", "otra vez")["corregidas"] == 0
    historial = geo.correcciones(1)
    assert len(historial) == 1 and historial[0]["marcas"] == 3 and int(historial[0]["pasaron_a_dentro"]) == 2
    with pytest.raises(geo.CorreccionError, match="máximo"):
        geo.vista_correccion(_sucursal(), "2025-01-01", "2026-10-20")


def test_ruta_corregir_fichadas(corr, monkeypatch):
    import web.auth.decorators as auth
    from web.sucursales import sucursales_routes as rutas

    app = Flask(__name__, template_folder=str(Path(__file__).resolve().parents[1] / "templates"))
    app.secret_key = "test"
    app.register_blueprint(rutas.sucursales_bp)
    monkeypatch.setattr(auth, "_cached_web_user", lambda uid: dict(id=99, activo=1, rol="admin", empresa_id=1))
    monkeypatch.setattr(rutas, "get_by_id", lambda sid: _sucursal() if sid == 1 else None)
    monkeypatch.setattr(rutas, "log_audit", lambda *a, **k: None)
    app.jinja_env.globals.update(csp_nonce=lambda: "n", csrf_token=lambda: "t", can_web=lambda code, action="ver": code == "qr_puerta",
                                 export_toolbar={"enabled": False, "items": []})
    monkeypatch.setattr(rutas, "get_empresas", lambda **kw: [dict(id=1, razon_social="Empresa")])
    client = app.test_client()
    with client.session_transaction() as sess:
        sess["user_id"] = 99
    pagina = client.get("/sucursales/editar/1?corr_desde=2026-07-01&corr_hasta=2026-10-20").get_data(as_text=True)
    assert "Fichadas validadas contra una ubicación anterior" in pagina and "Corregir 3 fichadas" in pagina
    assert "2 dentro" in pagina
    r = client.post("/sucursales/1/corregir-fichadas", data={"desde": "2026-07-01", "hasta": "2026-10-20", "motivo": ""})
    assert r.status_code == 302 and _filas("SELECT COUNT(*) AS n FROM asistencia_marcas_geo_correcciones")[0]["n"] == 0
    r = client.post("/sucursales/1/corregir-fichadas", data={"desde": "2026-07-01", "hasta": "2026-10-20", "motivo": "Mal cargadas"})
    assert r.status_code == 302 and "/sucursales/editar/1" in r.headers["Location"]
    assert _filas("SELECT COUNT(*) AS n FROM asistencia_marcas_geo_correcciones")[0]["n"] == 3
    with client.session_transaction() as sess:
        mensajes = [m for _, m in sess.get("_flashes", [])]
    assert any("Fichadas corregidas: 3" in m and "Pasaron a dentro del radio: 2" in m for m in mensajes)
    assert client.post("/sucursales/9/corregir-fichadas", data={"motivo": "x"}).status_code == 404
    pagina = client.get("/sucursales/editar/1?corr_desde=2026-07-01&corr_hasta=2026-10-20").get_data(as_text=True)
    assert "No hay fichadas validadas contra otra ubicación" in pagina and "Correcciones hechas (1)" in pagina
