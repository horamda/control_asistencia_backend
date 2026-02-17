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
        json={"metodo": "qr"},
    )
    assert resp.status_code == 400
    assert "qr_token requerido" in resp.get_json()["error"]


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
    monkeypatch.setattr(mobile_routes, "register_entrada", lambda **kwargs: 77)

    resp = client.post(
        "/api/v1/mobile/me/fichadas/scan",
        headers={"Authorization": "Bearer abc"},
        json={"qr_token": "qrauto", "lat": -34.6037, "lon": -58.3816},
    )
    body = resp.get_json()
    assert resp.status_code == 201
    assert body["accion"] == "ingreso"
    assert body["id"] == 77
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
    monkeypatch.setattr(mobile_routes, "register_salida", lambda **kwargs: 10)

    resp = client.post(
        "/api/v1/mobile/me/fichadas/scan",
        headers={"Authorization": "Bearer abc"},
        json={"qr_token": "qrauto", "lat": -34.6037, "lon": -58.3816},
    )
    body = resp.get_json()
    assert resp.status_code == 200
    assert body["accion"] == "egreso"
    assert body["id"] == 10
    assert body["gps_ok"] is True


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

    resp = client.post(
        "/api/v1/mobile/me/fichadas/scan",
        headers={"Authorization": "Bearer abc"},
        json={"qr_token": "qrauto", "lat": -34.6037, "lon": -58.3816},
    )
    body = resp.get_json()
    assert resp.status_code == 403
    assert body["gps_ok"] is False
