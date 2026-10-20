"""Mapa de fichadas (panel, solo lectura): filtros, aislamiento por empresa, referencias, escape de datos y permisos.

MySQL real (SH_TEST_DB_PORT), como el resto de los modulos con base."""
import datetime as dt
import json
from pathlib import Path

import pytest
from flask import Flask

from services import mapa_fichadas_service as mapa
from tests.test_seguridad import database  # noqa: F401  (fixture)

D = dt.date


@pytest.fixture
def mf(database, monkeypatch):  # noqa: F811
    """Sucursal 1 (Central) con coordenadas y radio de 100 m. Marcas del empleado 10 dentro y fuera del radio, una
    sin ubicacion, una con nombre que intenta inyectar HTML y una de la empresa 2."""
    conn = database()
    c = conn.cursor()
    for sql in [
        "ALTER TABLE sucursales ADD COLUMN empresa_id INT NOT NULL DEFAULT 1",
        "ALTER TABLE sucursales ADD COLUMN latitud DECIMAL(10,7) NULL",
        "ALTER TABLE sucursales ADD COLUMN longitud DECIMAL(10,7) NULL",
        "ALTER TABLE sucursales ADD COLUMN radio_permitido_m INT NULL",
        "UPDATE sucursales SET empresa_id = 2 WHERE id = 3",
        "UPDATE sucursales SET latitud = -34.6037, longitud = -58.3816, radio_permitido_m = 100 WHERE id = 1",
        "UPDATE empleados SET nombre = '<b>Luis</b>' WHERE id = 11",
        "CREATE TABLE asistencia_marcas (id BIGINT AUTO_INCREMENT PRIMARY KEY, empresa_id INT, empleado_id INT, fecha DATE,"
        " hora TIME, accion VARCHAR(10), metodo VARCHAR(20), lat DECIMAL(10,7) NULL, lon DECIMAL(10,7) NULL, gps_ok TINYINT NULL,"
        " gps_distancia_m DECIMAL(10,2) NULL, gps_tolerancia_m DECIMAL(10,2) NULL, gps_ref_lat DECIMAL(10,7) NULL,"
        " gps_ref_lon DECIMAL(10,7) NULL)",
    ]:
        c.execute(sql)
    from scripts.migrate_20261019_05_gps_calidad import migrate_cursor
    migrate_cursor(c)
    migrate_cursor(c)  # idempotente
    for sql in [
        "INSERT INTO asistencia_marcas (empresa_id, empleado_id, fecha, hora, accion, metodo, lat, lon, gps_ok, gps_distancia_m,"
        " gps_tolerancia_m, gps_ref_lat, gps_ref_lon) VALUES"
        " (1, 10, '2026-10-15', '08:02', 'ingreso', 'qr', -34.6038, -58.3817, 1, 14, 100, -34.6037, -58.3816),"
        " (1, 10, '2026-10-15', '17:01', 'egreso', 'qr', -34.6200, -58.4000, 0, 2450, 100, -34.6037, -58.3816),"
        " (1, 10, '2026-10-16', '08:00', 'ingreso', 'manual', NULL, NULL, NULL, NULL, NULL, NULL, NULL),"
        " (1, 11, '2026-10-16', '08:10', 'ingreso', 'qr', -34.5500, -58.4500, 0, 9000, 50, -34.5600, -58.4400),"
        " (2, 20, '2026-10-15', '08:00', 'ingreso', 'qr', -31.4, -64.18, 1, 5, 100, -31.4, -64.18)",
        # Calidad del GPS (app 1.54.0): el ingreso del 10 con buena precision; el 11 con GPS simulado; una posicion vieja.
        "UPDATE asistencia_marcas SET gps_precision_m = 14.6, gps_simulada = 0, gps_edad_s = 2 WHERE empleado_id = 10 AND hora = '08:02'",
        "UPDATE asistencia_marcas SET gps_precision_m = 5, gps_simulada = 1, gps_edad_s = 1 WHERE empleado_id = 11",
        "INSERT INTO asistencia_marcas (empresa_id, empleado_id, fecha, hora, accion, metodo, lat, lon, gps_ok, gps_distancia_m,"
        " gps_tolerancia_m, gps_ref_lat, gps_ref_lon, gps_precision_m, gps_simulada, gps_edad_s) VALUES"
        " (1, 10, '2026-10-17', '08:00', 'ingreso', 'qr', -34.6037, -58.3816, 1, 3, 100, -34.6037, -58.3816, 40, 0, 600)",
    ]:
        c.execute(sql)
    conn.commit()
    c.close()
    conn.close()
    monkeypatch.setattr(mapa, "now_local", lambda: dt.datetime(2026, 10, 19, 10, 0))
    return database


def test_fichadas_filtros_y_referencias(mf):
    datos = mapa.fichadas(1, D(2026, 10, 13), D(2026, 10, 19))
    assert datos["totales"] == dict(total=5, con_ubicacion=4, sin_ubicacion=1, fuera=2, dentro=2, simuladas=1, viejas=1,
                                    con_precision=3)
    # Primero las que tienen alguna alerta (fuera de radio, GPS simulado o posicion vieja).
    assert [p["alertas"] for p in datos["puntos"]] == [
        ["Posición de hace 10 min"], ["Fuera del radio", "GPS simulado"], ["Fuera del radio"], []]
    ingreso = datos["puntos"][-1]
    assert (ingreso["precision"], ingreso["simulada"], ingreso["edad"]) == (15, False, 2)
    egreso = next(p for p in datos["puntos"] if p["accion"] == "egreso")
    assert (egreso["hora"], egreso["distancia"], egreso["tolerancia"], egreso["ref"]) == ("17:01", 2450, 100, [-34.6037, -58.3816])
    # La sucursal con su radio y el punto de validacion (QR) que no es una sucursal.
    assert [(r["nombre"], r["radio"], r["tipo"]) for r in datos["referencias"]] == [
        ("Central", 100, "sucursal"), ("Punto de validación", 50, "qr")]
    assert len(mapa.fichadas(1, D(2026, 10, 13), D(2026, 10, 19), {"ver": "fuera"})["puntos"]) == 2
    assert len(mapa.fichadas(1, D(2026, 10, 13), D(2026, 10, 19), {"ver": "alertas"})["puntos"]) == 3
    assert len(mapa.fichadas(1, D(2026, 10, 13), D(2026, 10, 19), {"empleado_id": "10", "accion": "ingreso"})["puntos"]) == 2
    assert mapa.fichadas(1, D(2026, 10, 13), D(2026, 10, 19), {"sucursal_id": "2"})["totales"]["total"] == 0
    assert mapa.fichadas(2, D(2026, 10, 13), D(2026, 10, 19))["totales"]["total"] == 1  # cada empresa lo suyo


def test_periodo_por_defecto_y_maximo():
    assert mapa.periodo({}) != ()  # sin base: solo valida fechas
    with pytest.raises(mapa.Error, match="máximo"):
        mapa.periodo({"desde": "2026-01-01", "hasta": "2026-03-01"})
    with pytest.raises(mapa.Error, match="posterior"):
        mapa.periodo({"desde": "2026-10-10", "hasta": "2026-10-01"})


@pytest.fixture
def client(mf, monkeypatch):
    import web.auth.decorators as auth
    from web.mapa_fichadas import routes

    app = Flask(__name__, template_folder=str(Path(__file__).resolve().parents[1] / "templates"))
    app.secret_key = "test"
    app.config["TESTING"] = True
    app.register_blueprint(routes.web)
    permisos = {"acciones": {"ver"}}

    def can_web(code, action="ver"):
        return code == "mapa_fichadas" and action in permisos["acciones"]

    app.jinja_env.globals.update(csp_nonce=lambda: "n", csrf_token=lambda: "t", can_web=can_web,
                                 export_toolbar={"enabled": False, "items": []})
    monkeypatch.setattr(auth, "can_access_module", lambda uid, module, action="ver": can_web(module, action))
    monkeypatch.setattr(routes, "_cached_web_user", lambda uid: dict(id=99, empresa_id=1, activo=1))
    test_client = app.test_client()
    with test_client.session_transaction() as sess:
        sess["user_id"] = 99
    test_client.permisos = permisos
    return test_client


def test_pantalla_datos_escapados_y_permisos(client):
    pagina = client.get("/mapa-fichadas/?desde=2026-10-13&hasta=2026-10-19").get_data(as_text=True)
    assert "Mapa de fichadas" in pagina and "vendor/leaflet/leaflet.js" in pagina and "js/mapa-fichadas.js" in pagina
    assert "<b>Luis</b>" not in pagina  # el nombre se escapa en la lista y en el JSON
    bloque = pagina.split('<script type="application/json" id="mf-datos">', 1)[1].split("</script>", 1)[0]
    datos = json.loads(bloque)
    assert "GPS simulado" in pagina and "±15&nbsp;m" in pagina
    assert len(datos["puntos"]) == 4 and "<b>Luis</b>" in {p["empleado"].split(", ")[1] for p in datos["puntos"]}
    r = client.get("/mapa-fichadas/?desde=2026-01-01&hasta=2026-06-30")
    assert r.status_code == 302  # periodo invalido: vuelve con el aviso
    client.permisos["acciones"] = set()
    assert client.get("/mapa-fichadas/").status_code == 403
