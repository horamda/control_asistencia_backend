import datetime
import io

import app as app_module
import utils.jwt_guard as jwt_guard
import routes.mobile_v1_routes as mobile_routes


def _build_client(monkeypatch):
    monkeypatch.setattr(app_module, "init_db", lambda: None)
    monkeypatch.setattr(mobile_routes, "get_profile_photo_version_by_dni", lambda dni: None)
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
    monkeypatch.setattr(mobile_routes, "get_profile_photo_version_by_dni", lambda dni: "1709294400")

    resp = client.post("/api/v1/mobile/auth/login", json={"dni": "123", "password": "x"})
    body = resp.get_json()
    assert resp.status_code == 200
    assert body["token"] == "token-demo"
    assert body["empleado"]["id"] == 10
    assert body["empleado"]["foto"] == "https://cdn.example.com/fotos/123.jpg"
    assert body["empleado"]["imagen_version"] == "1709294400"


def test_mobile_login_invalid_credentials_sanitized(monkeypatch):
    client = _build_client(monkeypatch)
    monkeypatch.setattr(
        mobile_routes,
        "authenticate_user",
        lambda dni, password: (None, "inactive"),
    )

    resp = client.post("/api/v1/mobile/auth/login", json={"dni": "123", "password": "x"})
    body = resp.get_json()

    assert resp.status_code == 401
    assert body["error"] == "Credenciales invalidas."


def test_mobile_me_requires_bearer(monkeypatch):
    client = _build_client(monkeypatch)
    resp = client.get("/api/v1/mobile/me")
    assert resp.status_code == 401
    assert "Bearer" in resp.get_json()["error"]


def test_mobile_me_invalid_token_sanitized(monkeypatch):
    client = _build_client(monkeypatch)
    monkeypatch.setattr(jwt_guard, "verificar_token", lambda token: (_ for _ in ()).throw(ValueError("Token expirado")))

    resp = client.get("/api/v1/mobile/me", headers={"Authorization": "Bearer abc"})
    body = resp.get_json()

    assert resp.status_code == 401
    assert body["error"] == "Sesion invalida o expirada."
    assert resp.headers["WWW-Authenticate"] == 'Bearer realm="mobile"'


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
    monkeypatch.setattr(mobile_routes, "get_profile_photo_version_by_dni", lambda dni: "1709294500")

    resp = client.get("/api/v1/mobile/me", headers={"Authorization": "Bearer abc"})
    assert resp.status_code == 200
    assert resp.get_json()["id"] == 10
    assert resp.get_json()["imagen_version"] == "1709294500"


def test_mobile_auth_refresh_invalid_session_sanitized(monkeypatch):
    client = _build_client(monkeypatch)
    monkeypatch.setattr(jwt_guard, "verificar_token", lambda token: {"empleado_id": 10})
    monkeypatch.setattr(mobile_routes, "get_empleado_by_id", lambda empleado_id: None)

    resp = client.post("/api/v1/mobile/auth/refresh", headers={"Authorization": "Bearer abc"})
    body = resp.get_json()

    assert resp.status_code == 401
    assert body["error"] == "Sesion invalida o expirada."


def test_mobile_me_config_asistencia_incluye_intervalo_minimo(monkeypatch):
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
        },
    )
    monkeypatch.setattr(
        mobile_routes,
        "get_by_empresa_id",
        lambda empresa_id: {
            "empresa_id": empresa_id,
            "requiere_qr": 1,
            "requiere_foto": 0,
            "requiere_geo": 1,
            "tolerancia_global": 5,
            "cooldown_scan_segundos": 45,
            "intervalo_minimo_fichadas_minutos": 30,
        },
    )

    resp = client.get("/api/v1/mobile/me/config-asistencia", headers={"Authorization": "Bearer abc"})
    body = resp.get_json()
    assert resp.status_code == 200
    assert body["empresa_id"] == 3
    assert body["cooldown_scan_segundos"] == 45
    assert body["intervalo_minimo_fichadas_minutos"] == 30


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


def test_mobile_fichada_entrada_rechaza_reingreso_sin_intervalo_minimo(monkeypatch):
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
        lambda empleado_id, fecha: {"id": 10, "hora_entrada": "07:00", "hora_salida": "07:01"},
    )
    monkeypatch.setattr(
        mobile_routes,
        "get_last_marca_by_empleado_fecha",
        lambda empleado_id, fecha: {"id": 900, "accion": "egreso", "hora": "07:01"},
    )

    resp = client.post(
        "/api/v1/mobile/me/fichadas/entrada",
        headers={"Authorization": "Bearer abc"},
        json={"metodo": "manual", "hora_entrada": "07:30"},
    )
    body = resp.get_json()
    assert resp.status_code == 409
    assert "al menos 60 minutos" in body["error"]


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


def test_mobile_fichada_salida_rechaza_intervalo_minimo_de_1_hora(monkeypatch):
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
        lambda empleado_id, fecha: {"id": 11, "hora_entrada": "07:00", "hora_salida": None},
    )
    monkeypatch.setattr(
        mobile_routes,
        "get_last_marca_by_empleado_fecha",
        lambda empleado_id, fecha: {"id": 901, "accion": "ingreso", "hora": "07:00"},
    )

    resp = client.post(
        "/api/v1/mobile/me/fichadas/salida",
        headers={"Authorization": "Bearer abc"},
        json={"metodo": "manual", "hora_salida": "07:01"},
    )
    body = resp.get_json()
    assert resp.status_code == 409
    assert "al menos 60 minutos" in body["error"]


def test_mobile_fichada_salida_permite_intervalo_corto_si_config_intervalo_en_cero(monkeypatch):
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
            "intervalo_minimo_fichadas_minutos": 0,
        },
    )
    monkeypatch.setattr(
        mobile_routes,
        "get_by_empleado_fecha",
        lambda empleado_id, fecha: {"id": 11, "hora_entrada": "07:00", "hora_salida": None},
    )
    monkeypatch.setattr(
        mobile_routes,
        "get_last_marca_by_empleado_fecha",
        lambda empleado_id, fecha: {"id": 901, "accion": "ingreso", "hora": "07:00"},
    )
    monkeypatch.setattr(mobile_routes, "validar_asistencia", lambda *args: ({}, "ok"))
    monkeypatch.setattr(mobile_routes, "upsert_resumen_desde_marca", lambda **kwargs: 11)
    monkeypatch.setattr(mobile_routes, "create_asistencia_marca", lambda **kwargs: 902)

    resp = client.post(
        "/api/v1/mobile/me/fichadas/salida",
        headers={"Authorization": "Bearer abc"},
        json={"metodo": "manual", "hora_salida": "07:01"},
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
        json={"qr_token": "qrauto", "lat": -34.6037, "lon": -58.3816, "hora": "09:30"},
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
        json={"qr_token": "qrauto", "lat": -34.6037, "lon": -58.3816, "hora": "13:10"},
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
        json={"qr_token": "qrauto", "lat": -34.6037, "lon": -58.3816, "hora": "13:10"},
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
    monkeypatch.setattr(mobile_routes, "get_by_empleado_fecha", lambda empleado_id, fecha: None)
    monkeypatch.setattr(mobile_routes, "get_last_marca_by_empleado_fecha", lambda empleado_id, fecha: None)
    monkeypatch.setattr(mobile_routes, "validar_asistencia", lambda *args: ({}, "ok"))
    captured_evento = {}
    captured_upsert = {}
    captured_marca = {}

    def _fake_create_geo_qr_rechazo(**kwargs):
        captured_evento.update(kwargs)
        return 901

    def _fake_upsert_resumen_desde_marca(**kwargs):
        captured_upsert.update(kwargs)
        return 77

    def _fake_create_asistencia_marca(**kwargs):
        captured_marca.update(kwargs)
        return 701

    monkeypatch.setattr(mobile_routes, "upsert_resumen_desde_marca", _fake_upsert_resumen_desde_marca)
    monkeypatch.setattr(mobile_routes, "create_asistencia_marca", _fake_create_asistencia_marca)
    monkeypatch.setattr(mobile_routes, "count_marcas_by_empleado_fecha", lambda empleado_id, fecha: 1)
    monkeypatch.setattr(mobile_routes, "create_geo_qr_rechazo", _fake_create_geo_qr_rechazo)
    monkeypatch.setattr(mobile_routes, "create_audit", lambda *args, **kwargs: True)

    resp = client.post(
        "/api/v1/mobile/me/fichadas/scan",
        headers={"Authorization": "Bearer abc"},
        json={"qr_token": "qrauto", "lat": -34.6037, "lon": -58.3816},
    )
    body = resp.get_json()
    assert resp.status_code == 201
    assert body["id"] == 77
    assert body["marca_id"] == 701
    assert body["gps_ok"] is False
    assert body["alerta_fraude"] is True
    assert body["evento_id"] == 901
    assert captured_upsert["gps_ok"] is False
    assert captured_marca["gps_ok"] is False
    assert "alerta_fraude=1" in (captured_marca.get("observaciones") or "")
    assert captured_evento["empleado_id"] == 6
    assert captured_evento["empresa_id"] == 1
    assert captured_evento["distancia_m"] == 302.5
    assert captured_evento["tolerancia_m"] == 80.0


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
    monkeypatch.setattr(mobile_routes, "get_profile_photo_version_by_dni", lambda dni: "1709294600")

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
    assert body["imagen_version"] == "1709294600"


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
    assert body["imagen_version"] is None
    assert deleted["called"] is True
    assert state["foto"] is None


# ---------------------------------------------------------------------------
# /me/justificaciones
# ---------------------------------------------------------------------------

_FAKE_EMPLEADO_JUST = {
    "id": 10, "activo": 1, "empresa_id": 3,
    "dni": "123", "nombre": "Ana", "apellido": "Lopez",
}

_FAKE_JUST_ROW = {
    "id": 55, "empleado_id": 10, "asistencia_id": None,
    "asistencia_fecha": None, "motivo": "Certificado medico",
    "archivo": None, "estado": "pendiente",
    "created_at": datetime.datetime(2026, 3, 1, 10, 0, 0),
}


def _auth_headers():
    return {"Authorization": "Bearer abc"}


def _setup_just_auth(monkeypatch):
    monkeypatch.setattr(jwt_guard, "verificar_token", lambda t: {"empleado_id": 10})
    monkeypatch.setattr(mobile_routes, "get_empleado_by_id", lambda _: _FAKE_EMPLEADO_JUST)


def test_mobile_justificaciones_list_ok(monkeypatch):
    _setup_just_auth(monkeypatch)
    monkeypatch.setattr(
        mobile_routes, "get_justificaciones_page",
        lambda **kw: ([_FAKE_JUST_ROW], 1)
    )
    client = _build_client(monkeypatch)
    resp = client.get("/api/v1/mobile/me/justificaciones", headers=_auth_headers())
    body = resp.get_json()
    assert resp.status_code == 200
    assert body["total"] == 1
    assert body["items"][0]["id"] == 55
    assert body["items"][0]["estado"] == "pendiente"


def test_mobile_justificaciones_list_filtro_estado_invalido(monkeypatch):
    _setup_just_auth(monkeypatch)
    client = _build_client(monkeypatch)
    resp = client.get(
        "/api/v1/mobile/me/justificaciones?estado=en_revision",
        headers=_auth_headers()
    )
    assert resp.status_code == 400
    assert "estado invalido" in resp.get_json()["error"]


def test_mobile_justificaciones_list_filtro_estado_valido(monkeypatch):
    _setup_just_auth(monkeypatch)
    captured = {}
    def _fake_page(**kw):
        captured.update(kw)
        return ([], 0)
    monkeypatch.setattr(mobile_routes, "get_justificaciones_page", _fake_page)
    client = _build_client(monkeypatch)
    resp = client.get(
        "/api/v1/mobile/me/justificaciones?estado=aprobada",
        headers=_auth_headers()
    )
    assert resp.status_code == 200
    assert captured.get("estado") == "aprobada"


def test_mobile_justificaciones_detail_ok(monkeypatch):
    _setup_just_auth(monkeypatch)
    monkeypatch.setattr(mobile_routes, "get_justificacion_by_id", lambda _: _FAKE_JUST_ROW)
    client = _build_client(monkeypatch)
    resp = client.get("/api/v1/mobile/me/justificaciones/55", headers=_auth_headers())
    body = resp.get_json()
    assert resp.status_code == 200
    assert body["id"] == 55
    assert body["motivo"] == "Certificado medico"


def test_mobile_justificaciones_detail_ajena_retorna_404(monkeypatch):
    _setup_just_auth(monkeypatch)
    # justificacion pertenece al empleado 99, no al 10
    monkeypatch.setattr(
        mobile_routes, "get_justificacion_by_id",
        lambda _: {**_FAKE_JUST_ROW, "empleado_id": 99}
    )
    client = _build_client(monkeypatch)
    resp = client.get("/api/v1/mobile/me/justificaciones/55", headers=_auth_headers())
    assert resp.status_code == 404


def test_mobile_justificaciones_create_ok(monkeypatch):
    _setup_just_auth(monkeypatch)
    created_data = {}
    monkeypatch.setattr(
        mobile_routes, "create_justificacion_svc",
        lambda data: (created_data.update(data) or None) or 55
    )
    monkeypatch.setattr(mobile_routes, "get_justificacion_by_id", lambda _: _FAKE_JUST_ROW)
    monkeypatch.setattr(mobile_routes, "create_audit", lambda *a: None)
    client = _build_client(monkeypatch)
    resp = client.post(
        "/api/v1/mobile/me/justificaciones",
        json={"motivo": "Certificado medico", "asistencia_id": None},
        headers=_auth_headers()
    )
    body = resp.get_json()
    assert resp.status_code == 201
    assert body["id"] == 55
    assert created_data["empleado_id"] == 10
    assert created_data["estado"] == "pendiente"


def test_mobile_justificaciones_create_sin_motivo_retorna_400(monkeypatch):
    _setup_just_auth(monkeypatch)
    monkeypatch.setattr(
        mobile_routes, "create_justificacion_svc",
        lambda data: (_ for _ in ()).throw(ValueError("Motivo es requerido."))
    )
    client = _build_client(monkeypatch)
    resp = client.post(
        "/api/v1/mobile/me/justificaciones",
        json={"motivo": ""},
        headers=_auth_headers()
    )
    assert resp.status_code == 400
    assert "motivo" in resp.get_json()["error"].lower()


def test_mobile_justificaciones_update_pendiente_ok(monkeypatch):
    _setup_just_auth(monkeypatch)
    monkeypatch.setattr(mobile_routes, "get_justificacion_by_id", lambda _: _FAKE_JUST_ROW)
    updated = {}
    monkeypatch.setattr(
        mobile_routes, "update_justificacion_svc",
        lambda jid, data: updated.update({"jid": jid, **data})
    )
    monkeypatch.setattr(mobile_routes, "create_audit", lambda *a: None)
    client = _build_client(monkeypatch)
    resp = client.put(
        "/api/v1/mobile/me/justificaciones/55",
        json={"motivo": "Nuevo motivo"},
        headers=_auth_headers()
    )
    assert resp.status_code == 200
    assert updated["motivo"] == "Nuevo motivo"


def test_mobile_justificaciones_update_aprobada_retorna_409(monkeypatch):
    _setup_just_auth(monkeypatch)
    monkeypatch.setattr(
        mobile_routes, "get_justificacion_by_id",
        lambda _: {**_FAKE_JUST_ROW, "estado": "aprobada"}
    )
    client = _build_client(monkeypatch)
    resp = client.put(
        "/api/v1/mobile/me/justificaciones/55",
        json={"motivo": "Intento editar aprobada"},
        headers=_auth_headers()
    )
    assert resp.status_code == 409
    assert "aprobada" in resp.get_json()["error"]


def test_mobile_justificaciones_delete_pendiente_ok(monkeypatch):
    _setup_just_auth(monkeypatch)
    monkeypatch.setattr(mobile_routes, "get_justificacion_by_id", lambda _: _FAKE_JUST_ROW)
    deleted = {}
    monkeypatch.setattr(
        mobile_routes, "delete_justificacion_row",
        lambda jid: deleted.update({"jid": jid})
    )
    monkeypatch.setattr(mobile_routes, "create_audit", lambda *a: None)
    client = _build_client(monkeypatch)
    resp = client.delete("/api/v1/mobile/me/justificaciones/55", headers=_auth_headers())
    assert resp.status_code == 200
    assert resp.get_json()["ok"] is True
    assert deleted["jid"] == 55


def test_mobile_justificaciones_delete_rechazada_retorna_409(monkeypatch):
    _setup_just_auth(monkeypatch)
    monkeypatch.setattr(
        mobile_routes, "get_justificacion_by_id",
        lambda _: {**_FAKE_JUST_ROW, "estado": "rechazada"}
    )
    client = _build_client(monkeypatch)
    resp = client.delete("/api/v1/mobile/me/justificaciones/55", headers=_auth_headers())
    assert resp.status_code == 409


# ---------------------------------------------------------------------------
# Vacaciones
# ---------------------------------------------------------------------------

_FAKE_VAC_ROW = {
    "id": 7,
    "empleado_id": 10,
    "empresa_id": 3,
    "fecha_desde": "2026-01-10",
    "fecha_hasta": "2026-01-20",
    "observaciones": "Vacaciones anuales",
}


def _setup_vac_auth(monkeypatch):
    monkeypatch.setattr(jwt_guard, "verificar_token", lambda token: {"empleado_id": 10})
    monkeypatch.setattr(mobile_routes, "get_empleado_by_id", lambda eid: _FAKE_EMPLEADO_JUST)


def test_mobile_vacaciones_list_ok(monkeypatch):
    _setup_vac_auth(monkeypatch)
    monkeypatch.setattr(
        mobile_routes, "get_vacaciones_page_by_empleado",
        lambda eid, page, per_page, **kw: ([_FAKE_VAC_ROW], 1)
    )
    client = _build_client(monkeypatch)
    resp = client.get("/api/v1/mobile/me/vacaciones", headers=_auth_headers())
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["total"] == 1
    assert data["items"][0]["id"] == 7


def test_mobile_vacaciones_detail_ok(monkeypatch):
    _setup_vac_auth(monkeypatch)
    monkeypatch.setattr(mobile_routes, "get_vacacion_by_id", lambda _: _FAKE_VAC_ROW)
    client = _build_client(monkeypatch)
    resp = client.get("/api/v1/mobile/me/vacaciones/7", headers=_auth_headers())
    assert resp.status_code == 200
    assert resp.get_json()["fecha_desde"] == "2026-01-10"


def test_mobile_vacaciones_detail_ajena_retorna_404(monkeypatch):
    _setup_vac_auth(monkeypatch)
    monkeypatch.setattr(
        mobile_routes, "get_vacacion_by_id",
        lambda _: {**_FAKE_VAC_ROW, "empleado_id": 999}
    )
    client = _build_client(monkeypatch)
    resp = client.get("/api/v1/mobile/me/vacaciones/7", headers=_auth_headers())
    assert resp.status_code == 404


def test_mobile_vacaciones_create_ok(monkeypatch):
    _setup_vac_auth(monkeypatch)
    created = {}
    monkeypatch.setattr(
        mobile_routes, "create_vacacion_row",
        lambda data: (created.update(data) or 7)
    )
    monkeypatch.setattr(mobile_routes, "get_vacacion_by_id", lambda _: _FAKE_VAC_ROW)
    client = _build_client(monkeypatch)
    resp = client.post(
        "/api/v1/mobile/me/vacaciones",
        json={"fecha_desde": "2026-01-10", "fecha_hasta": "2026-01-20"},
        headers=_auth_headers()
    )
    assert resp.status_code == 201
    assert resp.get_json()["id"] == 7


def test_mobile_vacaciones_create_sin_fechas_retorna_400(monkeypatch):
    _setup_vac_auth(monkeypatch)
    client = _build_client(monkeypatch)
    resp = client.post(
        "/api/v1/mobile/me/vacaciones",
        json={"observaciones": "sin fechas"},
        headers=_auth_headers()
    )
    assert resp.status_code == 400
    assert "fecha" in resp.get_json()["error"]


def test_mobile_vacaciones_create_fechas_invertidas_retorna_400(monkeypatch):
    _setup_vac_auth(monkeypatch)
    client = _build_client(monkeypatch)
    resp = client.post(
        "/api/v1/mobile/me/vacaciones",
        json={"fecha_desde": "2026-01-20", "fecha_hasta": "2026-01-10"},
        headers=_auth_headers()
    )
    assert resp.status_code == 400
    assert "posterior" in resp.get_json()["error"]


def test_mobile_vacaciones_update_ok(monkeypatch):
    _setup_vac_auth(monkeypatch)
    monkeypatch.setattr(mobile_routes, "get_vacacion_by_id", lambda _: _FAKE_VAC_ROW)
    updated = {}
    monkeypatch.setattr(
        mobile_routes, "update_vacacion_row",
        lambda vid, data: updated.update({"vid": vid, **data})
    )
    client = _build_client(monkeypatch)
    resp = client.put(
        "/api/v1/mobile/me/vacaciones/7",
        json={"fecha_desde": "2026-02-01", "fecha_hasta": "2026-02-10"},
        headers=_auth_headers()
    )
    assert resp.status_code == 200
    assert updated["fecha_desde"] == "2026-02-01"


def test_mobile_vacaciones_delete_ok(monkeypatch):
    _setup_vac_auth(monkeypatch)
    monkeypatch.setattr(mobile_routes, "get_vacacion_by_id", lambda _: _FAKE_VAC_ROW)
    deleted = {}
    monkeypatch.setattr(
        mobile_routes, "delete_vacacion_row",
        lambda vid: deleted.update({"vid": vid})
    )
    client = _build_client(monkeypatch)
    resp = client.delete("/api/v1/mobile/me/vacaciones/7", headers=_auth_headers())
    assert resp.status_code == 200
    assert resp.get_json()["ok"] is True
    assert deleted["vid"] == 7


def test_mobile_vacaciones_delete_ajena_retorna_404(monkeypatch):
    _setup_vac_auth(monkeypatch)
    monkeypatch.setattr(
        mobile_routes, "get_vacacion_by_id",
        lambda _: {**_FAKE_VAC_ROW, "empleado_id": 999}
    )
    client = _build_client(monkeypatch)
    resp = client.delete("/api/v1/mobile/me/vacaciones/7", headers=_auth_headers())
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Adelantos
# ---------------------------------------------------------------------------

_FAKE_ADELANTO_ROW = {
    "id": 81,
    "empleado_id": 10,
    "empresa_id": 3,
    "periodo_year": 2026,
    "periodo_month": 4,
    "fecha_solicitud": "2026-04-17",
    "estado": "pendiente",
    "created_at": datetime.datetime(2026, 4, 17, 9, 30, 0),
    "resuelto_at": None,
    "resuelto_by_usuario": None,
}

_FAKE_ADELANTO_OLD_ROW = {
    "id": 71,
    "empleado_id": 10,
    "empresa_id": 3,
    "periodo_year": 2026,
    "periodo_month": 3,
    "fecha_solicitud": "2026-03-14",
    "estado": "aprobado",
    "created_at": datetime.datetime(2026, 3, 14, 8, 45, 0),
    "resuelto_at": datetime.datetime(2026, 3, 15, 11, 0, 0),
    "resuelto_by_usuario": "rrhh",
}


def _setup_adelanto_auth(monkeypatch):
    monkeypatch.setattr(jwt_guard, "verificar_token", lambda token: {"empleado_id": 10})
    monkeypatch.setattr(mobile_routes, "get_empleado_by_id", lambda eid: _FAKE_EMPLEADO_JUST)


def test_mobile_adelantos_estado_sin_solicitud(monkeypatch):
    _setup_adelanto_auth(monkeypatch)
    monkeypatch.setattr(mobile_routes, "_today_iso", lambda: "2026-04-17")
    monkeypatch.setattr(mobile_routes, "get_adelanto_mes_actual_svc", lambda empleado_id, **kw: None)
    client = _build_client(monkeypatch)
    resp = client.get("/api/v1/mobile/me/adelantos/estado", headers=_auth_headers())
    body = resp.get_json()
    assert resp.status_code == 200
    assert body["periodo"] == "2026-04"
    assert body["ya_solicitado"] is False
    assert body["adelanto"] is None


def test_mobile_adelantos_resumen_sin_historial(monkeypatch):
    _setup_adelanto_auth(monkeypatch)
    monkeypatch.setattr(mobile_routes, "_today_iso", lambda: "2026-04-18")
    monkeypatch.setattr(mobile_routes, "get_adelanto_mes_actual_svc", lambda empleado_id, **kw: None)
    monkeypatch.setattr(mobile_routes, "get_adelantos_page_by_empleado", lambda *args, **kw: ([], 0))
    client = _build_client(monkeypatch)
    resp = client.get("/api/v1/mobile/me/adelantos/resumen", headers=_auth_headers())
    body = resp.get_json()
    assert resp.status_code == 200
    assert body["periodo"] == "2026-04"
    assert body["ya_solicitado"] is False
    assert body["adelanto_mes_actual"] is None
    assert body["ultimo_adelanto"] is None
    assert body["total_historial"] == 0
    assert body["pendientes_total"] == 0


def test_mobile_adelantos_resumen_con_historial(monkeypatch):
    _setup_adelanto_auth(monkeypatch)
    monkeypatch.setattr(mobile_routes, "_today_iso", lambda: "2026-04-18")
    monkeypatch.setattr(mobile_routes, "get_adelanto_mes_actual_svc", lambda empleado_id, **kw: _FAKE_ADELANTO_ROW)
    captured = []

    def _fake_get_adelantos_page_by_empleado(empleado_id, page, per_page, **kw):
        captured.append({"empleado_id": empleado_id, "page": page, "per_page": per_page, "estado": kw.get("estado")})
        if kw.get("estado") == "pendiente":
            return ([_FAKE_ADELANTO_ROW], 1)
        return ([_FAKE_ADELANTO_OLD_ROW], 2)

    monkeypatch.setattr(mobile_routes, "get_adelantos_page_by_empleado", _fake_get_adelantos_page_by_empleado)
    client = _build_client(monkeypatch)
    resp = client.get("/api/v1/mobile/me/adelantos/resumen", headers=_auth_headers())
    body = resp.get_json()
    assert resp.status_code == 200
    assert body["ya_solicitado"] is True
    assert body["adelanto_mes_actual"]["id"] == 81
    assert body["ultimo_adelanto"]["id"] == 71
    assert body["ultimo_adelanto"]["resuelto_by_usuario"] == "rrhh"
    assert body["total_historial"] == 2
    assert body["pendientes_total"] == 1
    assert captured == [
        {"empleado_id": 10, "page": 1, "per_page": 1, "estado": None},
        {"empleado_id": 10, "page": 1, "per_page": 1, "estado": "pendiente"},
    ]


def test_mobile_adelantos_list_ok(monkeypatch):
    _setup_adelanto_auth(monkeypatch)
    captured = {}
    monkeypatch.setattr(
        mobile_routes,
        "get_adelantos_page_by_empleado",
        lambda empleado_id, page, per_page, **kw: (
            captured.update(
                {
                    "empleado_id": empleado_id,
                    "page": page,
                    "per_page": per_page,
                    "estado": kw.get("estado"),
                }
            )
            or ([_FAKE_ADELANTO_ROW], 1)
        ),
    )
    client = _build_client(monkeypatch)
    resp = client.get(
        "/api/v1/mobile/me/adelantos?page=2&per_page=5&estado=pendiente",
        headers=_auth_headers(),
    )
    body = resp.get_json()
    assert resp.status_code == 200
    assert body["total"] == 1
    assert body["page"] == 2
    assert body["per_page"] == 5
    assert body["items"][0]["id"] == 81
    assert body["items"][0]["resuelto_at"] is None
    assert captured == {
        "empleado_id": 10,
        "page": 2,
        "per_page": 5,
        "estado": "pendiente",
    }


def test_mobile_adelantos_list_estado_invalido(monkeypatch):
    _setup_adelanto_auth(monkeypatch)
    client = _build_client(monkeypatch)
    resp = client.get(
        "/api/v1/mobile/me/adelantos?estado=en_revision",
        headers=_auth_headers(),
    )
    assert resp.status_code == 400
    assert "estado invalido" in resp.get_json()["error"]


def test_mobile_adelantos_detail_ok(monkeypatch):
    _setup_adelanto_auth(monkeypatch)
    monkeypatch.setattr(mobile_routes, "get_adelanto_by_id", lambda _: _FAKE_ADELANTO_ROW)
    client = _build_client(monkeypatch)
    resp = client.get("/api/v1/mobile/me/adelantos/81", headers=_auth_headers())
    body = resp.get_json()
    assert resp.status_code == 200
    assert body["id"] == 81
    assert body["periodo"] == "2026-04"


def test_mobile_adelantos_detail_ajeno_retorna_404(monkeypatch):
    _setup_adelanto_auth(monkeypatch)
    monkeypatch.setattr(
        mobile_routes,
        "get_adelanto_by_id",
        lambda _: {**_FAKE_ADELANTO_ROW, "empleado_id": 999},
    )
    client = _build_client(monkeypatch)
    resp = client.get("/api/v1/mobile/me/adelantos/81", headers=_auth_headers())
    assert resp.status_code == 404
    assert "Adelanto no encontrado" in resp.get_json()["error"]


def test_mobile_adelantos_estado_con_solicitud(monkeypatch):
    _setup_adelanto_auth(monkeypatch)
    monkeypatch.setattr(mobile_routes, "_today_iso", lambda: "2026-04-17")
    monkeypatch.setattr(
        mobile_routes,
        "get_adelanto_mes_actual_svc",
        lambda empleado_id, **kw: _FAKE_ADELANTO_ROW,
    )
    client = _build_client(monkeypatch)
    resp = client.get("/api/v1/mobile/me/adelantos/estado", headers=_auth_headers())
    body = resp.get_json()
    assert resp.status_code == 200
    assert body["ya_solicitado"] is True
    assert body["adelanto"]["id"] == 81
    assert body["adelanto"]["estado"] == "pendiente"


def test_mobile_adelantos_create_ok(monkeypatch):
    _setup_adelanto_auth(monkeypatch)
    monkeypatch.setattr(mobile_routes, "_today_iso", lambda: "2026-04-17")
    created = {}
    monkeypatch.setattr(
        mobile_routes,
        "solicitar_adelanto_svc",
        lambda **kw: created.update(kw) or 81,
    )
    monkeypatch.setattr(mobile_routes, "get_adelanto_by_id", lambda _: _FAKE_ADELANTO_ROW)
    monkeypatch.setattr(mobile_routes, "create_audit", lambda *a: None)
    client = _build_client(monkeypatch)
    resp = client.post(
        "/api/v1/mobile/me/adelantos",
        json={},
        headers=_auth_headers(),
    )
    body = resp.get_json()
    assert resp.status_code == 201
    assert body["id"] == 81
    assert created["empleado_id"] == 10
    assert created["empresa_id"] == 3
    assert created["fecha_solicitud"] == "2026-04-17"


def test_mobile_adelantos_create_mes_duplicado_retorna_409(monkeypatch):
    _setup_adelanto_auth(monkeypatch)
    monkeypatch.setattr(mobile_routes, "_today_iso", lambda: "2026-04-17")
    monkeypatch.setattr(
        mobile_routes,
        "solicitar_adelanto_svc",
        lambda **kw: (_ for _ in ()).throw(
            mobile_routes.AdelantoAlreadyRequestedError("Ya solicitaste un adelanto en este mes.")
        ),
    )
    client = _build_client(monkeypatch)
    resp = client.post(
        "/api/v1/mobile/me/adelantos",
        json={},
        headers=_auth_headers(),
    )
    assert resp.status_code == 409
    assert "este mes" in resp.get_json()["error"]


# ---------------------------------------------------------------------------
# Pedidos de mercaderia
# ---------------------------------------------------------------------------

_FAKE_PEDIDO_MERCADERIA_ROW = {
    "id": 91,
    "empleado_id": 10,
    "periodo_year": 2026,
    "periodo_month": 4,
    "fecha_pedido": "2026-04-18",
    "estado": "pendiente",
    "cantidad_items": 2,
    "total_bultos": 3,
    "created_at": datetime.datetime(2026, 4, 18, 9, 30, 0),
    "resuelto_at": None,
    "resuelto_by_usuario": None,
    "motivo_rechazo": None,
    "items": [
        {
            "id": 1,
            "articulo_id": 5,
            "cantidad_bultos": 2,
            "codigo_articulo_snapshot": "A1",
            "descripcion_snapshot": "Gaseosa",
            "unidades_por_bulto_snapshot": 8,
        },
        {
            "id": 2,
            "articulo_id": 6,
            "cantidad_bultos": 1,
            "codigo_articulo_snapshot": "A2",
            "descripcion_snapshot": "Agua",
            "unidades_por_bulto_snapshot": 12,
        },
    ],
}

_FAKE_PEDIDO_MERCADERIA_OLD_ROW = {
    **_FAKE_PEDIDO_MERCADERIA_ROW,
    "id": 81,
    "periodo_year": 2026,
    "periodo_month": 3,
    "fecha_pedido": "2026-03-14",
    "estado": "aprobado",
    "created_at": datetime.datetime(2026, 3, 14, 8, 45, 0),
    "resuelto_at": datetime.datetime(2026, 3, 15, 11, 0, 0),
    "resuelto_by_usuario": "rrhh",
}


def _setup_pedidos_mercaderia_auth(monkeypatch):
    monkeypatch.setattr(jwt_guard, "verificar_token", lambda token: {"empleado_id": 10})
    monkeypatch.setattr(mobile_routes, "get_empleado_by_id", lambda eid: _FAKE_EMPLEADO_JUST)


def test_mobile_pedidos_mercaderia_resumen_con_historial(monkeypatch):
    _setup_pedidos_mercaderia_auth(monkeypatch)
    monkeypatch.setattr(mobile_routes, "_today_iso", lambda: "2026-04-18")
    monkeypatch.setattr(
        mobile_routes,
        "get_pedido_mercaderia_mes_actual_svc",
        lambda empleado_id, **kw: _FAKE_PEDIDO_MERCADERIA_ROW,
    )

    def _fake_get_pedidos(empleado_id, page, per_page, **kw):
        if kw.get("estado") == "pendiente":
            return ([_FAKE_PEDIDO_MERCADERIA_ROW], 1)
        if kw.get("estado") == "aprobado":
            return ([_FAKE_PEDIDO_MERCADERIA_OLD_ROW], 1)
        return ([_FAKE_PEDIDO_MERCADERIA_ROW], 2)

    monkeypatch.setattr(mobile_routes, "get_pedidos_mercaderia_page_by_empleado", _fake_get_pedidos)
    client = _build_client(monkeypatch)
    resp = client.get("/api/v1/mobile/me/pedidos-mercaderia/resumen", headers=_auth_headers())
    body = resp.get_json()
    assert resp.status_code == 200
    assert body["ya_solicitado"] is True
    assert body["pedido_mes_actual"]["id"] == 91
    assert body["ultimo_pedido_aprobado"]["id"] == 81
    assert body["historial_aprobados_total"] == 1
    assert body["pendientes_total"] == 1


def test_mobile_pedidos_mercaderia_articulos_ok(monkeypatch):
    _setup_pedidos_mercaderia_auth(monkeypatch)
    captured = {}
    monkeypatch.setattr(
        mobile_routes,
        "get_articulos_catalogo_pedidos_page",
        lambda page, per_page, **kw: (
            captured.update({"page": page, "per_page": per_page, "search": kw.get("search")})
            or ([
                {
                    "id": 5,
                    "codigo_articulo": "A1",
                    "descripcion": "Gaseosa",
                    "unidades_por_bulto": 8,
                    "bultos_por_pallet": 72,
                    "marca": "Marca",
                    "familia": "Familia",
                    "sabor": "Cola",
                    "division": "Bebidas",
                }
            ], 1)
        ),
    )
    client = _build_client(monkeypatch)
    resp = client.get("/api/v1/mobile/me/pedidos-mercaderia/articulos?q=gas&page=2&per_page=5", headers=_auth_headers())
    body = resp.get_json()
    assert resp.status_code == 200
    assert body["items"][0]["codigo_articulo"] == "A1"
    assert captured == {"page": 2, "per_page": 5, "search": "gas"}


def test_mobile_pedidos_mercaderia_list_ok(monkeypatch):
    _setup_pedidos_mercaderia_auth(monkeypatch)
    monkeypatch.setattr(
        mobile_routes,
        "get_pedidos_mercaderia_page_by_empleado",
        lambda empleado_id, page, per_page, **kw: ([_FAKE_PEDIDO_MERCADERIA_ROW], 1),
    )
    client = _build_client(monkeypatch)
    resp = client.get("/api/v1/mobile/me/pedidos-mercaderia?estado=pendiente", headers=_auth_headers())
    body = resp.get_json()
    assert resp.status_code == 200
    assert body["items"][0]["id"] == 91
    assert body["items"][0]["items"][0]["codigo_articulo"] == "A1"


def test_mobile_pedidos_mercaderia_detail_ok(monkeypatch):
    _setup_pedidos_mercaderia_auth(monkeypatch)
    monkeypatch.setattr(mobile_routes, "get_pedido_mercaderia_by_id", lambda _: _FAKE_PEDIDO_MERCADERIA_ROW)
    client = _build_client(monkeypatch)
    resp = client.get("/api/v1/mobile/me/pedidos-mercaderia/91", headers=_auth_headers())
    body = resp.get_json()
    assert resp.status_code == 200
    assert body["id"] == 91
    assert body["items"][1]["descripcion"] == "Agua"


def test_mobile_pedidos_mercaderia_create_ok(monkeypatch):
    _setup_pedidos_mercaderia_auth(monkeypatch)
    monkeypatch.setattr(mobile_routes, "_today_iso", lambda: "2026-04-18")
    created = {}
    monkeypatch.setattr(
        mobile_routes,
        "solicitar_pedido_mercaderia_svc",
        lambda **kw: created.update(kw) or 91,
    )
    monkeypatch.setattr(mobile_routes, "get_pedido_mercaderia_by_id", lambda _: _FAKE_PEDIDO_MERCADERIA_ROW)
    monkeypatch.setattr(mobile_routes, "create_audit", lambda *a: None)
    client = _build_client(monkeypatch)
    resp = client.post(
        "/api/v1/mobile/me/pedidos-mercaderia",
        json={"items": [{"articulo_id": 5, "cantidad_bultos": 2}]},
        headers=_auth_headers(),
    )
    body = resp.get_json()
    assert resp.status_code == 201
    assert body["id"] == 91
    assert created["items"] == [{"articulo_id": 5, "cantidad_bultos": 2}]


def test_mobile_pedidos_mercaderia_update_ok(monkeypatch):
    _setup_pedidos_mercaderia_auth(monkeypatch)
    captured = {}
    monkeypatch.setattr(
        mobile_routes,
        "editar_pedido_mercaderia_svc",
        lambda pedido_id, **kw: captured.update({"pedido_id": pedido_id, "empleado_id": kw.get("empleado_id"), "items": kw.get("items")}),
    )
    monkeypatch.setattr(mobile_routes, "get_pedido_mercaderia_by_id", lambda _: _FAKE_PEDIDO_MERCADERIA_ROW)
    monkeypatch.setattr(mobile_routes, "create_audit", lambda *a: None)
    client = _build_client(monkeypatch)
    resp = client.put(
        "/api/v1/mobile/me/pedidos-mercaderia/91",
        json={"items": [{"articulo_id": 5, "cantidad_bultos": 4}]},
        headers=_auth_headers(),
    )
    assert resp.status_code == 200
    assert captured == {"pedido_id": 91, "empleado_id": 10, "items": [{"articulo_id": 5, "cantidad_bultos": 4}]}


def test_mobile_pedidos_mercaderia_cancel_ok(monkeypatch):
    _setup_pedidos_mercaderia_auth(monkeypatch)
    captured = {}
    monkeypatch.setattr(
        mobile_routes,
        "cancelar_pedido_mercaderia_svc",
        lambda pedido_id, **kw: captured.update({"pedido_id": pedido_id, "empleado_id": kw.get("empleado_id")}),
    )
    monkeypatch.setattr(
        mobile_routes,
        "get_pedido_mercaderia_by_id",
        lambda _: {**_FAKE_PEDIDO_MERCADERIA_ROW, "estado": "cancelado"},
    )
    monkeypatch.setattr(mobile_routes, "create_audit", lambda *a: None)
    client = _build_client(monkeypatch)
    resp = client.delete("/api/v1/mobile/me/pedidos-mercaderia/91", headers=_auth_headers())
    body = resp.get_json()
    assert resp.status_code == 200
    assert body["estado"] == "cancelado"
    assert captured == {"pedido_id": 91, "empleado_id": 10}


# ---------------------------------------------------------------------------
# Horarios asignaciones
# ---------------------------------------------------------------------------

_FAKE_ASIGNACION = {
    "id": 3,
    "empleado_id": 10,
    "horario_id": 5,
    "horario_nombre": "Turno Mañana",
    "fecha_desde": "2025-01-01",
    "fecha_hasta": None,
}

_FAKE_DIAS = [
    {"dia_semana": 1},
    {"dia_semana": 2},
    {"dia_semana": 3},
    {"dia_semana": 4},
    {"dia_semana": 5},
]


def _setup_horario_auth(monkeypatch):
    monkeypatch.setattr(jwt_guard, "verificar_token", lambda token: {"empleado_id": 10})
    monkeypatch.setattr(mobile_routes, "get_empleado_by_id", lambda eid: _FAKE_EMPLEADO_JUST)


def test_mobile_horarios_asignaciones_list_ok(monkeypatch):
    _setup_horario_auth(monkeypatch)
    monkeypatch.setattr(
        mobile_routes, "get_horario_historial_by_empleado",
        lambda eid: [_FAKE_ASIGNACION]
    )
    client = _build_client(monkeypatch)
    resp = client.get("/api/v1/mobile/me/horarios-asignaciones", headers=_auth_headers())
    assert resp.status_code == 200
    data = resp.get_json()
    assert len(data) == 1
    assert data[0]["horario_nombre"] == "Turno Mañana"
    assert data[0]["fecha_desde"] == "2025-01-01"
    assert data[0]["fecha_hasta"] is None


def test_mobile_horarios_asignaciones_list_vacia(monkeypatch):
    _setup_horario_auth(monkeypatch)
    monkeypatch.setattr(
        mobile_routes, "get_horario_historial_by_empleado",
        lambda eid: []
    )
    client = _build_client(monkeypatch)
    resp = client.get("/api/v1/mobile/me/horarios-asignaciones", headers=_auth_headers())
    assert resp.status_code == 200
    assert resp.get_json() == []


def test_mobile_horarios_asignaciones_actual_ok(monkeypatch):
    _setup_horario_auth(monkeypatch)
    monkeypatch.setattr(
        mobile_routes, "get_horario_actual_by_empleado",
        lambda eid: _FAKE_ASIGNACION
    )
    monkeypatch.setattr(
        mobile_routes, "get_dias_by_horario",
        lambda hid: _FAKE_DIAS
    )
    client = _build_client(monkeypatch)
    resp = client.get("/api/v1/mobile/me/horarios-asignaciones/actual", headers=_auth_headers())
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["asignacion"]["horario_nombre"] == "Turno Mañana"
    assert len(data["dias"]) == 5
    assert data["dias"][0]["dia_semana"] == 1


def test_mobile_horarios_asignaciones_actual_sin_asignacion(monkeypatch):
    _setup_horario_auth(monkeypatch)
    monkeypatch.setattr(
        mobile_routes, "get_horario_actual_by_empleado",
        lambda eid: None
    )
    client = _build_client(monkeypatch)
    resp = client.get("/api/v1/mobile/me/horarios-asignaciones/actual", headers=_auth_headers())
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["asignacion"] is None
    assert data["dias"] == []


# ---------------------------------------------------------------------------
# Francos
# ---------------------------------------------------------------------------

_FAKE_FRANCO_ROW = {
    "id": 12,
    "empleado_id": 10,
    "empresa_id": 3,
    "fecha": "2026-03-10",
    "motivo": "Franco compensatorio",
}


def _setup_franco_auth(monkeypatch):
    monkeypatch.setattr(jwt_guard, "verificar_token", lambda token: {"empleado_id": 10})
    monkeypatch.setattr(mobile_routes, "get_empleado_by_id", lambda eid: _FAKE_EMPLEADO_JUST)


def test_mobile_francos_list_ok(monkeypatch):
    _setup_franco_auth(monkeypatch)
    monkeypatch.setattr(
        mobile_routes, "get_francos_page_by_empleado",
        lambda eid, page, per_page, **kw: ([_FAKE_FRANCO_ROW], 1)
    )
    client = _build_client(monkeypatch)
    resp = client.get("/api/v1/mobile/me/francos", headers=_auth_headers())
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["total"] == 1
    assert data["items"][0]["motivo"] == "Franco compensatorio"
    assert data["items"][0]["fecha"] == "2026-03-10"


def test_mobile_francos_list_con_filtro_fechas(monkeypatch):
    _setup_franco_auth(monkeypatch)
    captured = {}
    def _fake_page(eid, page, per_page, **kw):
        captured.update(kw)
        return [], 0
    monkeypatch.setattr(mobile_routes, "get_francos_page_by_empleado", _fake_page)
    client = _build_client(monkeypatch)
    resp = client.get(
        "/api/v1/mobile/me/francos?desde=2026-03-01&hasta=2026-03-31",
        headers=_auth_headers()
    )
    assert resp.status_code == 200
    assert captured["fecha_desde"] == "2026-03-01"
    assert captured["fecha_hasta"] == "2026-03-31"


def test_mobile_francos_detail_ok(monkeypatch):
    _setup_franco_auth(monkeypatch)
    monkeypatch.setattr(mobile_routes, "get_franco_by_id", lambda _: _FAKE_FRANCO_ROW)
    client = _build_client(monkeypatch)
    resp = client.get("/api/v1/mobile/me/francos/12", headers=_auth_headers())
    assert resp.status_code == 200
    assert resp.get_json()["id"] == 12


def test_mobile_francos_detail_ajeno_retorna_404(monkeypatch):
    _setup_franco_auth(monkeypatch)
    monkeypatch.setattr(
        mobile_routes, "get_franco_by_id",
        lambda _: {**_FAKE_FRANCO_ROW, "empleado_id": 999}
    )
    client = _build_client(monkeypatch)
    resp = client.get("/api/v1/mobile/me/francos/12", headers=_auth_headers())
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Legajo eventos
# ---------------------------------------------------------------------------

_FAKE_EVENTO_ROW = {
    "id": 20,
    "empleado_id": 10,
    "empresa_id": 3,
    "tipo_id": 2,
    "tipo_codigo": "SANCION",
    "tipo_nombre": "Sanción",
    "fecha_evento": "2026-02-15",
    "fecha_desde": None,
    "fecha_hasta": None,
    "titulo": "Llegada tarde reiterada",
    "descripcion": "Tercer episodio en el mes",
    "estado": "vigente",
    "severidad": "leve",
}


def _setup_evento_auth(monkeypatch):
    monkeypatch.setattr(jwt_guard, "verificar_token", lambda token: {"empleado_id": 10})
    monkeypatch.setattr(mobile_routes, "get_empleado_by_id", lambda eid: _FAKE_EMPLEADO_JUST)


def test_mobile_legajo_eventos_list_ok(monkeypatch):
    _setup_evento_auth(monkeypatch)
    monkeypatch.setattr(
        mobile_routes, "get_eventos_page",
        lambda page, per_page, **kw: ([_FAKE_EVENTO_ROW], 1)
    )
    client = _build_client(monkeypatch)
    resp = client.get("/api/v1/mobile/me/legajo/eventos", headers=_auth_headers())
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["total"] == 1
    assert data["items"][0]["tipo_codigo"] == "SANCION"
    assert data["items"][0]["titulo"] == "Llegada tarde reiterada"


def test_mobile_legajo_eventos_list_estado_invalido(monkeypatch):
    _setup_evento_auth(monkeypatch)
    client = _build_client(monkeypatch)
    resp = client.get(
        "/api/v1/mobile/me/legajo/eventos?estado=invalido",
        headers=_auth_headers()
    )
    assert resp.status_code == 400
    assert "estado" in resp.get_json()["error"]


def test_mobile_legajo_eventos_list_filtro_estado_valido(monkeypatch):
    _setup_evento_auth(monkeypatch)
    captured = {}
    def _fake_page(page, per_page, **kw):
        captured.update(kw)
        return [], 0
    monkeypatch.setattr(mobile_routes, "get_eventos_page", _fake_page)
    client = _build_client(monkeypatch)
    resp = client.get(
        "/api/v1/mobile/me/legajo/eventos?estado=vigente",
        headers=_auth_headers()
    )
    assert resp.status_code == 200
    assert captured["estado"] == "vigente"
    assert captured["empleado_id"] == 10


def test_mobile_legajo_eventos_detail_ok(monkeypatch):
    _setup_evento_auth(monkeypatch)
    monkeypatch.setattr(mobile_routes, "get_evento_by_id", lambda _: _FAKE_EVENTO_ROW)
    client = _build_client(monkeypatch)
    resp = client.get("/api/v1/mobile/me/legajo/eventos/20", headers=_auth_headers())
    assert resp.status_code == 200
    assert resp.get_json()["id"] == 20
    assert resp.get_json()["fecha_desde"] is None


def test_mobile_legajo_eventos_detail_ajeno_retorna_404(monkeypatch):
    _setup_evento_auth(monkeypatch)
    monkeypatch.setattr(
        mobile_routes, "get_evento_by_id",
        lambda _: {**_FAKE_EVENTO_ROW, "empleado_id": 999}
    )
    client = _build_client(monkeypatch)
    resp = client.get("/api/v1/mobile/me/legajo/eventos/20", headers=_auth_headers())
    assert resp.status_code == 404
