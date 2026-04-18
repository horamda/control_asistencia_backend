import app as app_module
import web.auth.decorators as auth_decorators
import web.adelantos.adelantos_routes as adelantos_routes


def _build_client(monkeypatch):
    monkeypatch.setattr(app_module, "init_db", lambda: None)
    app = app_module.create_app()
    app.config["TESTING"] = True
    app.config["WTF_CSRF_ENABLED"] = False
    return app.test_client()


def _login(client, role="admin"):
    with client.session_transaction() as sess:
        sess["user_id"] = 99
        sess["role"] = role
        sess["nombre"] = "Test"


def _build_authed_client(monkeypatch):
    monkeypatch.setattr(auth_decorators, "has_role", lambda user_id, role: True)
    client = _build_client(monkeypatch)
    _login(client)
    return client


def _stub_empleados():
    return [{"id": 1, "nombre": "Ana", "apellido": "Lopez", "dni": "12345"}]


def test_adelantos_listado_requiere_login(monkeypatch):
    monkeypatch.setattr(auth_decorators, "has_role", lambda user_id, role: True)
    client = _build_client(monkeypatch)
    resp = client.get("/adelantos/")
    assert resp.status_code in (302, 403)


def test_adelantos_listado_ok(monkeypatch):
    monkeypatch.setattr(
        adelantos_routes,
        "get_page",
        lambda **kw: (
            [
                {
                    "id": 81,
                    "empresa_nombre": "Acme",
                    "apellido": "Lopez",
                    "nombre": "Ana",
                    "dni": "12345",
                    "periodo_year": 2026,
                    "periodo_month": 4,
                    "fecha_solicitud": "2026-04-17",
                    "estado": "aprobado",
                    "resuelto_by_usuario": "admin",
                    "resuelto_at": "2026-04-17 10:00:00",
                }
            ],
            1,
        ),
    )
    monkeypatch.setattr(adelantos_routes, "get_summary", lambda **kw: {"total": 0, "pendientes": 0, "aprobados": 0, "rechazados": 0, "cancelados": 0})
    monkeypatch.setattr(adelantos_routes, "get_empleados", lambda **kw: _stub_empleados())
    client = _build_authed_client(monkeypatch)
    resp = client.get("/adelantos/")
    assert resp.status_code == 200
    assert b"Adelantos" in resp.data
    assert b"admin" in resp.data


def test_adelantos_listado_envia_filtros(monkeypatch):
    captured = {}

    def _fake_get_page(**kw):
        captured.update(kw)
        return ([], 0)

    monkeypatch.setattr(adelantos_routes, "get_page", _fake_get_page)
    monkeypatch.setattr(adelantos_routes, "get_summary", lambda **kw: {"total": 0, "pendientes": 0, "aprobados": 0, "rechazados": 0, "cancelados": 0})
    monkeypatch.setattr(adelantos_routes, "get_empleados", lambda **kw: _stub_empleados())
    client = _build_authed_client(monkeypatch)
    resp = client.get("/adelantos/?empleado_id=1&estado=pendiente&anio=2026&mes=4&q=lopez")
    assert resp.status_code == 200
    assert captured["empleado_id"] == 1
    assert captured["estado"] == "pendiente"
    assert captured["periodo_year"] == 2026
    assert captured["periodo_month"] == 4
    assert captured["search"] == "lopez"


def test_adelantos_listado_mes_invalido_muestra_error(monkeypatch):
    monkeypatch.setattr(adelantos_routes, "get_page", lambda **kw: ([], 0))
    monkeypatch.setattr(adelantos_routes, "get_summary", lambda **kw: {"total": 0, "pendientes": 0, "aprobados": 0, "rechazados": 0, "cancelados": 0})
    monkeypatch.setattr(adelantos_routes, "get_empleados", lambda **kw: _stub_empleados())
    client = _build_authed_client(monkeypatch)
    resp = client.get("/adelantos/?mes=15")
    assert resp.status_code == 200
    assert b"Mes invalido" in resp.data


def test_adelantos_export_csv_ok(monkeypatch):
    captured = {}

    def _fake_get_export(**kw):
        captured.update(kw)
        return [
            {
                "id": 81,
                "empresa_nombre": "Acme",
                "apellido": "Lopez",
                "nombre": "Ana",
                "dni": "12345",
                "periodo_year": 2026,
                "periodo_month": 4,
                "fecha_solicitud": "2026-04-17",
                "estado": "pendiente",
                "created_at": "2026-04-17 09:30:00",
                "resuelto_by_usuario": "rrhh",
                "resuelto_at": "2026-04-17 11:00:00",
            }
        ]

    monkeypatch.setattr(adelantos_routes, "get_export", _fake_get_export)
    client = _build_authed_client(monkeypatch)
    resp = client.get("/adelantos/export.csv?estado=pendiente&anio=2026&mes=4")
    assert resp.status_code == 200
    assert resp.mimetype == "text/csv"
    assert captured["estado"] == "pendiente"
    assert captured["periodo_year"] == 2026
    assert captured["periodo_month"] == 4
    assert b"Acme" in resp.data
    assert b"rrhh" in resp.data


def test_adelantos_export_csv_mes_invalido_redirige(monkeypatch):
    client = _build_authed_client(monkeypatch)
    resp = client.get("/adelantos/export.csv?mes=15")
    assert resp.status_code == 302
    assert "/adelantos/" in resp.headers["Location"]


def test_adelantos_aprobar_redirige_con_msg(monkeypatch):
    captured = {}
    monkeypatch.setattr(
        adelantos_routes,
        "aprobar_adelanto",
        lambda adelanto_id, **kw: captured.update({"adelanto_id": adelanto_id, "actor_id": kw.get("actor_id")}),
    )
    monkeypatch.setattr(adelantos_routes, "log_audit", lambda *args, **kwargs: None)
    client = _build_authed_client(monkeypatch)
    resp = client.post("/adelantos/aprobar/81")
    assert resp.status_code == 302
    assert "msg=" in resp.headers["Location"]
    assert captured == {"adelanto_id": 81, "actor_id": 99}


def test_adelantos_aprobar_error_redirige_con_error(monkeypatch):
    monkeypatch.setattr(
        adelantos_routes,
        "aprobar_adelanto",
        lambda adelanto_id, **kw: (_ for _ in ()).throw(ValueError("No se puede aprobar")),
    )
    client = _build_authed_client(monkeypatch)
    resp = client.post("/adelantos/aprobar/81")
    assert resp.status_code == 302
    assert "error=" in resp.headers["Location"]


def test_adelantos_rechazar_redirige_con_msg(monkeypatch):
    captured = {}
    monkeypatch.setattr(
        adelantos_routes,
        "rechazar_adelanto",
        lambda adelanto_id, **kw: captured.update({"adelanto_id": adelanto_id, "actor_id": kw.get("actor_id")}),
    )
    monkeypatch.setattr(adelantos_routes, "log_audit", lambda *args, **kwargs: None)
    client = _build_authed_client(monkeypatch)
    resp = client.post("/adelantos/rechazar/81")
    assert resp.status_code == 302
    assert "msg=" in resp.headers["Location"]
    assert captured == {"adelanto_id": 81, "actor_id": 99}
