import app as app_module
import web.auth.decorators as auth_decorators
import web.vacaciones.vacaciones_routes as vacaciones_routes


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
    return [{"id": 10, "nombre": "Ana", "apellido": "Lopez", "dni": "12345"}]


def _stub_summary():
    return {
        "total": 1,
        "pendientes": 1,
        "aprobados": 0,
        "rechazados": 0,
        "dias_tomados": 0,
        "dias_pendientes": 5,
        "dias_compensatorios": 0,
        "dias_ajustes": 0,
    }


def _stub_saldo():
    return {
        "anio": 2026,
        "empleado": {"id": 10, "dni": "12345", "nombre": "Ana Lopez"},
        "vacaciones": {
            "fecha_ingreso": "2020-01-01",
            "antiguedad_al_31_12": 6,
            "dias_habiles_anio": 261,
            "dias_trabajados_anio": 0,
            "aplica_control_proporcional": False,
            "calculo_proporcional": False,
            "dias_base": 21,
            "dias_compensatorios": 0,
            "dias_ajustes": 0,
            "dias_tomados": 0,
            "dias_pendientes": 5,
            "dias_corresponden": 21,
            "dias_disponibles": 21,
            "dias_disponibles_con_pendientes": 16,
        },
    }


def test_vacaciones_listado_ok(monkeypatch):
    monkeypatch.setattr(
        vacaciones_routes,
        "get_movimientos_page",
        lambda **kw: (
            [
                {
                    "id": 5,
                    "apellido": "Lopez",
                    "nombre": "Ana",
                    "dni": "12345",
                    "empresa_nombre": "Acme",
                    "anio": 2026,
                    "tipo": "tomado",
                    "dias": 5,
                    "estado": "pendiente",
                    "fecha_desde": "2026-01-10",
                    "fecha_hasta": "2026-01-14",
                    "observacion": "Solicitud mobile",
                }
            ],
            1,
        ),
    )
    monkeypatch.setattr(vacaciones_routes, "get_movimientos_summary", lambda **kw: _stub_summary())
    monkeypatch.setattr(vacaciones_routes, "get_empleados", lambda **kw: _stub_empleados())
    monkeypatch.setattr(vacaciones_routes, "get_all", lambda: [])
    monkeypatch.setattr(vacaciones_routes, "calcular_resumen_vacaciones", lambda empleado_id, anio: _stub_saldo())

    client = _build_authed_client(monkeypatch)
    resp = client.get("/vacaciones/?empleado_id=10&anio=2026")

    assert resp.status_code == 200
    assert b"Vacaciones" in resp.data
    assert b"Solicitud mobile" in resp.data
    assert b"Aprobar" in resp.data


def test_vacaciones_listado_envia_filtros(monkeypatch):
    captured = {}

    def _fake_get_page(**kw):
        captured.update(kw)
        return ([], 0)

    monkeypatch.setattr(vacaciones_routes, "get_movimientos_page", _fake_get_page)
    monkeypatch.setattr(vacaciones_routes, "get_movimientos_summary", lambda **kw: _stub_summary())
    monkeypatch.setattr(vacaciones_routes, "get_empleados", lambda **kw: _stub_empleados())
    monkeypatch.setattr(vacaciones_routes, "get_all", lambda: [])
    monkeypatch.setattr(vacaciones_routes, "calcular_resumen_vacaciones", lambda empleado_id, anio: _stub_saldo())

    client = _build_authed_client(monkeypatch)
    resp = client.get("/vacaciones/?empleado_id=10&anio=2026&tipo=tomado&estado=pendiente&q=ana")

    assert resp.status_code == 200
    assert captured["empleado_id"] == 10
    assert captured["anio"] == 2026
    assert captured["tipo"] == "tomado"
    assert captured["estado"] == "pendiente"
    assert captured["search"] == "ana"


def test_vacaciones_movimiento_nuevo_post(monkeypatch):
    captured = {}
    monkeypatch.setattr(vacaciones_routes, "get_empleados", lambda **kw: _stub_empleados())
    monkeypatch.setattr(
        vacaciones_routes,
        "crear_movimiento_vacaciones_admin",
        lambda data: captured.update(data) or 77,
    )
    monkeypatch.setattr(vacaciones_routes, "log_audit", lambda *args, **kwargs: None)

    client = _build_authed_client(monkeypatch)
    resp = client.post(
        "/vacaciones/movimientos/nuevo",
        data={
            "empleado_id": "10",
            "anio": "2026",
            "tipo": "compensatorio",
            "dias": "2",
            "estado": "aprobado",
            "observacion": "Temporada",
        },
    )

    assert resp.status_code == 302
    assert captured["empleado_id"] == 10
    assert captured["tipo"] == "compensatorio"
    assert "msg=" in resp.headers["Location"]


def test_vacaciones_aprobar_redirige_con_msg(monkeypatch):
    captured = {}
    monkeypatch.setattr(
        vacaciones_routes,
        "aprobar_movimiento_vacaciones",
        lambda movimiento_id, **kw: captured.update({"movimiento_id": movimiento_id, "actor_id": kw.get("actor_id")}),
    )
    monkeypatch.setattr(vacaciones_routes, "log_audit", lambda *args, **kwargs: None)

    client = _build_authed_client(monkeypatch)
    resp = client.post("/vacaciones/movimientos/aprobar/5")

    assert resp.status_code == 302
    assert captured == {"movimiento_id": 5, "actor_id": 99}
    assert "msg=" in resp.headers["Location"]


def test_vacaciones_rechazar_redirige_con_msg(monkeypatch):
    captured = {}
    monkeypatch.setattr(
        vacaciones_routes,
        "rechazar_movimiento_vacaciones",
        lambda movimiento_id, **kw: captured.update({"movimiento_id": movimiento_id, "actor_id": kw.get("actor_id")}),
    )
    monkeypatch.setattr(vacaciones_routes, "log_audit", lambda *args, **kwargs: None)

    client = _build_authed_client(monkeypatch)
    resp = client.post("/vacaciones/movimientos/rechazar/5")

    assert resp.status_code == 302
    assert captured == {"movimiento_id": 5, "actor_id": 99}
    assert "msg=" in resp.headers["Location"]
