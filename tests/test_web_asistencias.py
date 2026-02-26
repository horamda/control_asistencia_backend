import app as app_module
import web.auth.decorators as auth_decorators
import web.asistencias.asistencias_routes as asistencias_routes


def _build_client(monkeypatch):
    monkeypatch.setattr(app_module, "init_db", lambda: None)
    app = app_module.create_app()
    app.config["TESTING"] = True
    app.config["WTF_CSRF_ENABLED"] = False
    return app.test_client()


def _login_session(client):
    with client.session_transaction() as sess:
        sess["user_id"] = 99


def test_asistencias_get_ok(monkeypatch):
    client = _build_client(monkeypatch)
    _login_session(client)
    monkeypatch.setattr(auth_decorators, "has_role", lambda actor_id, role: True)
    monkeypatch.setattr(asistencias_routes, "get_page", lambda *args, **kwargs: ([], 0))
    monkeypatch.setattr(asistencias_routes, "get_empleados", lambda include_inactive=True: [])

    resp = client.get("/asistencias/")
    assert resp.status_code == 200
    assert b"Generar ausentes por rango" in resp.data


def test_generar_ausentes_dia(monkeypatch):
    client = _build_client(monkeypatch)
    _login_session(client)
    monkeypatch.setattr(auth_decorators, "has_role", lambda actor_id, role: True)
    captured = {}

    def _fake_generar_ausentes(fecha):
        captured["fecha"] = fecha
        return 0, []

    monkeypatch.setattr(asistencias_routes, "generar_ausentes", _fake_generar_ausentes)
    monkeypatch.setattr(asistencias_routes, "generar_ausentes_rango", lambda *args, **kwargs: (0, []))

    resp = client.post(
        "/asistencias/generar-ausentes",
        data={"modo": "dia", "fecha": "2026-02-20"},
        follow_redirects=False,
    )
    assert resp.status_code == 302
    assert "fecha_desde=2026-02-20" in resp.headers["Location"]
    assert captured["fecha"] == "2026-02-20"


def test_generar_ausentes_rango(monkeypatch):
    client = _build_client(monkeypatch)
    _login_session(client)
    monkeypatch.setattr(auth_decorators, "has_role", lambda actor_id, role: True)
    captured = {}

    def _fake_generar_ausentes_rango(fecha_desde, fecha_hasta):
        captured["desde"] = fecha_desde
        captured["hasta"] = fecha_hasta
        return 0, []

    monkeypatch.setattr(asistencias_routes, "generar_ausentes", lambda *args, **kwargs: (0, []))
    monkeypatch.setattr(asistencias_routes, "generar_ausentes_rango", _fake_generar_ausentes_rango)

    resp = client.post(
        "/asistencias/generar-ausentes",
        data={"modo": "rango", "fecha_desde": "2026-02-01", "fecha_hasta": "2026-02-10"},
        follow_redirects=False,
    )
    assert resp.status_code == 302
    assert "fecha_desde=2026-02-01" in resp.headers["Location"]
    assert "fecha_hasta=2026-02-10" in resp.headers["Location"]
    assert captured["desde"] == "2026-02-01"
    assert captured["hasta"] == "2026-02-10"


def test_historial_marcas_get_ok(monkeypatch):
    client = _build_client(monkeypatch)
    _login_session(client)
    monkeypatch.setattr(auth_decorators, "has_role", lambda actor_id, role: True)
    monkeypatch.setattr(asistencias_routes, "get_marcas_admin_page", lambda **kwargs: ([], 0))
    monkeypatch.setattr(asistencias_routes, "get_empleados", lambda include_inactive=True: [])
    monkeypatch.setattr(asistencias_routes, "get_empresas", lambda include_inactive=True: [])

    resp = client.get("/asistencias/marcas")
    assert resp.status_code == 200
    assert b"Historial de marcas" in resp.data


def test_historial_marcas_csv_ok(monkeypatch):
    client = _build_client(monkeypatch)
    _login_session(client)
    monkeypatch.setattr(auth_decorators, "has_role", lambda actor_id, role: True)
    monkeypatch.setattr(
        asistencias_routes,
        "get_marcas_admin_export",
        lambda **kwargs: [
            {
                "id": 1,
                "empresa_nombre": "Empresa Test",
                "apellido": "Perez",
                "nombre": "Ana",
                "dni": "30111222",
                "fecha": "2026-02-21",
                "hora": "08:00:00",
                "accion": "ingreso",
                "tipo_marca": "jornada",
                "metodo": "qr",
                "gps_ok": 1,
                "gps_distancia_m": 3.2,
                "gps_tolerancia_m": 30.0,
                "lat": -34.6,
                "lon": -58.4,
                "estado": "ok",
                "observaciones": "",
                "fecha_creacion": "2026-02-21 08:00:01",
            }
        ],
    )

    resp = client.get("/asistencias/marcas.csv")
    assert resp.status_code == 200
    assert "text/csv" in resp.headers["Content-Type"]
    assert "historial_marcas_" in resp.headers["Content-Disposition"]
    assert b"Empresa Test" in resp.data


def test_historial_marcas_backfill_post_ok(monkeypatch):
    client = _build_client(monkeypatch)
    _login_session(client)
    monkeypatch.setattr(auth_decorators, "has_role", lambda actor_id, role: True)
    monkeypatch.setattr(asistencias_routes, "backfill_marcas", lambda: (4, 2))

    resp = client.post(
        "/asistencias/marcas/backfill",
        data={
            "page": "1",
            "per": "20",
            "empresa_id": "",
            "empleado_id": "",
            "fecha_desde": "",
            "fecha_hasta": "",
            "tipo_marca": "",
            "accion": "",
            "metodo": "",
            "gps_ok": "",
            "q": "",
        },
        follow_redirects=False,
    )
    assert resp.status_code == 302
    assert "/asistencias/marcas" in resp.headers["Location"]
    assert "backfill_ingresos=4" in resp.headers["Location"]
    assert "backfill_egresos=2" in resp.headers["Location"]
