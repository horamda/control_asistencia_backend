import datetime
import io

import app as app_module
import utils.jwt_guard as jwt_guard
import routes.mobile_v1_routes as mobile_routes


def _build_client(monkeypatch):
    monkeypatch.setattr(app_module, "init_db", lambda: None)
    app = app_module.create_app()
    app.config["TESTING"] = True
    app.config["WTF_CSRF_ENABLED"] = False
    return app.test_client()


def test_mobile_login_requires_dni_password(monkeypatch):
    client = _build_client(monkeypatch)
    resp = client.post("/api/v1/mobile/auth/login", json={})
    assert resp.status_code == 400
    assert "dni y password" in resp.get_json()["error"]


def test_mobile_login_ok(monkeypatch):
    client = _build_client(monkeypatch)
    monkeypatch.setattr(
        mobile_routes,
        "authenticate_user",
        lambda dni, password: (
            {
                "id": 10,
                "dni": dni,
                "nombre": "Ana",
                "apellido": "Lopez",
                "empresa_id": 3,
                "foto": "https://cdn.example.com/fotos/123.jpg",
            },
            None,
        ),
    )
    monkeypatch.setattr(mobile_routes, "generar_token", lambda payload: "token-demo")

    resp = client.post("/api/v1/mobile/auth/login", json={"dni": "123", "password": "x"})
    body = resp.get_json()
    assert resp.status_code == 200
    assert body["token"] == "token-demo"
    assert body["empleado"]["id"] == 10
    assert body["empleado"]["foto"] == "https://cdn.example.com/fotos/123.jpg"


def test_mobile_me_requires_bearer(monkeypatch):
    client = _build_client(monkeypatch)
    resp = client.get("/api/v1/mobile/me")
    assert resp.status_code == 401
    assert "Bearer" in resp.get_json()["error"]


def test_mobile_me_ok(monkeypatch):
    client = _build_client(monkeypatch)
    monkeypatch.setattr(jwt_guard, "verificar_token", lambda token: {"empleado_id": 10})
    monkeypatch.setattr(
        mobile_routes,
        "get_empleado_by_id",
        lambda empleado_id: {
            "id": empleado_id,
            "activo": 1,
            "empresa_id": 3,
            "dni": "123",
            "nombre": "Ana",
            "apellido": "Lopez",
            "email": "ana@test.com",
            "telefono": "123",
            "direccion": "X",
            "foto": None,
            "estado": "activo",
            "sucursal_id": None,
            "sector_id": None,
            "puesto_id": None,
            "legajo": "L1",
        },
    )

    resp = client.get("/api/v1/mobile/me", headers={"Authorization": "Bearer abc"})
    assert resp.status_code == 200
    assert resp.get_json()["id"] == 10


def test_mobile_fichada_entrada_requiere_qr(monkeypatch):
    client = _build_client(monkeypatch)
    monkeypatch.setattr(jwt_guard, "verificar_token", lambda token: {"empleado_id": 5})
    monkeypatch.setattr(
        mobile_routes,
        "get_empleado_by_id",
        lambda empleado_id: {
            "id": empleado_id,
            "activo": 1,
            "empresa_id": 1,
            "dni": "1",
            "nombre": "Emp",
            "apellido": "One",
            "password_hash": "x",
        },
    )
    monkeypatch.setattr(
        mobile_routes,
        "get_by_empresa_id",
        lambda empresa_id: {
            "requiere_qr": 1,
            "requiere_foto": 0,
            "requiere_geo": 0,
        },
    )

    resp = client.post(
        "/api/v1/mobile/me/fichadas/entrada",
        headers={"Authorization": "Bearer abc"},
        json={"metodo": "manual"},
    )
    assert resp.status_code == 400
    assert "requiere metodo QR" in resp.get_json()["error"]


def test_mobile_generar_qr_ok(monkeypatch):
    client = _build_client(monkeypatch)
    monkeypatch.setattr(jwt_guard, "verificar_token", lambda token: {"empleado_id": 8})
    monkeypatch.setattr(
        mobile_routes,
        "get_empleado_by_id",
        lambda empleado_id: {
            "id": empleado_id,
            "activo": 1,
            "empresa_id": 2,
            "dni": "2",
            "nombre": "Emp",
            "apellido": "Two",
        },
    )
    monkeypatch.setattr(
        mobile_routes,
        "generar_token_qr",
        lambda payload, vigencia_segundos=120: "qr-token-demo",
    )
    monkeypatch.setattr(
        mobile_routes,
        "build_qr_png_base64",
        lambda content: "data:image/png;base64,AAA",
    )

    resp = client.post(
        "/api/v1/mobile/me/qr",
        headers={"Authorization": "Bearer abc"},
        json={"accion": "ingreso", "scope": "empresa", "vigencia_segundos": 120},
    )
    body = resp.get_json()
    assert resp.status_code == 200
    assert body["qr_token"] == "qr-token-demo"
    assert body["accion"] == "ingreso"


def test_mobile_fichada_entrada_qr_token_requerido(monkeypatch):
    client = _build_client(monkeypatch)
    monkeypatch.setattr(jwt_guard, "verificar_token", lambda token: {"empleado_id": 5})
    monkeypatch.setattr(
        mobile_routes,
        "get_empleado_by_id",
        lambda empleado_id: {
            "id": empleado_id,
            "activo": 1,
            "empresa_id": 1,
            "dni": "1",
            "nombre": "Emp",
            "apellido": "One",
            "password_hash": "x",
        },
    )
    monkeypatch.setattr(
        mobile_routes,
        "get_by_empresa_id",
        lambda empresa_id: {
            "requiere_qr": 0,
            "requiere_foto": 0,
            "requiere_geo": 0,
        },
    )

    resp = client.post(
        "/api/v1/mobile/me/fichadas/entrada",
        headers={"Authorization": "Bearer abc"},
        json={"metodo": "qr", "lat": -34.6037, "lon": -58.3816},
    )
    assert resp.status_code == 400
    assert "qr_token requerido" in resp.get_json()["error"]


def test_mobile_fichada_entrada_permite_reingreso_despues_egreso(monkeypatch):
    client = _build_client(monkeypatch)
    monkeypatch.setattr(jwt_guard, "verificar_token", lambda token: {"empleado_id": 5})
    monkeypatch.setattr(
        mobile_routes,
        "get_empleado_by_id",
        lambda empleado_id: {
            "id": empleado_id,
            "activo": 1,
            "empresa_id": 1,
            "dni": "1",
            "nombre": "Emp",
            "apellido": "One",
            "password_hash": "x",
        },
    )
    monkeypatch.setattr(
        mobile_routes,
        "get_by_empresa_id",
        lambda empresa_id: {
            "requiere_qr": 0,
            "requiere_foto": 0,
            "requiere_geo": 0,
        },
    )
    monkeypatch.setattr(
        mobile_routes,
        "get_by_empleado_fecha",
        lambda empleado_id, fecha: {"id": 10, "hora_entrada": "08:00", "hora_salida": "12:00"},
    )
    monkeypatch.setattr(
        mobile_routes,
        "get_last_marca_by_empleado_fecha",
        lambda empleado_id, fecha: {"id": 900, "accion": "egreso", "hora": "12:00"},
    )
    monkeypatch.setattr(mobile_routes, "validar_asistencia", lambda *args: ({}, "ok"))
    monkeypatch.setattr(mobile_routes, "upsert_resumen_desde_marca", lambda **kwargs: 81)
    monkeypatch.setattr(mobile_routes, "create_asistencia_marca", lambda **kwargs: 901)

    resp = client.post(
        "/api/v1/mobile/me/fichadas/entrada",
        headers={"Authorization": "Bearer abc"},
        json={"metodo": "manual", "hora_entrada": "13:00"},
    )
    body = resp.get_json()
    assert resp.status_code == 201
    assert body["id"] == 81
    assert body["marca_id"] == 901
    assert body["estado"] == "ok"


def test_mobile_fichada_salida_manual_con_ingreso_abierto(monkeypatch):
    client = _build_client(monkeypatch)
    monkeypatch.setattr(jwt_guard, "verificar_token", lambda token: {"empleado_id": 5})
    monkeypatch.setattr(
        mobile_routes,
        "get_empleado_by_id",
        lambda empleado_id: {
            "id": empleado_id,
            "activo": 1,
            "empresa_id": 1,
            "dni": "1",
            "nombre": "Emp",
            "apellido": "One",
            "password_hash": "x",
        },
    )
    monkeypatch.setattr(
        mobile_routes,
        "get_by_empresa_id",
        lambda empresa_id: {
            "requiere_qr": 0,
            "requiere_foto": 0,
            "requiere_geo": 0,
        },
    )
    monkeypatch.setattr(
        mobile_routes,
        "get_by_empleado_fecha",
        lambda empleado_id, fecha: {"id": 11, "hora_entrada": "13:00", "hora_salida": None},
    )
    monkeypatch.setattr(
        mobile_routes,
        "get_last_marca_by_empleado_fecha",
        lambda empleado_id, fecha: {"id": 901, "accion": "ingreso", "hora": "13:00"},
    )
    monkeypatch.setattr(mobile_routes, "validar_asistencia", lambda *args: ({}, "ok"))
    monkeypatch.setattr(mobile_routes, "upsert_resumen_desde_marca", lambda **kwargs: 11)
    monkeypatch.setattr(mobile_routes, "create_asistencia_marca", lambda **kwargs: 902)

    resp = client.post(
        "/api/v1/mobile/me/fichadas/salida",
        headers={"Authorization": "Bearer abc"},
        json={"metodo": "manual", "hora_salida": "17:00"},
    )
    body = resp.get_json()
    assert resp.status_code == 200
    assert body["id"] == 11
    assert body["marca_id"] == 902
    assert body["estado"] == "ok"


def test_mobile_fichada_scan_qr_auto_ingreso(monkeypatch):
    client = _build_client(monkeypatch)
    monkeypatch.setattr(jwt_guard, "verificar_token", lambda token: {"empleado_id": 6})
    monkeypatch.setattr(
        mobile_routes,
        "get_empleado_by_id",
        lambda empleado_id: {
            "id": empleado_id,
            "activo": 1,
            "empresa_id": 1,
            "dni": "6",
            "nombre": "Emp",
            "apellido": "Six",
        },
    )
    monkeypatch.setattr(
        mobile_routes,
        "get_by_empresa_id",
        lambda empresa_id: {
            "requiere_qr": 1,
            "requiere_foto": 0,
            "requiere_geo": 0,
        },
    )
    monkeypatch.setattr(
        mobile_routes,
        "verificar_token_qr",
        lambda token, accion_esperada=None: {
            "type": "asistencia_qr",
            "accion": "auto",
            "empresa_id": 1,
            "scope": "empresa",
        },
    )
    monkeypatch.setattr(mobile_routes, "get_by_empleado_fecha", lambda empleado_id, fecha: None)
    monkeypatch.setattr(mobile_routes, "get_last_marca_by_empleado_fecha", lambda empleado_id, fecha: None)
    monkeypatch.setattr(
        mobile_routes,
        "_validar_geo_scan_qr",
        lambda empleado, qr_payload, lat, lon: {
            "gps_ok": True,
            "distancia_m": 12.3,
            "tolerancia_m": 80.0,
            "ref_lat": -34.0,
            "ref_lon": -58.0,
            "sucursal_id": 1,
        },
    )
    monkeypatch.setattr(mobile_routes, "validar_asistencia", lambda *args: ({}, "ok"))
    monkeypatch.setattr(mobile_routes, "upsert_resumen_desde_marca", lambda **kwargs: 77)
    monkeypatch.setattr(mobile_routes, "create_asistencia_marca", lambda **kwargs: 701)
    monkeypatch.setattr(mobile_routes, "count_marcas_by_empleado_fecha", lambda empleado_id, fecha: 1)

    resp = client.post(
        "/api/v1/mobile/me/fichadas/scan",
        headers={"Authorization": "Bearer abc"},
        json={"qr_token": "qrauto", "lat": -34.6037, "lon": -58.3816},
    )
    body = resp.get_json()
    assert resp.status_code == 201
    assert body["accion"] == "ingreso"
    assert body["id"] == 77
    assert body["marca_id"] == 701
    assert body["total_marcas_dia"] == 1
    assert body["tipo_marca"] == "jornada"
    assert body["gps_ok"] is True


def test_mobile_fichada_scan_qr_auto_egreso(monkeypatch):
    client = _build_client(monkeypatch)
    monkeypatch.setattr(jwt_guard, "verificar_token", lambda token: {"empleado_id": 6})
    monkeypatch.setattr(
        mobile_routes,
        "get_empleado_by_id",
        lambda empleado_id: {
            "id": empleado_id,
            "activo": 1,
            "empresa_id": 1,
            "dni": "6",
            "nombre": "Emp",
            "apellido": "Six",
        },
    )
    monkeypatch.setattr(
        mobile_routes,
        "get_by_empresa_id",
        lambda empresa_id: {
            "requiere_qr": 1,
            "requiere_foto": 0,
            "requiere_geo": 0,
        },
    )
    monkeypatch.setattr(
        mobile_routes,
        "verificar_token_qr",
        lambda token, accion_esperada=None: {
            "type": "asistencia_qr",
            "accion": "auto",
            "empresa_id": 1,
            "scope": "empresa",
        },
    )
    monkeypatch.setattr(
        mobile_routes,
        "get_by_empleado_fecha",
        lambda empleado_id, fecha: {
            "id": 10,
            "hora_entrada": "08:00",
            "hora_salida": None,
        },
    )
    monkeypatch.setattr(
        mobile_routes,
        "get_last_marca_by_empleado_fecha",
        lambda empleado_id, fecha: {
            "id": 501,
            "fecha": fecha,
            "hora": "08:00",
            "accion": "ingreso",
        },
    )
    monkeypatch.setattr(
        mobile_routes,
        "_validar_geo_scan_qr",
        lambda empleado, qr_payload, lat, lon: {
            "gps_ok": True,
            "distancia_m": 10.0,
            "tolerancia_m": 80.0,
            "ref_lat": -34.0,
            "ref_lon": -58.0,
            "sucursal_id": 1,
        },
    )
    monkeypatch.setattr(mobile_routes, "validar_asistencia", lambda *args: ({}, "ok"))
    monkeypatch.setattr(mobile_routes, "upsert_resumen_desde_marca", lambda **kwargs: 10)
    monkeypatch.setattr(mobile_routes, "create_asistencia_marca", lambda **kwargs: 702)
    monkeypatch.setattr(mobile_routes, "count_marcas_by_empleado_fecha", lambda empleado_id, fecha: 2)

    resp = client.post(
        "/api/v1/mobile/me/fichadas/scan",
        headers={"Authorization": "Bearer abc"},
        json={"qr_token": "qrauto", "lat": -34.6037, "lon": -58.3816},
    )
    body = resp.get_json()
    assert resp.status_code == 200
    assert body["accion"] == "egreso"
    assert body["id"] == 10
    assert body["marca_id"] == 702
    assert body["total_marcas_dia"] == 2
    assert body["tipo_marca"] == "jornada"
    assert body["gps_ok"] is True


def test_mobile_fichada_scan_qr_auto_ingreso_despues_de_egreso(monkeypatch):
    client = _build_client(monkeypatch)
    monkeypatch.setattr(jwt_guard, "verificar_token", lambda token: {"empleado_id": 6})
    monkeypatch.setattr(
        mobile_routes,
        "get_empleado_by_id",
        lambda empleado_id: {
            "id": empleado_id,
            "activo": 1,
            "empresa_id": 1,
            "dni": "6",
            "nombre": "Emp",
            "apellido": "Six",
        },
    )
    monkeypatch.setattr(
        mobile_routes,
        "get_by_empresa_id",
        lambda empresa_id: {
            "requiere_qr": 1,
            "requiere_foto": 0,
            "requiere_geo": 0,
        },
    )
    monkeypatch.setattr(
        mobile_routes,
        "verificar_token_qr",
        lambda token, accion_esperada=None: {
            "type": "asistencia_qr",
            "accion": "auto",
            "empresa_id": 1,
            "scope": "empresa",
        },
    )
    monkeypatch.setattr(
        mobile_routes,
        "get_by_empleado_fecha",
        lambda empleado_id, fecha: {
            "id": 10,
            "hora_entrada": "08:00",
            "hora_salida": "12:00",
        },
    )
    monkeypatch.setattr(
        mobile_routes,
        "get_last_marca_by_empleado_fecha",
        lambda empleado_id, fecha: {
            "id": 502,
            "fecha": fecha,
            "hora": "12:00",
            "accion": "egreso",
        },
    )
    monkeypatch.setattr(
        mobile_routes,
        "_validar_geo_scan_qr",
        lambda empleado, qr_payload, lat, lon: {
            "gps_ok": True,
            "distancia_m": 9.2,
            "tolerancia_m": 80.0,
            "ref_lat": -34.0,
            "ref_lon": -58.0,
            "sucursal_id": 1,
        },
    )
    monkeypatch.setattr(mobile_routes, "validar_asistencia", lambda *args: ({}, "ok"))
    monkeypatch.setattr(mobile_routes, "upsert_resumen_desde_marca", lambda **kwargs: 10)
    monkeypatch.setattr(mobile_routes, "create_asistencia_marca", lambda **kwargs: 703)
    monkeypatch.setattr(mobile_routes, "count_marcas_by_empleado_fecha", lambda empleado_id, fecha: 3)

    resp = client.post(
        "/api/v1/mobile/me/fichadas/scan",
        headers={"Authorization": "Bearer abc"},
        json={"qr_token": "qrauto", "lat": -34.6037, "lon": -58.3816},
    )
    body = resp.get_json()
    assert resp.status_code == 201
    assert body["accion"] == "ingreso"
    assert body["id"] == 10
    assert body["marca_id"] == 703
    assert body["total_marcas_dia"] == 3
    assert body["tipo_marca"] == "jornada"


def test_mobile_fichada_scan_qr_auto_reingreso_sin_marcas_previas(monkeypatch):
    client = _build_client(monkeypatch)
    monkeypatch.setattr(jwt_guard, "verificar_token", lambda token: {"empleado_id": 6})
    monkeypatch.setattr(
        mobile_routes,
        "get_empleado_by_id",
        lambda empleado_id: {
            "id": empleado_id,
            "activo": 1,
            "empresa_id": 1,
            "dni": "6",
            "nombre": "Emp",
            "apellido": "Six",
        },
    )
    monkeypatch.setattr(
        mobile_routes,
        "get_by_empresa_id",
        lambda empresa_id: {
            "requiere_qr": 1,
            "requiere_foto": 0,
            "requiere_geo": 0,
        },
    )
    monkeypatch.setattr(
        mobile_routes,
        "verificar_token_qr",
        lambda token, accion_esperada=None: {
            "type": "asistencia_qr",
            "accion": "auto",
            "empresa_id": 1,
            "scope": "empresa",
        },
    )
    monkeypatch.setattr(
        mobile_routes,
        "get_by_empleado_fecha",
        lambda empleado_id, fecha: {
            "id": 10,
            "hora_entrada": "07:00",
            "hora_salida": "13:00",
        },
    )
    # Caso real reportado: no hay marcas atomicas pero el resumen del dia ya se cerro.
    monkeypatch.setattr(mobile_routes, "get_last_marca_by_empleado_fecha", lambda empleado_id, fecha: None)
    monkeypatch.setattr(
        mobile_routes,
        "_validar_geo_scan_qr",
        lambda empleado, qr_payload, lat, lon: {
            "gps_ok": True,
            "distancia_m": 12.1,
            "tolerancia_m": 80.0,
            "ref_lat": -34.0,
            "ref_lon": -58.0,
            "sucursal_id": 1,
        },
    )
    monkeypatch.setattr(mobile_routes, "validar_asistencia", lambda *args: ({}, "ok"))
    monkeypatch.setattr(mobile_routes, "upsert_resumen_desde_marca", lambda **kwargs: 81)
    monkeypatch.setattr(mobile_routes, "create_asistencia_marca", lambda **kwargs: 801)
    monkeypatch.setattr(mobile_routes, "count_marcas_by_empleado_fecha", lambda empleado_id, fecha: 1)

    resp = client.post(
        "/api/v1/mobile/me/fichadas/scan",
        headers={"Authorization": "Bearer abc"},
        json={"qr_token": "qrauto", "lat": -34.6037, "lon": -58.3816},
    )
    body = resp.get_json()
    assert resp.status_code == 201
    assert body["accion"] == "ingreso"
    assert body["id"] == 81
    assert body["marca_id"] == 801


def test_mobile_fichada_flujo_mixto_qr_manual_qr_qr(monkeypatch):
    client = _build_client(monkeypatch)
    monkeypatch.setattr(jwt_guard, "verificar_token", lambda token: {"empleado_id": 6})
    monkeypatch.setattr(
        mobile_routes,
        "get_empleado_by_id",
        lambda empleado_id: {
            "id": empleado_id,
            "activo": 1,
            "empresa_id": 1,
            "dni": "6",
            "nombre": "Emp",
            "apellido": "Six",
        },
    )
    monkeypatch.setattr(
        mobile_routes,
        "get_by_empresa_id",
        lambda empresa_id: {
            "requiere_qr": 0,
            "requiere_foto": 0,
            "requiere_geo": 0,
        },
    )
    monkeypatch.setattr(
        mobile_routes,
        "verificar_token_qr",
        lambda token, accion_esperada=None: {
            "type": "asistencia_qr",
            "accion": "auto",
            "empresa_id": 1,
            "scope": "empresa",
        },
    )
    monkeypatch.setattr(
        mobile_routes,
        "_validar_geo_scan_qr",
        lambda empleado, qr_payload, lat, lon: {
            "gps_ok": True,
            "distancia_m": 10.0,
            "tolerancia_m": 80.0,
            "ref_lat": -34.0,
            "ref_lon": -58.0,
            "sucursal_id": 1,
        },
    )
    monkeypatch.setattr(mobile_routes, "validar_asistencia", lambda *args: ({}, "ok"))

    state = {
        "asistencia_id": 100,
        "resumen": None,
        "marcas": [],
    }

    def _get_resumen(_empleado_id, _fecha):
        return state["resumen"]

    def _get_last_marca(_empleado_id, _fecha):
        if not state["marcas"]:
            return None
        last = state["marcas"][-1]
        return {
            "id": last["id"],
            "fecha": "2026-03-02",
            "hora": last["hora"],
            "accion": last["accion"],
        }

    def _upsert(**kwargs):
        accion = kwargs["accion"]
        hora = kwargs["hora"]
        resumen = state["resumen"]

        if accion == "ingreso":
            if resumen and resumen.get("hora_entrada") and resumen.get("hora_salida") is None:
                raise ValueError("Ya hay un ingreso abierto para esa fecha.")
            if not resumen or (resumen.get("hora_entrada") and resumen.get("hora_salida")):
                state["asistencia_id"] += 1
                state["resumen"] = {"id": state["asistencia_id"], "hora_entrada": hora, "hora_salida": None}
            else:
                resumen["hora_entrada"] = hora
                resumen["hora_salida"] = None
            return state["resumen"]["id"]

        if not resumen or not resumen.get("hora_entrada") or resumen.get("hora_salida") is not None:
            raise ValueError("No hay fichada de entrada para esa fecha.")
        resumen["hora_salida"] = hora
        return resumen["id"]

    def _create_marca(**kwargs):
        marca_id = len(state["marcas"]) + 1
        state["marcas"].append({"id": marca_id, "accion": kwargs["accion"], "hora": kwargs["hora"]})
        return marca_id

    monkeypatch.setattr(mobile_routes, "get_by_empleado_fecha", _get_resumen)
    monkeypatch.setattr(mobile_routes, "get_last_marca_by_empleado_fecha", _get_last_marca)
    monkeypatch.setattr(mobile_routes, "upsert_resumen_desde_marca", _upsert)
    monkeypatch.setattr(mobile_routes, "create_asistencia_marca", _create_marca)
    monkeypatch.setattr(mobile_routes, "count_marcas_by_empleado_fecha", lambda empleado_id, fecha: len(state["marcas"]))

    # 1) ingreso qr
    resp1 = client.post(
        "/api/v1/mobile/me/fichadas/scan",
        headers={"Authorization": "Bearer abc"},
        json={"qr_token": "qrauto", "lat": -34.6037, "lon": -58.3816, "hora": "08:00"},
    )
    assert resp1.status_code == 201
    assert resp1.get_json()["accion"] == "ingreso"

    # 2) egreso manual
    resp2 = client.post(
        "/api/v1/mobile/me/fichadas/salida",
        headers={"Authorization": "Bearer abc"},
        json={"metodo": "manual", "hora_salida": "12:00"},
    )
    assert resp2.status_code == 200

    # 3) reingreso qr
    resp3 = client.post(
        "/api/v1/mobile/me/fichadas/scan",
        headers={"Authorization": "Bearer abc"},
        json={"qr_token": "qrauto", "lat": -34.6037, "lon": -58.3816, "hora": "13:00"},
    )
    assert resp3.status_code == 201
    assert resp3.get_json()["accion"] == "ingreso"

    # 4) egreso qr
    resp4 = client.post(
        "/api/v1/mobile/me/fichadas/scan",
        headers={"Authorization": "Bearer abc"},
        json={"qr_token": "qrauto", "lat": -34.6037, "lon": -58.3816, "hora": "17:00"},
    )
    assert resp4.status_code == 200
    assert resp4.get_json()["accion"] == "egreso"

    assert [m["accion"] for m in state["marcas"]] == ["ingreso", "egreso", "ingreso", "egreso"]


def test_mobile_fichada_scan_qr_tipo_marca_del_qr_prevalece(monkeypatch):
    client = _build_client(monkeypatch)
    monkeypatch.setattr(jwt_guard, "verificar_token", lambda token: {"empleado_id": 6})
    monkeypatch.setattr(
        mobile_routes,
        "get_empleado_by_id",
        lambda empleado_id: {
            "id": empleado_id,
            "activo": 1,
            "empresa_id": 1,
            "dni": "6",
            "nombre": "Emp",
            "apellido": "Six",
        },
    )
    monkeypatch.setattr(
        mobile_routes,
        "get_by_empresa_id",
        lambda empresa_id: {
            "requiere_qr": 1,
            "requiere_foto": 0,
            "requiere_geo": 0,
        },
    )
    monkeypatch.setattr(
        mobile_routes,
        "verificar_token_qr",
        lambda token, accion_esperada=None: {
            "type": "asistencia_qr",
            "accion": "auto",
            "empresa_id": 1,
            "scope": "empresa",
            "tipo_marca": "almuerzo",
        },
    )
    monkeypatch.setattr(mobile_routes, "get_by_empleado_fecha", lambda empleado_id, fecha: None)
    monkeypatch.setattr(mobile_routes, "get_last_marca_by_empleado_fecha", lambda empleado_id, fecha: None)
    monkeypatch.setattr(
        mobile_routes,
        "_validar_geo_scan_qr",
        lambda empleado, qr_payload, lat, lon: {
            "gps_ok": True,
            "distancia_m": 10.1,
            "tolerancia_m": 80.0,
            "ref_lat": -34.0,
            "ref_lon": -58.0,
            "sucursal_id": 1,
        },
    )
    monkeypatch.setattr(mobile_routes, "validar_asistencia", lambda *args: ({}, "ok"))
    monkeypatch.setattr(mobile_routes, "upsert_resumen_desde_marca", lambda **kwargs: 88)
    captured = {}

    def _fake_create_asistencia_marca(**kwargs):
        captured.update(kwargs)
        return 999

    monkeypatch.setattr(mobile_routes, "create_asistencia_marca", _fake_create_asistencia_marca)
    monkeypatch.setattr(mobile_routes, "count_marcas_by_empleado_fecha", lambda empleado_id, fecha: 1)

    resp = client.post(
        "/api/v1/mobile/me/fichadas/scan",
        headers={"Authorization": "Bearer abc"},
        json={"qr_token": "qrauto", "tipo_marca": "desayuno", "lat": -34.6037, "lon": -58.3816},
    )
    body = resp.get_json()
    assert resp.status_code == 201
    assert body["tipo_marca"] == "almuerzo"
    assert captured["tipo_marca"] == "almuerzo"


def test_mobile_fichada_scan_qr_fuera_rango(monkeypatch):
    client = _build_client(monkeypatch)
    monkeypatch.setattr(jwt_guard, "verificar_token", lambda token: {"empleado_id": 6})
    monkeypatch.setattr(
        mobile_routes,
        "get_empleado_by_id",
        lambda empleado_id: {
            "id": empleado_id,
            "activo": 1,
            "empresa_id": 1,
            "dni": "6",
            "nombre": "Emp",
            "apellido": "Six",
        },
    )
    monkeypatch.setattr(
        mobile_routes,
        "get_by_empresa_id",
        lambda empresa_id: {
            "requiere_qr": 1,
            "requiere_foto": 0,
            "requiere_geo": 0,
        },
    )
    monkeypatch.setattr(
        mobile_routes,
        "verificar_token_qr",
        lambda token, accion_esperada=None: {
            "type": "asistencia_qr",
            "accion": "auto",
            "empresa_id": 1,
            "scope": "empresa",
        },
    )
    monkeypatch.setattr(
        mobile_routes,
        "_validar_geo_scan_qr",
        lambda empleado, qr_payload, lat, lon: {
            "gps_ok": False,
            "distancia_m": 302.5,
            "tolerancia_m": 80.0,
            "ref_lat": -34.0,
            "ref_lon": -58.0,
            "sucursal_id": 1,
        },
    )
    captured = {}

    def _fake_create_geo_qr_rechazo(**kwargs):
        captured.update(kwargs)
        return 901

    monkeypatch.setattr(mobile_routes, "create_geo_qr_rechazo", _fake_create_geo_qr_rechazo)
    monkeypatch.setattr(mobile_routes, "create_audit", lambda *args, **kwargs: True)

    resp = client.post(
        "/api/v1/mobile/me/fichadas/scan",
        headers={"Authorization": "Bearer abc"},
        json={"qr_token": "qrauto", "lat": -34.6037, "lon": -58.3816},
    )
    body = resp.get_json()
    assert resp.status_code == 403
    assert body["gps_ok"] is False
    assert body["alerta_fraude"] is True
    assert body["evento_id"] == 901
    assert captured["empleado_id"] == 6
    assert captured["empresa_id"] == 1
    assert captured["distancia_m"] == 302.5
    assert captured["tolerancia_m"] == 80.0


def test_mobile_fichada_scan_qr_cooldown_duplicate(monkeypatch):
    client = _build_client(monkeypatch)
    monkeypatch.setattr(jwt_guard, "verificar_token", lambda token: {"empleado_id": 6})
    monkeypatch.setattr(
        mobile_routes,
        "get_empleado_by_id",
        lambda empleado_id: {
            "id": empleado_id,
            "activo": 1,
            "empresa_id": 1,
            "dni": "6",
            "nombre": "Emp",
            "apellido": "Six",
        },
    )
    monkeypatch.setattr(
        mobile_routes,
        "get_by_empresa_id",
        lambda empresa_id: {
            "requiere_qr": 1,
            "requiere_foto": 0,
            "requiere_geo": 0,
            "cooldown_scan_segundos": 60,
        },
    )
    monkeypatch.setattr(
        mobile_routes,
        "verificar_token_qr",
        lambda token, accion_esperada=None: {
            "type": "asistencia_qr",
            "accion": "auto",
            "empresa_id": 1,
            "scope": "empresa",
        },
    )
    monkeypatch.setattr(
        mobile_routes,
        "_validar_geo_scan_qr",
        lambda empleado, qr_payload, lat, lon: {
            "gps_ok": True,
            "distancia_m": 10.0,
            "tolerancia_m": 80.0,
            "ref_lat": -34.0,
            "ref_lon": -58.0,
            "sucursal_id": 1,
        },
    )
    monkeypatch.setattr(
        mobile_routes,
        "get_by_empleado_fecha",
        lambda empleado_id, fecha: {"id": 10, "hora_entrada": "08:00", "hora_salida": None},
    )
    monkeypatch.setattr(
        mobile_routes,
        "get_last_marca_by_empleado_fecha",
        lambda empleado_id, fecha: {
            "id": 501,
            "fecha": fecha,
            "hora": "08:00",
            "accion": "ingreso",
            "fecha_creacion": datetime.datetime.now() - datetime.timedelta(seconds=10),
        },
    )

    resp = client.post(
        "/api/v1/mobile/me/fichadas/scan",
        headers={"Authorization": "Bearer abc"},
        json={"qr_token": "qrauto", "lat": -34.6037, "lon": -58.3816},
    )
    body = resp.get_json()
    assert resp.status_code == 409
    assert "Escaneo duplicado" in body["error"]
    assert body["code"] == "scan_cooldown"
    assert isinstance(body["cooldown_segundos_restantes"], int)


def test_mobile_me_marcas_ok(monkeypatch):
    client = _build_client(monkeypatch)
    monkeypatch.setattr(jwt_guard, "verificar_token", lambda token: {"empleado_id": 6})
    monkeypatch.setattr(
        mobile_routes,
        "get_empleado_by_id",
        lambda empleado_id: {
            "id": empleado_id,
            "activo": 1,
            "empresa_id": 1,
            "dni": "6",
            "nombre": "Emp",
            "apellido": "Six",
        },
    )
    monkeypatch.setattr(
        mobile_routes,
        "get_marcas_page_by_empleado",
        lambda empleado_id, page, per_page, fecha_desde=None, fecha_hasta=None: (
            [
                {
                    "id": 9001,
                    "asistencia_id": 10,
                    "fecha": "2026-02-18",
                    "hora": "08:00",
                    "accion": "ingreso",
                    "metodo": "qr",
                    "tipo_marca": "almuerzo",
                    "estado": "ok",
                    "observaciones": "ok",
                    "lat": -34.6,
                    "lon": -58.38,
                    "gps_ok": 1,
                    "gps_distancia_m": 11.5,
                    "gps_tolerancia_m": 80.0,
                    "fecha_creacion": "2026-02-18T08:00:01",
                }
            ],
            1,
        ),
    )

    resp = client.get("/api/v1/mobile/me/marcas?page=1&per=20", headers={"Authorization": "Bearer abc"})
    body = resp.get_json()
    assert resp.status_code == 200
    assert body["total"] == 1
    assert body["items"][0]["id"] == 9001
    assert body["items"][0]["accion"] == "ingreso"
    assert body["items"][0]["tipo_marca"] == "almuerzo"
    assert body["items"][0]["gps_ok"] is True


def test_mobile_eventos_seguridad_ok(monkeypatch):
    client = _build_client(monkeypatch)
    monkeypatch.setattr(jwt_guard, "verificar_token", lambda token: {"empleado_id": 6})
    monkeypatch.setattr(
        mobile_routes,
        "get_empleado_by_id",
        lambda empleado_id: {
            "id": empleado_id,
            "activo": 1,
            "empresa_id": 1,
            "dni": "6",
            "nombre": "Emp",
            "apellido": "Six",
        },
    )
    monkeypatch.setattr(
        mobile_routes,
        "get_security_events_page",
        lambda empleado_id, page, per_page, tipo_evento=None: (
            [
                {
                    "id": 901,
                    "tipo_evento": "qr_geo_fuera_rango",
                    "severidad": "alta",
                    "alerta_fraude": True,
                    "fecha": "2026-02-18T15:24:10",
                    "fecha_operacion": "2026-02-18",
                    "hora_operacion": "15:24",
                    "lat": -34.6,
                    "lon": -58.38,
                    "ref_lat": -34.61,
                    "ref_lon": -58.37,
                    "distancia_m": 302.5,
                    "tolerancia_m": 80.0,
                    "sucursal_id": 3,
                }
            ],
            1,
        ),
    )

    resp = client.get("/api/v1/mobile/me/eventos-seguridad?page=1&per=10", headers={"Authorization": "Bearer abc"})
    body = resp.get_json()
    assert resp.status_code == 200
    assert body["total"] == 1
    assert body["items"][0]["id"] == 901
    assert body["items"][0]["alerta_fraude"] is True


def test_mobile_eventos_seguridad_page_clamp(monkeypatch):
    client = _build_client(monkeypatch)
    monkeypatch.setattr(jwt_guard, "verificar_token", lambda token: {"empleado_id": 6})
    monkeypatch.setattr(
        mobile_routes,
        "get_empleado_by_id",
        lambda empleado_id: {
            "id": empleado_id,
            "activo": 1,
            "empresa_id": 1,
            "dni": "6",
            "nombre": "Emp",
            "apellido": "Six",
        },
    )
    captured = {}

    def _fake_get_security_events_page(empleado_id, page, per_page, tipo_evento=None):
        captured["page"] = page
        captured["per_page"] = per_page
        return [], 0

    monkeypatch.setattr(mobile_routes, "get_security_events_page", _fake_get_security_events_page)

    resp = client.get("/api/v1/mobile/me/eventos-seguridad?page=0&per=10", headers={"Authorization": "Bearer abc"})
    body = resp.get_json()
    assert resp.status_code == 200
    assert body["total"] == 0
    assert captured["page"] == 1
    assert captured["per_page"] == 10


def test_mobile_eventos_seguridad_error_controlado(monkeypatch):
    client = _build_client(monkeypatch)
    monkeypatch.setattr(jwt_guard, "verificar_token", lambda token: {"empleado_id": 6})
    monkeypatch.setattr(
        mobile_routes,
        "get_empleado_by_id",
        lambda empleado_id: {
            "id": empleado_id,
            "activo": 1,
            "empresa_id": 1,
            "dni": "6",
            "nombre": "Emp",
            "apellido": "Six",
        },
    )
    monkeypatch.setattr(
        mobile_routes,
        "get_security_events_page",
        lambda empleado_id, page, per_page, tipo_evento=None: (_ for _ in ()).throw(RuntimeError("db fail")),
    )

    resp = client.get("/api/v1/mobile/me/eventos-seguridad", headers={"Authorization": "Bearer abc"})
    body = resp.get_json()
    assert resp.status_code == 500
    assert "No se pudo obtener eventos de seguridad" in body["error"]


def test_mobile_me_estadisticas_ok(monkeypatch):
    client = _build_client(monkeypatch)
    monkeypatch.setattr(jwt_guard, "verificar_token", lambda token: {"empleado_id": 6})
    monkeypatch.setattr(
        mobile_routes,
        "get_empleado_by_id",
        lambda empleado_id: {
            "id": empleado_id,
            "activo": 1,
            "empresa_id": 1,
            "dni": "6",
            "nombre": "Emp",
            "apellido": "Six",
        },
    )
    monkeypatch.setattr(
        mobile_routes,
        "get_mobile_stats_by_empleado",
        lambda empleado_id, fecha_desde, fecha_hasta: {
            "totales": {
                "registros": 20,
                "ok": 14,
                "tarde": 3,
                "ausente": 2,
                "salida_anticipada": 1,
                "sin_estado": 0,
            },
            "kpis": {
                "puntualidad_pct": 70.0,
                "ausentismo_pct": 10.0,
                "cumplimiento_jornada_pct": 88.9,
                "no_show_pct": 50.0,
                "tasa_salida_anticipada_pct": 5.0,
            },
            "jornadas": {
                "completas": 16,
                "con_marca": 18,
                "incompletas": 2,
            },
            "justificaciones": {
                "total": 4,
                "pendientes": 1,
                "aprobadas": 2,
                "rechazadas": 1,
                "tasa_aprobacion_pct": 50.0,
            },
            "vacaciones": {"eventos": 1, "dias": 5},
            "ausencias": {"total": 2, "sin_justificacion": 1},
            "series": {"diaria": [{"fecha": "2026-02-01", "registros": 1, "ok": 1, "tarde": 0, "ausente": 0, "salida_anticipada": 0, "puntualidad_pct": 100.0, "ausentismo_pct": 0.0}]},
        },
    )

    resp = client.get(
        "/api/v1/mobile/me/estadisticas?desde=2026-02-01&hasta=2026-02-27",
        headers={"Authorization": "Bearer abc"},
    )
    body = resp.get_json()
    assert resp.status_code == 200
    assert body["periodo"]["desde"] == "2026-02-01"
    assert body["periodo"]["hasta"] == "2026-02-27"
    assert body["totales"]["registros"] == 20
    assert body["kpis"]["puntualidad_pct"] == 70.0
    assert body["justificaciones"]["total"] == 4
    assert body["vacaciones"]["dias"] == 5


def test_mobile_me_estadisticas_fecha_futura_bloqueada(monkeypatch):
    client = _build_client(monkeypatch)
    monkeypatch.setattr(jwt_guard, "verificar_token", lambda token: {"empleado_id": 6})
    monkeypatch.setattr(
        mobile_routes,
        "get_empleado_by_id",
        lambda empleado_id: {
            "id": empleado_id,
            "activo": 1,
            "empresa_id": 1,
            "dni": "6",
            "nombre": "Emp",
            "apellido": "Six",
        },
    )

    resp = client.get(
        "/api/v1/mobile/me/estadisticas?desde=2026-02-01&hasta=2099-01-01",
        headers={"Authorization": "Bearer abc"},
    )
    body = resp.get_json()
    assert resp.status_code == 400
    assert "No se permiten fechas futuras" in body["error"]


def test_mobile_me_estadisticas_desde_mayor_a_hasta(monkeypatch):
    client = _build_client(monkeypatch)
    monkeypatch.setattr(jwt_guard, "verificar_token", lambda token: {"empleado_id": 6})
    monkeypatch.setattr(
        mobile_routes,
        "get_empleado_by_id",
        lambda empleado_id: {
            "id": empleado_id,
            "activo": 1,
            "empresa_id": 1,
            "dni": "6",
            "nombre": "Emp",
            "apellido": "Six",
        },
    )

    today = datetime.date.today()
    desde = today.isoformat()
    hasta = (today - datetime.timedelta(days=1)).isoformat()
    resp = client.get(
        f"/api/v1/mobile/me/estadisticas?desde={desde}&hasta={hasta}",
        headers={"Authorization": "Bearer abc"},
    )
    body = resp.get_json()
    assert resp.status_code == 400
    assert "desde > hasta" in body["error"]


def test_mobile_me_estadisticas_rango_maximo_366(monkeypatch):
    client = _build_client(monkeypatch)
    monkeypatch.setattr(jwt_guard, "verificar_token", lambda token: {"empleado_id": 6})
    monkeypatch.setattr(
        mobile_routes,
        "get_empleado_by_id",
        lambda empleado_id: {
            "id": empleado_id,
            "activo": 1,
            "empresa_id": 1,
            "dni": "6",
            "nombre": "Emp",
            "apellido": "Six",
        },
    )

    today = datetime.date.today()
    desde = (today - datetime.timedelta(days=367)).isoformat()
    hasta = today.isoformat()
    resp = client.get(
        f"/api/v1/mobile/me/estadisticas?desde={desde}&hasta={hasta}",
        headers={"Authorization": "Bearer abc"},
    )
    body = resp.get_json()
    assert resp.status_code == 400
    assert "366 dias" in body["error"]


def test_mobile_me_estadisticas_error_controlado(monkeypatch):
    client = _build_client(monkeypatch)
    monkeypatch.setattr(jwt_guard, "verificar_token", lambda token: {"empleado_id": 6})
    monkeypatch.setattr(
        mobile_routes,
        "get_empleado_by_id",
        lambda empleado_id: {
            "id": empleado_id,
            "activo": 1,
            "empresa_id": 1,
            "dni": "6",
            "nombre": "Emp",
            "apellido": "Six",
        },
    )
    monkeypatch.setattr(
        mobile_routes,
        "get_mobile_stats_by_empleado",
        lambda empleado_id, fecha_desde, fecha_hasta: (_ for _ in ()).throw(RuntimeError("db fail")),
    )

    today = datetime.date.today().isoformat()
    resp = client.get(
        f"/api/v1/mobile/me/estadisticas?desde={today}&hasta={today}",
        headers={"Authorization": "Bearer abc"},
    )
    body = resp.get_json()
    assert resp.status_code == 500
    assert "No se pudieron obtener estadisticas." in body["error"]


def test_mobile_me_perfil_actualiza_con_foto_file(monkeypatch):
    client = _build_client(monkeypatch)
    monkeypatch.setattr(jwt_guard, "verificar_token", lambda token: {"empleado_id": 8})

    state = {
        "telefono": "1111",
        "direccion": "Direccion vieja",
        "foto": "https://old/foto.jpg",
    }

    def _fake_get_empleado_by_id(empleado_id):
        return {
            "id": empleado_id,
            "activo": 1,
            "empresa_id": 1,
            "dni": "30123456",
            "nombre": "Emp",
            "apellido": "Eight",
            "telefono": state["telefono"],
            "direccion": state["direccion"],
            "foto": state["foto"],
        }

    def _fake_update_mobile_profile(empleado_id, telefono, direccion, foto):
        state["telefono"] = telefono
        state["direccion"] = direccion
        state["foto"] = foto
        return True

    monkeypatch.setattr(mobile_routes, "get_empleado_by_id", _fake_get_empleado_by_id)
    monkeypatch.setattr(mobile_routes, "update_mobile_profile", _fake_update_mobile_profile)
    monkeypatch.setattr(
        mobile_routes,
        "upload_profile_photo",
        lambda file_storage, dni: f"https://fotos.www.delpalacio.com.ar/{dni}.jpg",
    )

    resp = client.put(
        "/api/v1/mobile/me/perfil",
        headers={"Authorization": "Bearer abc"},
        data={
            "telefono": "2222",
            "direccion": "Direccion nueva",
            "foto_file": (io.BytesIO(b"\xff\xd8\xff\xdb\x00C"), "selfie.jpg"),
        },
        content_type="multipart/form-data",
    )
    body = resp.get_json()
    assert resp.status_code == 200
    assert body["telefono"] == "2222"
    assert body["direccion"] == "Direccion nueva"
    assert body["foto"] == "https://fotos.www.delpalacio.com.ar/30123456.jpg"


def test_mobile_me_perfil_foto_file_invalida(monkeypatch):
    client = _build_client(monkeypatch)
    monkeypatch.setattr(jwt_guard, "verificar_token", lambda token: {"empleado_id": 9})
    monkeypatch.setattr(
        mobile_routes,
        "get_empleado_by_id",
        lambda empleado_id: {
            "id": empleado_id,
            "activo": 1,
            "empresa_id": 1,
            "dni": "30999999",
            "nombre": "Emp",
            "apellido": "Nine",
            "telefono": "123",
            "direccion": "X",
            "foto": None,
        },
    )
    monkeypatch.setattr(
        mobile_routes,
        "upload_profile_photo",
        lambda file_storage, dni: (_ for _ in ()).throw(ValueError("Tipo de imagen no permitido.")),
    )

    resp = client.put(
        "/api/v1/mobile/me/perfil",
        headers={"Authorization": "Bearer abc"},
        data={"foto_file": (io.BytesIO(b"not-an-image"), "archivo.txt")},
        content_type="multipart/form-data",
    )
    body = resp.get_json()
    assert resp.status_code == 400
    assert "Tipo de imagen no permitido" in body["error"]


def test_mobile_me_perfil_foto_file_error_ftp(monkeypatch):
    client = _build_client(monkeypatch)
    monkeypatch.setattr(jwt_guard, "verificar_token", lambda token: {"empleado_id": 9})
    monkeypatch.setattr(
        mobile_routes,
        "get_empleado_by_id",
        lambda empleado_id: {
            "id": empleado_id,
            "activo": 1,
            "empresa_id": 1,
            "dni": "30999999",
            "nombre": "Emp",
            "apellido": "Nine",
            "telefono": "123",
            "direccion": "X",
            "foto": None,
        },
    )
    monkeypatch.setattr(
        mobile_routes,
        "upload_profile_photo",
        lambda file_storage, dni: (_ for _ in ()).throw(RuntimeError("ftp down")),
    )

    resp = client.put(
        "/api/v1/mobile/me/perfil",
        headers={"Authorization": "Bearer abc"},
        data={"foto_file": (io.BytesIO(b"\xff\xd8\xff"), "selfie.jpg")},
        content_type="multipart/form-data",
    )
    body = resp.get_json()
    assert resp.status_code == 500
    assert "No se pudo subir la foto de perfil." in body["error"]


def test_mobile_me_perfil_eliminar_foto(monkeypatch):
    client = _build_client(monkeypatch)
    monkeypatch.setattr(jwt_guard, "verificar_token", lambda token: {"empleado_id": 10})

    state = {
        "telefono": "4444",
        "direccion": "Direccion vieja",
        "foto": "https://fotos.www.delpalacio.com.ar/30111111.jpg",
    }
    deleted = {"called": False}

    def _fake_get_empleado_by_id(empleado_id):
        return {
            "id": empleado_id,
            "activo": 1,
            "empresa_id": 1,
            "dni": "30111111",
            "nombre": "Emp",
            "apellido": "Ten",
            "telefono": state["telefono"],
            "direccion": state["direccion"],
            "foto": state["foto"],
        }

    def _fake_update_mobile_profile(empleado_id, telefono, direccion, foto):
        state["telefono"] = telefono
        state["direccion"] = direccion
        state["foto"] = foto
        return True

    monkeypatch.setattr(mobile_routes, "get_empleado_by_id", _fake_get_empleado_by_id)
    monkeypatch.setattr(mobile_routes, "update_mobile_profile", _fake_update_mobile_profile)
    monkeypatch.setattr(
        mobile_routes,
        "delete_profile_photo_for_dni",
        lambda dni: deleted.update({"called": True}) or True,
    )

    resp = client.put(
        "/api/v1/mobile/me/perfil",
        headers={"Authorization": "Bearer abc"},
        data={"eliminar_foto": "true"},
        content_type="multipart/form-data",
    )
    body = resp.get_json()
    assert resp.status_code == 200
    assert body["foto"] is None
    assert deleted["called"] is True


def test_mobile_me_perfil_foto_file_y_eliminar_foto_conflicto(monkeypatch):
    client = _build_client(monkeypatch)
    monkeypatch.setattr(jwt_guard, "verificar_token", lambda token: {"empleado_id": 11})
    monkeypatch.setattr(
        mobile_routes,
        "get_empleado_by_id",
        lambda empleado_id: {
            "id": empleado_id,
            "activo": 1,
            "empresa_id": 1,
            "dni": "30111112",
            "nombre": "Emp",
            "apellido": "Eleven",
            "telefono": "5555",
            "direccion": "X",
            "foto": None,
        },
    )

    resp = client.put(
        "/api/v1/mobile/me/perfil",
        headers={"Authorization": "Bearer abc"},
        data={
            "eliminar_foto": "true",
            "foto_file": (io.BytesIO(b"\xff\xd8\xff"), "selfie.jpg"),
        },
        content_type="multipart/form-data",
    )
    body = resp.get_json()
    assert resp.status_code == 400
    assert "foto_file junto con eliminar_foto" in body["error"]


def test_mobile_me_perfil_delete_foto_endpoint(monkeypatch):
    client = _build_client(monkeypatch)
    monkeypatch.setattr(jwt_guard, "verificar_token", lambda token: {"empleado_id": 12})

    state = {
        "telefono": "6666",
        "direccion": "Direccion",
        "foto": "https://fotos.www.delpalacio.com.ar/30111113.jpg",
    }
    deleted = {"called": False}

    def _fake_get_empleado_by_id(empleado_id):
        return {
            "id": empleado_id,
            "activo": 1,
            "empresa_id": 1,
            "dni": "30111113",
            "nombre": "Emp",
            "apellido": "Twelve",
            "telefono": state["telefono"],
            "direccion": state["direccion"],
            "foto": state["foto"],
        }

    def _fake_update_mobile_profile(empleado_id, telefono, direccion, foto):
        state["telefono"] = telefono
        state["direccion"] = direccion
        state["foto"] = foto
        return True

    monkeypatch.setattr(mobile_routes, "get_empleado_by_id", _fake_get_empleado_by_id)
    monkeypatch.setattr(mobile_routes, "update_mobile_profile", _fake_update_mobile_profile)
    monkeypatch.setattr(
        mobile_routes,
        "delete_profile_photo_for_dni",
        lambda dni: deleted.update({"called": True}) or True,
    )

    resp = client.delete(
        "/api/v1/mobile/me/perfil/foto",
        headers={"Authorization": "Bearer abc"},
    )
    body = resp.get_json()
    assert resp.status_code == 200
    assert body["ok"] is True
    assert body["foto"] is None
    assert deleted["called"] is True
    assert state["foto"] is None
