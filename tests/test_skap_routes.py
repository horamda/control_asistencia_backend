import app as app_module
import routes.skap_routes as skap_routes
import utils.jwt_guard as jwt_guard
import web.auth.decorators as auth_decorators
import web.skap.skap_routes as skap_web_routes


def _build_client(monkeypatch):
    monkeypatch.setattr(app_module, "init_db", lambda: None)
    app = app_module.create_app()
    app.config["TESTING"] = True
    app.config["WTF_CSRF_ENABLED"] = False
    return app.test_client()


def _login_web_session(client, role="admin"):
    with client.session_transaction() as sess:
        sess["user_id"] = 99
        sess["role"] = role
        sess["nombre"] = "Test"


def test_mobile_skap_crear_evaluacion_ok(monkeypatch):
    client = _build_client(monkeypatch)
    monkeypatch.setattr(jwt_guard, "verificar_token", lambda token: {"empleado_id": 10})
    monkeypatch.setattr(
        skap_routes,
        "get_empleado_by_id",
        lambda empleado_id: {
            "id": 10,
            "activo": 1,
            "empresa_id": 3,
            "sector_id": 7,
            "puesto_id": 4,
            "reporta_a_empleado_id": 20,
            "apellido": "Lopez",
            "nombre": "Ana",
        },
    )
    captured = {}

    monkeypatch.setattr(
        skap_routes,
        "create_evaluacion",
        lambda **kwargs: captured.update(kwargs) or {"evaluacion": {"id": 77}, "plan": {"id": 88}},
    )

    resp = client.post(
        "/api/skap/evaluacion",
        headers={"Authorization": "Bearer token-demo"},
        json={
            "anio": 2025,
            "respuestas": [{"pregunta_id": 1, "puntaje": 5}],
            "observaciones_generales": "Sin novedades",
        },
    )

    assert resp.status_code == 200
    body = resp.get_json()
    assert body["success"] is True
    assert body["data"]["evaluacion"]["id"] == 77
    assert captured["evaluador_empleado_id"] == 10
    assert captured["anio"] == 2025
    assert captured["respuestas"][0]["pregunta_id"] == 1


def test_mobile_skap_mi_desarrollo_ok(monkeypatch):
    client = _build_client(monkeypatch)
    monkeypatch.setattr(jwt_guard, "verificar_token", lambda token: {"empleado_id": 10})
    monkeypatch.setattr(
        skap_routes,
        "get_empleado_by_id",
        lambda empleado_id: {
            "id": 10,
            "activo": 1,
            "empresa_id": 3,
            "sector_id": 7,
            "puesto_id": 4,
            "reporta_a_empleado_id": 20,
            "apellido": "Lopez",
            "nombre": "Ana",
        },
    )
    monkeypatch.setattr(
        skap_routes,
        "get_mi_desarrollo",
        lambda **kwargs: {
            "anio_evaluado": kwargs["anio"] or 2025,
            "ranking": {"posicion": 2, "total": 5},
            "badge": "Plata",
            "evaluacion": {"id": 100},
        },
    )

    resp = client.get("/api/skap/mi_desarrollo?anio=2025", headers={"Authorization": "Bearer token-demo"})

    assert resp.status_code == 200
    body = resp.get_json()
    assert body["success"] is True
    assert body["data"]["ranking"]["posicion"] == 2
    assert body["data"]["anio_evaluado"] == 2025


def test_web_skap_dashboard_ok(monkeypatch):
    monkeypatch.setattr(auth_decorators, "has_role", lambda user_id, role: True)
    client = _build_client(monkeypatch)
    _login_web_session(client)

    monkeypatch.setattr(
        skap_web_routes,
        "get_sectores_page",
        lambda page, per_page, activo=None: ([{"id": 7, "nombre": "Operaciones"}], 1),
    )
    monkeypatch.setattr(
        skap_web_routes,
        "get_dashboard_data",
        lambda **kwargs: {
            "resumen": {
                "empleados_activos": 8,
                "empleados_evaluados": 5,
                "empleados_pendientes": 3,
                "promedio_general": 4.1,
                "planes_total": 2,
                "acciones_vencidas": 1,
                "acciones_completadas": 1,
                "acciones_en_proceso": 0,
                "acciones_canceladas": 0,
            },
            "sector_ranking": [],
            "historical_evolution": [],
            "category_averages": [],
            "weakest_competencies": [],
            "strongest_competencies": [],
            "destacados": [],
            "criticos": [],
        },
    )

    resp = client.get("/skap/?anio=2025&sector_id=7")

    assert resp.status_code == 200
    assert b"Resumen de desarrollo" in resp.data
    assert b"Operaciones" in resp.data
