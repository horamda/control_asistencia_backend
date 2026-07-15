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


def test_mobile_feedback_clientes_search_and_limit_ok(monkeypatch):
    client = _build_client(monkeypatch)
    monkeypatch.setattr(jwt_guard, "verificar_token", lambda token: {"empleado_id": 10})
    captured = {}

    def fake_get_clientes_page(page, per_page, *, search=None, activo=None):
        captured.update({"page": page, "per_page": per_page, "search": search, "activo": activo})
        return (
            [
                {
                    "id": 55,
                    "codigo_externo": "CLI-001",
                    "sucursal_origen": "7",
                    "razon_social": "Cliente SA",
                    "nombre_fantasia": "Cliente Centro",
                    "telefonos": "1122334455",
                    "movil": "1199998888",
                    "email": "contacto@cliente.com",
                    "domicilio": "Av. Siempre Viva 123",
                    "localidad": "CABA",
                    "provincia": "Buenos Aires",
                    "tipo_descripcion": "Minorista",
                }
            ],
            1,
        )

    monkeypatch.setattr(feedback_routes, "get_clientes_page", fake_get_clientes_page)

    resp = client.get(
        "/api/v1/feedback/clientes?q=cliente&page=2&per_page=500",
        headers={"Authorization": "Bearer token-demo"},
    )

    assert resp.status_code == 200
    body = resp.get_json()
    assert captured == {"page": 2, "per_page": 200, "search": "cliente", "activo": 1}
    assert body["page"] == 2
    assert body["per_page"] == 200
    assert body["items"][0]["sucursal_origen"] == 7


def test_web_feedback_dashboard_ok(monkeypatch):
    monkeypatch.setattr(auth_decorators, "has_role", lambda user_id, role: True)
    client = _build_client(monkeypatch)
    _login(client)
    captured = {}
    monkeypatch.setattr(
        feedback_web_routes,
        "get_feedback_dashboard",
        lambda **kw: captured.update(kw) or {
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
    monkeypatch.setattr(
        feedback_web_routes,
        "get_sectores",
        lambda include_inactive=True: [
            {"id": 7, "nombre": "Ventas", "empresa_nombre": "Acme", "activo": 1}
        ],
    )
    monkeypatch.setattr(
        feedback_web_routes,
        "get_sucursales",
        lambda include_inactive=True: [
            {"id": 4, "nombre": "Centro", "empresa_nombre": "Acme", "activa": 1}
        ],
    )

    resp = client.get("/feedback/?sector_id=7&sucursal_id=4&empleado_activo=0")
    assert resp.status_code == 200
    assert b"Resumen general" in resp.data
    assert b"Rotura" in resp.data
    assert b"Sector del empleado" in resp.data
    assert b"Ventas" in resp.data
    assert b"Sucursal del empleado" in resp.data
    assert b"Centro" in resp.data
    assert b"Cargar feedback" in resp.data
    assert b"Ver registros" in resp.data
    assert captured == {"sector_id": 7, "sucursal_id": 4, "empleado_activo": 0}


def test_web_feedback_registros_filtra_sector_estado_y_empleado(monkeypatch):
    monkeypatch.setattr(auth_decorators, "has_role", lambda user_id, role: True)
    client = _build_client(monkeypatch)
    _login(client)
    captured = {}

    def fake_page(page, per_page, **kwargs):
        captured.update({"page": page, "per_page": per_page, **kwargs})
        return ([{
            "id": 1,
            "created_at": "2026-07-14 10:00",
            "descripcion": "Visita comercial",
            "estado_actual": "pendiente",
            "empleado_nombre": "Lopez Ana",
            "empleado_legajo": "L10",
            "empleado_activo": 1,
            "empleado_sector_id": 7,
            "empleado_sector_nombre": "Ventas",
            "cliente_razon_social": "Cliente SA",
            "motivo_nombre": "Visita",
        }], 1)

    monkeypatch.setattr(feedback_web_routes, "get_feedbacks_page", fake_page)
    monkeypatch.setattr(feedback_web_routes, "get_sectores", lambda include_inactive=True: [
        {"id": 7, "nombre": "Ventas", "empresa_nombre": "Acme", "activo": 1}
    ])
    monkeypatch.setattr(feedback_web_routes, "get_sucursales", lambda include_inactive=True: [
        {"id": 4, "nombre": "Centro", "empresa_nombre": "Acme", "activa": 1}
    ])

    resp = client.get("/feedback/registros?sector_id=7&sucursal_id=4&empleado_activo=1&estado=pendiente&q=cliente")

    assert resp.status_code == 200
    assert b"Visita comercial" in resp.data
    assert b"Ventas" in resp.data
    assert captured == {
        "page": 1,
        "per_page": 20,
        "estado": "pendiente",
        "search": "cliente",
        "sector_id": 7,
        "sucursal_id": 4,
        "empleado_activo": 1,
    }


def test_web_feedback_nuevo_reutiliza_servicio_mobile(monkeypatch):
    monkeypatch.setattr(auth_decorators, "has_role", lambda user_id, role: True)
    client = _build_client(monkeypatch)
    _login(client)
    captured = {}
    monkeypatch.setattr(feedback_web_routes, "create_feedback", lambda **kwargs: captured.update(kwargs) or 77)
    monkeypatch.setattr(feedback_web_routes, "log_audit", lambda *args, **kwargs: None)

    resp = client.post("/feedback/nuevo", data={
        "empleado_id": "10",
        "cliente_id": "20",
        "motivo_id": "30",
        "descripcion": "Comentario desde el panel",
    })

    assert resp.status_code == 302
    assert "/feedback/registros" in resp.headers["Location"]
    assert captured == {
        "empleado_id": 10,
        "cliente_id": 20,
        "motivo_id": 30,
        "descripcion": "Comentario desde el panel",
    }


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


def test_web_feedback_clientes_listado_paginado(monkeypatch):
    monkeypatch.setattr(auth_decorators, "has_role", lambda user_id, role: True)
    client = _build_client(monkeypatch)
    _login(client)
    monkeypatch.setattr(
        feedback_web_routes,
        "get_clientes_page",
        lambda page, per_page, *, search=None, activo=None: (
            [
                {
                    "codigo_externo": "CLI-001",
                    "razon_social": "Cliente SA",
                    "nombre_fantasia": "Cliente Centro",
                    "tipo_descripcion": "Minorista",
                    "localidad": "CABA",
                    "provincia": "Buenos Aires",
                    "activo": 1,
                }
            ],
            21,
        ),
    )

    resp = client.get("/feedback/clientes?page=2&per=10&q=cli&activo=1")
    assert resp.status_code == 200
    assert b"Anterior" in resp.data
    assert b"Siguiente" in resp.data
