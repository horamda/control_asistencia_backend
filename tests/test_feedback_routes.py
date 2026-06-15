import io

import app as app_module
import routes.feedback_routes as feedback_routes
import web.auth.decorators as auth_decorators
import web.feedback.feedback_routes as feedback_web_routes
import utils.jwt_guard as jwt_guard


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


def test_mobile_feedback_crear_ok(monkeypatch):
    client = _build_client(monkeypatch)
    monkeypatch.setattr(jwt_guard, "verificar_token", lambda token: {"empleado_id": 10})
    monkeypatch.setattr(
        feedback_routes,
        "get_empleado_by_id",
        lambda empleado_id: {
            "id": 10,
            "activo": 1,
            "empresa_id": 3,
            "reporta_a_empleado_id": 20,
            "nombre": "Ana",
            "apellido": "Lopez",
            "legajo": "L10",
        },
    )
    monkeypatch.setattr(feedback_routes, "create_feedback", lambda **kw: 77)
    monkeypatch.setattr(
        feedback_routes,
        "serialize_feedback",
        lambda row: {"id": row.get("id"), "estado_actual": row.get("estado_actual"), "cliente": {"razon_social": "Cliente SA"}},
    )
    monkeypatch.setattr(
        "repositories.feedback_repository.get_by_id",
        lambda feedback_id: {"id": feedback_id, "estado_actual": "pendiente"},
    )

    resp = client.post(
        "/api/v1/feedback",
        headers={"Authorization": "Bearer token-demo"},
        json={"cliente_id": 1, "motivo_id": 2, "descripcion": "Problema en la calle"},
    )

    assert resp.status_code == 201
    assert resp.get_json()["feedback"]["id"] == 77


def test_mobile_feedback_historial_ok(monkeypatch):
    client = _build_client(monkeypatch)
    monkeypatch.setattr(jwt_guard, "verificar_token", lambda token: {"empleado_id": 10})
    monkeypatch.setattr(
        feedback_routes,
        "get_empleado_by_id",
        lambda empleado_id: {"id": 10, "activo": 1, "empresa_id": 3},
    )
    monkeypatch.setattr(
        feedback_routes,
        "get_feedback_historial",
        lambda **kw: ([{"id": 1, "estado_actual": "pendiente"}], 1),
    )

    resp = client.get("/api/v1/feedback/historial", headers={"Authorization": "Bearer token-demo"})
    assert resp.status_code == 200
    assert resp.get_json()["total"] == 1


def test_web_feedback_dashboard_ok(monkeypatch):
    monkeypatch.setattr(auth_decorators, "has_role", lambda user_id, role: True)
    client = _build_client(monkeypatch)
    _login(client)
    monkeypatch.setattr(
        feedback_web_routes,
        "get_feedback_dashboard",
        lambda **kw: {
            "resumen": {
                "total": 3,
                "resueltos": 2,
                "pendientes": 1,
                "en_proceso": 0,
                "vencidos": 0,
                "resueltos_en_sla": 2,
                "resueltos_fuera_sla": 0,
            },
            "top_motivos": [{"motivo_nombre": "Rotura", "total": 2, "resueltos": 1}],
            "ranking": [{"apellido": "Lopez", "nombre": "Ana", "legajo": "L10", "total": 5}],
            "personal": {"total_cargados": 5, "posicion_ranking": 1},
            "totales": {"empleados_activos": 10, "empleados_con_carga": 4},
        },
    )
    monkeypatch.setattr(feedback_web_routes, "count_motivos", lambda include_inactive=True: 2)
    monkeypatch.setattr(feedback_web_routes, "count_clientes", lambda include_inactive=True: 15)

    resp = client.get("/feedback/")
    assert resp.status_code == 200
    assert b"Resumen general" in resp.data
    assert b"Rotura" in resp.data


def test_web_feedback_clientes_importar_ok(monkeypatch):
    monkeypatch.setattr(auth_decorators, "has_role", lambda user_id, role: True)
    client = _build_client(monkeypatch)
    _login(client)
    monkeypatch.setattr(
        feedback_web_routes,
        "importar_clientes_desde_csv",
        lambda stream: {
            "total_filas": 1,
            "importadas": 1,
            "creados": 1,
            "actualizados": 0,
            "errores": 0,
            "detalle_errores": [],
        },
    )
    monkeypatch.setattr(feedback_web_routes, "log_audit", lambda *a, **kw: None)

    resp = client.post(
        "/feedback/clientes/importar",
        data={"archivo_csv": (io.BytesIO(b"dummy"), "clientes.csv")},
        content_type="multipart/form-data",
    )
    assert resp.status_code == 200
    assert b"Importacion" in resp.data
