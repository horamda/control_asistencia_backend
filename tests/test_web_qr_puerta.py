import app as app_module
import web.auth.decorators as auth_decorators
import web.qr_puerta.qr_puerta_routes as qr_routes


def _build_client(monkeypatch):
    monkeypatch.setattr(app_module, "init_db", lambda: None)
    app = app_module.create_app()
    app.config["TESTING"] = True
    app.config["WTF_CSRF_ENABLED"] = False
    return app.test_client()


def _login_session(client):
    with client.session_transaction() as sess:
        sess["user_id"] = 99


def test_qr_puerta_requires_login(monkeypatch):
    client = _build_client(monkeypatch)
    monkeypatch.setattr(auth_decorators, "has_role", lambda actor_id, role: True)

    resp = client.get("/qr-puerta/")
    assert resp.status_code == 302
    assert "/login" in resp.headers["Location"]


def test_qr_puerta_get_ok(monkeypatch):
    client = _build_client(monkeypatch)
    _login_session(client)
    monkeypatch.setattr(auth_decorators, "has_role", lambda actor_id, role: True)
    monkeypatch.setattr(
        qr_routes,
        "get_empresas",
        lambda include_inactive=False: [{"id": 1, "razon_social": "Empresa Demo"}],
    )
    monkeypatch.setattr(
        qr_routes,
        "get_sucursales",
        lambda include_inactive=False: [
            {
                "id": 10,
                "empresa_id": 1,
                "empresa_nombre": "Empresa Demo",
                "nombre": "Casa Central",
                "latitud": -34.6037,
                "longitud": -58.3816,
                "radio_permitido_m": 80,
            }
        ],
    )
    monkeypatch.setattr(qr_routes, "get_qr_historial_recent", lambda limit=30: [])

    resp = client.get("/qr-puerta/")
    assert resp.status_code == 200
    assert b"QR de puerta" in resp.data


def test_qr_puerta_post_ok(monkeypatch):
    client = _build_client(monkeypatch)
    _login_session(client)
    monkeypatch.setattr(auth_decorators, "has_role", lambda actor_id, role: True)
    monkeypatch.setattr(
        qr_routes,
        "get_empresas",
        lambda include_inactive=False: [{"id": 1, "razon_social": "Empresa Demo"}],
    )
    monkeypatch.setattr(
        qr_routes,
        "get_sucursales",
        lambda include_inactive=False: [
            {
                "id": 10,
                "empresa_id": 1,
                "empresa_nombre": "Empresa Demo",
                "nombre": "Casa Central",
                "latitud": -34.6037,
                "longitud": -58.3816,
                "radio_permitido_m": 80,
            }
        ],
    )
    captured_payload = {}
    captured_historial = {}

    def _fake_generar_token_qr(payload, vigencia_segundos=120):
        captured_payload.update(payload)
        return "qr-token-demo"

    monkeypatch.setattr(qr_routes, "generar_token_qr", _fake_generar_token_qr)
    monkeypatch.setattr(qr_routes, "build_qr_png_base64", lambda content: "data:image/png;base64,AAA")
    monkeypatch.setattr(qr_routes, "log_audit", lambda *args, **kwargs: None)
    def _fake_create_qr_historial(**kwargs):
        captured_historial.update(kwargs)
        return 55

    monkeypatch.setattr(qr_routes, "create_qr_historial", _fake_create_qr_historial)
    monkeypatch.setattr(
        qr_routes,
        "get_qr_historial_recent",
        lambda limit=30: [
            {
                "id": 55,
                "empresa_nombre": "Empresa Demo",
                "sucursal_nombre": "Casa Central",
                "tolerancia_m": 80,
                "vigencia_dias": 30,
                "expira_at": "2026-03-20 12:00:00",
                "fecha": "2026-02-18 12:00:00",
            }
        ],
    )

    resp = client.post(
        "/qr-puerta/",
        data={
            "empresa_id": "1",
            "sucursal_id": "10",
            "tolerancia_m": "80",
            "vigencia_dias": "30",
            "tipo_marca": "almuerzo",
        },
        follow_redirects=True,
    )
    assert resp.status_code == 200
    assert b"QR generado" in resp.data
    assert b"Tipo de marca" in resp.data
    assert b"almuerzo" in resp.data
    assert b"data:image/png;base64,AAA" in resp.data
    assert b"Historial de QRs generados" in resp.data
    assert b"Reimprimir" in resp.data
    assert captured_payload["tipo_marca"] == "almuerzo"
    assert captured_historial["tipo_marca"] == "almuerzo"


def test_qr_puerta_reimprimir_ok(monkeypatch):
    client = _build_client(monkeypatch)
    _login_session(client)
    monkeypatch.setattr(auth_decorators, "has_role", lambda actor_id, role: True)
    monkeypatch.setattr(
        qr_routes,
        "get_qr_historial_by_id",
        lambda historial_id: {
            "id": historial_id,
            "empresa_id": 1,
            "empresa_nombre": "Empresa Demo",
            "sucursal_id": 10,
            "sucursal_nombre": "Casa Central",
            "tipo_marca": "almuerzo",
            "tolerancia_m": 80,
            "fecha": "2026-02-18 12:00:00",
            "qr_token": "qr-token-demo",
        },
    )
    monkeypatch.setattr(qr_routes, "build_qr_png_base64", lambda content: "data:image/png;base64,AAA")

    resp = client.get("/qr-puerta/reimprimir/55")
    assert resp.status_code == 200
    assert b"Tolerancia GPS" in resp.data
    assert b"Tipo de marca" in resp.data
    assert b"almuerzo" in resp.data
    assert b"80 m" in resp.data
    assert b"data:image/png;base64,AAA" in resp.data
