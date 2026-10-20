"""Geolocalizacion de sucursales en el panel: sugerencia desde las fichadas, QR desactualizados y el mapa del formulario.

MySQL real (SH_TEST_DB_PORT) para el servicio; el formulario se prueba con los repositorios simulados."""
import datetime as dt
import json
from pathlib import Path

import pytest
from flask import Flask

from services import sucursal_geo_service as geo
from tests.test_seguridad import database  # noqa: F401  (fixture)

COSTA = (-36.7212921, -56.6776091)  # donde fichan de verdad
CARGADA = (-36.3226892, -57.6801836)  # la ubicacion cargada (calle Chascomus 588, Dolores)


@pytest.fixture
def geo_db(database, monkeypatch):  # noqa: F811
    conn = database()
    c = conn.cursor()
    for sql in [
        "CREATE TABLE asistencia_marcas (id BIGINT AUTO_INCREMENT PRIMARY KEY, empresa_id INT, empleado_id INT, fecha DATE,"
        " hora TIME, accion VARCHAR(10), lat DECIMAL(10,7) NULL, lon DECIMAL(10,7) NULL)",
        "CREATE TABLE qr_puerta_historial (id BIGINT AUTO_INCREMENT PRIMARY KEY, sucursal_id INT, geo_lat DECIMAL(10,7),"
        " geo_lon DECIMAL(10,7), tolerancia_m INT, fecha DATETIME, expira_at DATETIME, activo TINYINT DEFAULT 1)",
    ]:
        c.execute(sql)
    # Sucursal 1: empleados 10, 11 y 13. Ocho fichadas cerca de la costa (unos metros de diferencia), una desde otro
    # lugar, una vieja (fuera de los 30 dias) y una sin GPS. El 12 es de otra sucursal.
    filas = [(10, "2026-10-15", COSTA[0] + d, COSTA[1] + d) for d in (0, 0.0001, -0.0001, 0.0002, 0.00005, -0.00015, 0.0001, 0)]
    filas += [(11, "2026-10-16", -34.6037, -58.3816), (13, "2026-08-01", -31.4, -64.18), (11, "2026-10-17", None, None),
              (12, "2026-10-15", -35.57, -57.97)]
    for eid, fecha, lat, lon in filas:
        c.execute("INSERT INTO asistencia_marcas (empresa_id, empleado_id, fecha, hora, accion, lat, lon) VALUES"
                  " (1, %s, %s, '08:00', 'ingreso', %s, %s)", (eid, fecha, lat, lon))
    c.execute("INSERT INTO qr_puerta_historial (sucursal_id, geo_lat, geo_lon, tolerancia_m, fecha, expira_at, activo) VALUES"
              " (1, %s, %s, 30, '2026-06-01 10:00', '2027-06-01', 1), (1, %s, %s, 30, '2026-10-18 10:00', '2027-10-18', 1),"
              " (1, %s, %s, 30, '2026-01-01 10:00', '2027-01-01', 0)", (*CARGADA, *COSTA, *CARGADA))
    conn.commit()
    c.close()
    conn.close()
    monkeypatch.setattr(geo, "now_local", lambda: dt.datetime(2026, 10, 19, 10, 0))
    return database


def test_sugerencia_desde_las_fichadas_y_qr_desactualizados(geo_db):
    datos = geo.contexto(dict(id=1, latitud=COSTA[0], longitud=COSTA[1]))
    s = datos["sugerencia"]
    assert s["fichadas"] == 9  # solo las de la sucursal, con GPS y de los ultimos 30 dias
    assert geo.distancia_m(s["lat"], s["lon"], *COSTA) < 15  # la fichada desde otro lugar no la mueve
    assert s["cerca"] == 8 and s["mitad_m"] < 15 and s["distancia_actual_m"] < 15
    assert [(q["desactualizado"], q["distancia_m"] > 90000) for q in datos["qrs"]] == [(False, False), (True, True)]
    assert len(datos["mapa"]["puntos"]) == 9 and datos["mapa"]["qrs"][1]["desactualizado"] is True
    # Con la ubicacion vieja cargada, la sugerencia queda a unos 99,5 km.
    vieja = geo.contexto(dict(id=1, latitud=CARGADA[0], longitud=CARGADA[1]))
    assert 99000 < vieja["sugerencia"]["distancia_actual_m"] < 100000


def test_sin_fichadas_suficientes_no_sugiere(geo_db):
    datos = geo.contexto(dict(id=2, latitud=None, longitud=None))
    assert datos["sugerencia"] is None and datos["qrs"] == [] and len(datos["mapa"]["puntos"]) == 1  # el 12, una sola


def test_formulario_con_mapa_y_aviso_de_qr(monkeypatch):
    import web.auth.decorators as auth
    from web.sucursales import sucursales_routes as rutas

    app = Flask(__name__, template_folder=str(Path(__file__).resolve().parents[1] / "templates"))
    app.secret_key = "test"
    app.register_blueprint(rutas.sucursales_bp)
    app.jinja_env.globals.update(csp_nonce=lambda: "n", csrf_token=lambda: "t", can_web=lambda code, action="ver": code == "qr_puerta",
                                 export_toolbar={"enabled": False, "items": []})
    monkeypatch.setattr(auth, "_cached_web_user", lambda uid: dict(id=1, activo=1, rol="admin", empresa_id=1))
    monkeypatch.setattr(rutas, "get_by_id", lambda sid: dict(id=sid, empresa_id=1, nombre="Casa Central", direccion="",
                                                              latitud=CARGADA[0], longitud=CARGADA[1], radio_permitido_m=30, activa=1))
    monkeypatch.setattr(rutas, "get_empresas", lambda **kw: [dict(id=1, razon_social="Empresa")])
    monkeypatch.setattr(rutas.geo, "contexto", lambda suc: dict(
        sugerencia=dict(lat=COSTA[0], lon=COSTA[1], fichadas=9, dias=30, mitad_m=8, cerca=8, cerca_m=150, distancia_actual_m=99483),
        qrs=[dict(id=1, lat=CARGADA[0], lon=CARGADA[1], tolerancia=30, fecha=dt.datetime(2026, 6, 1), expira=None,
                  distancia_m=99483, desactualizado=True)],
        mapa=dict(sugerencia=None, puntos=[[COSTA[0], COSTA[1], "ingreso"]], qrs=[])))
    client = app.test_client()
    with client.session_transaction() as sess:
        sess["user_id"] = 1
    pagina = client.get("/sucursales/editar/1").get_data(as_text=True)
    assert "Usar la ubicación de las fichadas" in pagina and "99.483 m" in pagina and "desactualizado" in pagina
    assert 'id="su-lat"' in pagina and "js/sucursal-mapa.js" in pagina and "js/mapa-base.js" in pagina
    assert 'id="su-buscar"' in pagina and "/sucursales/geocodificar" in pagina
    datos = json.loads(pagina.split('<script type="application/json" id="su-datos">', 1)[1].split("</script>", 1)[0])
    assert datos["puntos"] == [[COSTA[0], COSTA[1], "ingreso"]]
    # Si el contexto falla, el formulario igual se muestra (sin mapa de fichadas).
    monkeypatch.setattr(rutas.geo, "contexto", lambda suc: 1 / 0)
    assert client.get("/sucursales/editar/1").status_code == 200


# --- Buscador de direcciones (sin red: OpenStreetMap simulado) ---------------------------------------------------

class _Respuesta:
    def __init__(self, cuerpo):
        self.cuerpo = cuerpo

    def read(self):
        return json.dumps(self.cuerpo).encode()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


def test_buscar_direccion_cachea_y_maneja_errores(monkeypatch):
    from services import geocodificacion_service as gc

    pedidos = []

    def urlopen(pedido, timeout):
        pedidos.append(pedido)
        return _Respuesta([{"display_name": "Cacique Sayueque, Chascomús, Buenos Aires", "lat": "-35.5752720", "lon": "-57.9786980"},
                           {"display_name": "sin coordenadas"}])

    monkeypatch.setattr(gc.urllib.request, "urlopen", urlopen)
    monkeypatch.setattr(gc, "_cache", {})
    monkeypatch.setattr(gc.time, "sleep", lambda s: None)
    with pytest.raises(gc.Error, match="al menos 4"):
        gc.buscar("ab")
    resultados = gc.buscar("Cacique Sayueque, Chascomús")
    assert resultados == [dict(nombre="Cacique Sayueque, Chascomús, Buenos Aires", lat=-35.575272, lon=-57.978698)]
    assert gc.buscar("  cacique   sayueque, CHASCOMÚS ") == resultados and len(pedidos) == 1  # cache
    url = pedidos[0].full_url
    assert "countrycodes=ar" in url and pedidos[0].get_header("User-agent").startswith("FichaYa")

    def falla(pedido, timeout):
        raise OSError("sin red")

    monkeypatch.setattr(gc.urllib.request, "urlopen", falla)
    with pytest.raises(gc.Error, match="No se pudo consultar") as error:
        gc.buscar("Belgrano 123, Dolores")
    assert error.value.status == 502


def test_ruta_geocodificar(monkeypatch):
    import web.auth.decorators as auth
    from web.sucursales import sucursales_routes as rutas

    app = Flask(__name__)
    app.secret_key = "test"
    app.register_blueprint(rutas.sucursales_bp)
    monkeypatch.setattr(auth, "_cached_web_user", lambda uid: dict(id=1, activo=1, rol="admin", empresa_id=1))
    monkeypatch.setattr(rutas.geocodificacion, "buscar", lambda q: [dict(nombre=q, lat=-36.3, lon=-57.6)])
    client = app.test_client()
    with client.session_transaction() as sess:
        sess["user_id"] = 1
    assert client.get("/sucursales/geocodificar?q=Dolores").get_json() == {"resultados": [{"nombre": "Dolores", "lat": -36.3, "lon": -57.6}]}

    def corta(q):
        raise rutas.geocodificacion.Error("Escribí al menos 4 letras de la dirección.")

    monkeypatch.setattr(rutas.geocodificacion, "buscar", corta)
    r = client.get("/sucursales/geocodificar?q=ab")
    assert r.status_code == 400 and "4 letras" in r.get_json()["error"]
    monkeypatch.setattr(auth, "_cached_web_user", lambda uid: dict(id=1, activo=1, rol="rrhh", empresa_id=1))
    monkeypatch.setattr(auth, "can_access_module", lambda *a, **k: False)
    assert client.get("/sucursales/geocodificar?q=Dolores").status_code == 403
