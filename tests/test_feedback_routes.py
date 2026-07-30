import io

import app as app_module
import routes.feedback_routes as feedback_routes
from repositories.feedback_cliente_repository import _build_feedback_cliente_rank_sql
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


def test_mobile_feedback_crear_multipart_con_evidencia_ok(monkeypatch):
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
    captured = {}
    monkeypatch.setattr(feedback_routes, "create_feedback", lambda **kw: captured.update(kw) or 77)
    monkeypatch.setattr(
        feedback_routes,
        "serialize_feedback",
        lambda row: {"id": row.get("id"), "estado_actual": row.get("estado_actual")},
    )
    monkeypatch.setattr(
        "repositories.feedback_repository.get_by_id",
        lambda feedback_id: {"id": feedback_id, "estado_actual": "pendiente"},
    )

    resp = client.post(
        "/api/v1/feedback",
        headers={"Authorization": "Bearer token-demo"},
        data={
            "cliente_id": "1",
            "motivo_id": "2",
            "descripcion": "Problema con evidencia",
            "foto": (io.BytesIO(b"fake-image"), "evidencia.png"),
        },
        content_type="multipart/form-data",
    )

    assert resp.status_code == 201
    assert captured["empleado_id"] == 10
    assert captured["cliente_id"] == 1
    assert captured["motivo_id"] == 2
    assert captured["descripcion"] == "Problema con evidencia"
    assert captured["evidencia_file"].filename == "evidencia.png"


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


def test_mobile_feedback_bandeja_usa_jefe_directo_sin_requerir_sector_responsable(monkeypatch):
    client = _build_client(monkeypatch)
    monkeypatch.setattr(jwt_guard, "verificar_token", lambda token: {"empleado_id": 20})
    monkeypatch.setattr(
        feedback_routes,
        "get_empleado_by_id",
        lambda empleado_id: {"id": 20, "activo": 1, "empresa_id": 3, "sector_id": 7},
    )
    captured = {}
    monkeypatch.setattr(
        feedback_routes,
        "get_feedback_bandeja",
        lambda **kw: captured.update(kw) or ([{"id": 1, "estado_actual": "pendiente"}], 1),
    )

    resp = client.get("/api/v1/feedback/bandeja", headers={"Authorization": "Bearer token-demo"})

    assert resp.status_code == 200
    assert resp.get_json()["total"] == 1
    assert captured["jefe_directo_id"] == 20


def test_mobile_feedback_dashboard_usa_sector_del_empleado(monkeypatch):
    client = _build_client(monkeypatch)
    monkeypatch.setattr(jwt_guard, "verificar_token", lambda token: {"empleado_id": 10})
    monkeypatch.setattr(
        feedback_routes,
        "get_empleado_by_id",
        lambda empleado_id: {"id": 10, "activo": 1, "empresa_id": 3, "sector_id": 7},
    )
    captured = {}
    monkeypatch.setattr(
        feedback_routes,
        "get_feedback_dashboard",
        lambda **kw: captured.update(kw) or {
            "resumen": {"total": 1},
            "top_motivos": [],
            "ranking": [],
            "personal": None,
            "totales": {},
        },
    )

    resp = client.get("/api/v1/feedback/dashboard", headers={"Authorization": "Bearer token-demo"})

    assert resp.status_code == 200
    assert captured == {"empresa_id": 3, "sector_id": 7, "empleado_id": 10}


def test_feedback_cliente_rank_sql_params_match_placeholders():
    sql, params = _build_feedback_cliente_rank_sql("cliente")

    assert sql.count("%s") == len(params)


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


def test_mobile_feedback_clientes_ignores_non_numeric_sucursal(monkeypatch):
    client = _build_client(monkeypatch)
    monkeypatch.setattr(jwt_guard, "verificar_token", lambda token: {"empleado_id": 10})

    def fake_get_clientes_page(page, per_page, *, search=None, activo=None):
        return (
            [
                {
                    "id": 55,
                    "codigo_externo": "CLI-001",
                    "sucursal_origen": "NORTE",
                    "razon_social": "Cliente SA",
                    "nombre_fantasia": "Cliente Centro",
                    "tipo_descripcion": "Minorista",
                }
            ],
            1,
        )

    monkeypatch.setattr(feedback_routes, "get_clientes_page", fake_get_clientes_page)

    resp = client.get(
        "/api/v1/feedback/clientes?q=cliente",
        headers={"Authorization": "Bearer token-demo"},
    )

    assert resp.status_code == 200
    assert resp.get_json()["items"][0]["sucursal_origen"] is None


def test_mobile_feedback_clientes_accepts_search_alias(monkeypatch):
    client = _build_client(monkeypatch)
    monkeypatch.setattr(jwt_guard, "verificar_token", lambda token: {"empleado_id": 10})
    captured = {}

    def fake_get_clientes_page(page, per_page, *, search=None, activo=None):
        captured.update({"page": page, "per_page": per_page, "search": search, "activo": activo})
        return ([], 0)

    monkeypatch.setattr(feedback_routes, "get_clientes_page", fake_get_clientes_page)

    resp = client.get(
        "/api/v1/feedback/clientes?search=Cliente%20Centro",
        headers={"Authorization": "Bearer token-demo"},
    )

    assert resp.status_code == 200
    assert captured == {"page": 1, "per_page": 20, "search": "Cliente Centro", "activo": 1}


def test_mobile_feedback_clientes_accepts_razon_social_alias(monkeypatch):
    client = _build_client(monkeypatch)
    monkeypatch.setattr(jwt_guard, "verificar_token", lambda token: {"empleado_id": 10})
    captured = {}

    def fake_get_clientes_page(page, per_page, *, search=None, activo=None):
        captured.update({"page": page, "per_page": per_page, "search": search, "activo": activo})
        return ([], 0)

    monkeypatch.setattr(feedback_routes, "get_clientes_page", fake_get_clientes_page)

    resp = client.get(
        "/api/v1/feedback/clientes?razon_social=riajos",
        headers={"Authorization": "Bearer token-demo"},
    )

    assert resp.status_code == 200
    assert captured == {"page": 1, "per_page": 20, "search": "riajos", "activo": 1}


def test_web_feedback_dashboard_ok(monkeypatch):
    monkeypatch.setattr(auth_decorators, "has_role", lambda user_id, role: True)
    monkeypatch.setattr(feedback_web_routes, "has_role", lambda user_id, role: True)
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
    assert captured == {"sector_id": 7, "sucursal_id": 4, "empleado_id": None, "empleado_activo": 0}


def test_web_feedback_registros_filtra_sector_estado_y_empleado(monkeypatch):
    monkeypatch.setattr(auth_decorators, "has_role", lambda user_id, role: True)
    monkeypatch.setattr(feedback_web_routes, "has_role", lambda user_id, role: True)
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
    monkeypatch.setattr(feedback_web_routes, "get_empleados", lambda include_inactive=True: [])

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
        "sector_responsable_id": None,
        "sucursal_id": 4,
        "jefe_directo_id": None,
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
        "evidencia_file": None,
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
    monkeypatch.setattr(feedback_web_routes, "count_clientes", lambda include_inactive=False: 4711)

    resp = client.get("/feedback/clientes?page=2&per=10&q=cli&activo=1")
    assert resp.status_code == 200
    assert b"Clientes en base" in resp.data
    assert b"4711" in resp.data
    assert b"Anterior" in resp.data
    assert b"Siguiente" in resp.data


def test_web_feedback_clientes_listado_accepts_search_alias(monkeypatch):
    monkeypatch.setattr(auth_decorators, "has_role", lambda user_id, role: True)
    client = _build_client(monkeypatch)
    _login(client)
    captured = {}
    monkeypatch.setattr(
        feedback_web_routes,
        "get_clientes_page",
        lambda page, per_page, *, search=None, activo=None: captured.update(
            {"page": page, "per_page": per_page, "search": search, "activo": activo}
        ) or ([], 0),
    )
    monkeypatch.setattr(feedback_web_routes, "count_clientes", lambda include_inactive=False: 0)

    resp = client.get("/feedback/clientes?search=Cliente%20Centro&activo=1")

    assert resp.status_code == 200
    assert captured == {"page": 1, "per_page": 20, "search": "Cliente Centro", "activo": 1}


def test_web_feedback_registros_filtra_jefe_y_muestra_acciones(monkeypatch):
    monkeypatch.setattr(auth_decorators, "has_role", lambda user_id, role: True)
    monkeypatch.setattr(feedback_web_routes, "has_role", lambda user_id, role: True)
    client = _build_client(monkeypatch)
    _login(client)
    captured = {}

    def fake_page(page, per_page, **kwargs):
        captured.update(kwargs)
        return ([{
            "id": 9,
            "created_at": "2026-07-14 10:00",
            "descripcion": "Cliente sin respuesta",
            "estado_actual": "en_proceso",
            "empleado_nombre": "Lopez Ana",
            "empleado_legajo": "L10",
            "empleado_activo": 1,
            "empleado_sector_nombre": "Ventas",
            "empleado_sucursal_nombre": "Centro",
            "jefe_directo_id": 20,
            "jefe_directo_nombre": "Perez Jose",
            "jefe_directo_legajo": "J20",
            "cliente_razon_social": "Cliente SA",
            "motivo_nombre": "Visita",
        }], 1)

    monkeypatch.setattr(feedback_web_routes, "get_feedbacks_page", fake_page)
    monkeypatch.setattr(feedback_web_routes, "get_sectores", lambda include_inactive=True: [])
    monkeypatch.setattr(feedback_web_routes, "get_sucursales", lambda include_inactive=True: [])
    monkeypatch.setattr(feedback_web_routes, "get_empleados", lambda include_inactive=True: [{"id": 20, "apellido": "Perez", "nombre": "Jose"}])

    resp = client.get("/feedback/registros?jefe_directo_id=20")

    assert resp.status_code == 200
    assert captured["jefe_directo_id"] == 20
    assert b"Perez Jose" in resp.data
    assert b"Responder" in resp.data


def test_web_feedback_registros_jefe_usa_su_bandeja(monkeypatch):
    monkeypatch.setattr(auth_decorators, "has_role", lambda user_id, role: role == "jefe")
    monkeypatch.setattr(feedback_web_routes, "has_role", lambda user_id, role: False)
    monkeypatch.setattr(feedback_web_routes, "current_empleado_id", lambda: 20)
    monkeypatch.setattr(
        feedback_web_routes,
        "get_empleado_by_id",
        lambda empleado_id: {"id": empleado_id, "sector_id": 7, "sector_nombre": "Ventas"},
    )
    client = _build_client(monkeypatch)
    _login(client, role="jefe")
    captured = {}

    def fake_page(page, per_page, **kwargs):
        captured.update(kwargs)
        return ([{
            "id": 9,
            "created_at": "2026-07-14 10:00",
            "descripcion": "Cliente sin respuesta",
            "estado_actual": "pendiente",
            "empleado_nombre": "Lopez Ana",
            "empleado_legajo": "L10",
            "empleado_activo": 1,
            "empleado_sector_id": 7,
            "empleado_sector_nombre": "Ventas",
            "empleado_sucursal_nombre": "Centro",
            "jefe_directo_id": 20,
            "jefe_directo_nombre": "Perez Jose",
            "jefe_directo_legajo": "J20",
            "cliente_razon_social": "Cliente SA",
            "motivo_nombre": "Visita",
        }], 1)

    monkeypatch.setattr(feedback_web_routes, "get_feedbacks_page", fake_page)
    monkeypatch.setattr(feedback_web_routes, "get_sectores", lambda include_inactive=True: [])
    monkeypatch.setattr(feedback_web_routes, "get_sucursales", lambda include_inactive=True: [])
    monkeypatch.setattr(feedback_web_routes, "get_empleados", lambda include_inactive=True: (_ for _ in ()).throw(AssertionError("no debe listar jefes")))

    resp = client.get("/feedback/bandeja?estado=pendiente", follow_redirects=True)

    assert resp.status_code == 200
    assert captured["jefe_directo_id"] == 20
    assert captured["sector_id"] is None
    assert captured["estado"] == "pendiente"
    assert b"Responder" in resp.data
    assert b"Todos los jefes" not in resp.data


def test_web_feedback_registros_supervisor_fuerza_su_sector(monkeypatch):
    monkeypatch.setattr(auth_decorators, "has_role", lambda user_id, role: role == "supervisor")
    monkeypatch.setattr(feedback_web_routes, "has_role", lambda user_id, role: False)
    monkeypatch.setattr(feedback_web_routes, "current_empleado_id", lambda: 30)
    monkeypatch.setattr(
        feedback_web_routes,
        "get_empleado_by_id",
        lambda empleado_id: {"id": empleado_id, "sector_id": 7, "sector_nombre": "Operaciones"},
    )
    client = _build_client(monkeypatch)
    _login(client, role="supervisor")
    captured = {}

    def fake_page(page, per_page, **kwargs):
        captured.update(kwargs)
        return ([{
            "id": 11,
            "created_at": "2026-07-14 10:00",
            "descripcion": "Caso operaciones",
            "estado_actual": "pendiente",
            "empleado_nombre": "Aguirre Leo",
            "empleado_legajo": "L11",
            "empleado_activo": 1,
            "empleado_sector_id": 7,
            "empleado_sector_nombre": "Operaciones",
            "empleado_sucursal_nombre": "Centro",
            "jefe_directo_id": 99,
            "jefe_directo_nombre": "Otro Jefe",
            "jefe_directo_legajo": "J99",
            "cliente_razon_social": "Cliente SA",
            "motivo_nombre": "Entrega",
        }], 1)

    monkeypatch.setattr(feedback_web_routes, "get_feedbacks_page", fake_page)
    monkeypatch.setattr(feedback_web_routes, "get_sectores", lambda include_inactive=True: [])
    monkeypatch.setattr(feedback_web_routes, "get_sucursales", lambda include_inactive=True: [])

    resp = client.get("/feedback/registros?sector_id=99&jefe_directo_id=99")

    assert resp.status_code == 200
    assert captured["sector_id"] == 7
    assert captured["jefe_directo_id"] is None
    assert b"Caso operaciones" in resp.data
    assert b"Todos los jefes" not in resp.data


def test_web_feedback_detalle_muestra_form_respuesta(monkeypatch):
    monkeypatch.setattr(auth_decorators, "has_role", lambda user_id, role: True)
    monkeypatch.setattr(feedback_web_routes, "has_role", lambda user_id, role: True)
    client = _build_client(monkeypatch)
    _login(client)
    monkeypatch.setattr(
        feedback_web_routes,
        "get_feedback_by_id",
        lambda feedback_id: {
            "id": feedback_id,
            "estado_actual": "pendiente",
            "descripcion": "Resolver reclamo",
            "fecha_vencimiento": "2026-07-30",
            "created_at": "2026-07-14 10:00",
            "empleado_nombre": "Lopez Ana",
            "empleado_legajo": "L10",
            "empleado_activo": 1,
            "empleado_sector_nombre": "Ventas",
            "empleado_sucursal_nombre": "Centro",
            "jefe_directo_id": 20,
            "jefe_directo_nombre": "Perez Jose",
            "jefe_directo_legajo": "J20",
            "cliente_razon_social": "Cliente SA",
            "motivo_nombre": "Visita",
        },
    )

    resp = client.get("/feedback/registros/9")

    assert resp.status_code == 200
    assert b"Feedback #9" in resp.data
    assert b"Cargar respuesta del jefe" in resp.data
    assert b"Guardar respuesta y resolver" in resp.data


def test_web_feedback_detalle_oculta_form_sin_permiso_respuesta(monkeypatch):
    monkeypatch.setattr(auth_decorators, "has_role", lambda user_id, role: True)
    monkeypatch.setattr(feedback_web_routes, "has_role", lambda user_id, role: role not in {"admin", "rrhh"})
    client = _build_client(monkeypatch)
    _login(client)
    monkeypatch.setattr(feedback_web_routes, "current_empleado_id", lambda: 30)
    monkeypatch.setattr(
        feedback_web_routes,
        "get_empleado_by_id",
        lambda empleado_id: {"id": empleado_id, "sector_id": 7, "sector_nombre": "Ventas"},
    )
    monkeypatch.setattr(
        feedback_web_routes,
        "get_feedback_by_id",
        lambda feedback_id: {
            "id": feedback_id,
            "estado_actual": "pendiente",
            "descripcion": "Resolver reclamo",
            "fecha_vencimiento": "2026-07-30",
            "created_at": "2026-07-14 10:00",
            "empleado_nombre": "Lopez Ana",
            "empleado_legajo": "L10",
            "empleado_activo": 1,
            "empleado_sector_id": 7,
            "empleado_sector_nombre": "Ventas",
            "empleado_sucursal_nombre": "Centro",
            "jefe_directo_id": 20,
            "jefe_directo_nombre": "Perez Jose",
            "jefe_directo_legajo": "J20",
            "cliente_razon_social": "Cliente SA",
            "motivo_nombre": "Visita",
        },
    )

    resp = client.get("/feedback/registros/9")

    assert resp.status_code == 200
    assert b"No tiene permisos para responder este feedback." in resp.data
    assert b"Guardar respuesta y resolver" not in resp.data


def test_web_feedback_detalle_bloquea_otro_sector(monkeypatch):
    monkeypatch.setattr(auth_decorators, "has_role", lambda user_id, role: role == "supervisor")
    monkeypatch.setattr(feedback_web_routes, "has_role", lambda user_id, role: False)
    client = _build_client(monkeypatch)
    _login(client, role="supervisor")
    monkeypatch.setattr(feedback_web_routes, "current_empleado_id", lambda: 30)
    monkeypatch.setattr(
        feedback_web_routes,
        "get_empleado_by_id",
        lambda empleado_id: {"id": empleado_id, "sector_id": 7, "sector_nombre": "Operaciones"},
    )
    monkeypatch.setattr(
        feedback_web_routes,
        "get_feedback_by_id",
        lambda feedback_id: {
            "id": feedback_id,
            "estado_actual": "pendiente",
            "empleado_sector_id": 99,
            "empleado_sector_nombre": "Ventas",
        },
    )

    resp = client.get("/feedback/registros/9")

    assert resp.status_code == 302
    assert "No+tiene+permisos" in resp.headers["Location"]


def test_web_feedback_resolver_admin(monkeypatch):
    monkeypatch.setattr(auth_decorators, "has_role", lambda user_id, role: True)
    monkeypatch.setattr(feedback_web_routes, "has_role", lambda user_id, role: True)
    client = _build_client(monkeypatch)
    _login(client)
    captured = {}
    monkeypatch.setattr(feedback_web_routes, "current_empleado_id", lambda: None)
    monkeypatch.setattr(feedback_web_routes, "get_feedback_by_id", lambda feedback_id: {"id": feedback_id, "jefe_directo_id": 20})
    monkeypatch.setattr(feedback_web_routes, "resolver_feedback", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("no debe usar resolver de jefe")))
    monkeypatch.setattr(feedback_web_routes, "resolver_feedback_admin", lambda feedback_id, **kwargs: captured.update({"feedback_id": feedback_id, **kwargs}))
    monkeypatch.setattr(feedback_web_routes, "log_audit", lambda *args, **kwargs: None)

    resp = client.post(
        "/feedback/registros/9/resolver",
        data={"resolucion_descripcion": "Se contacto al cliente y se cerro el caso."},
        follow_redirects=False,
    )

    assert resp.status_code == 302
    assert captured == {
        "feedback_id": 9,
        "actor_empleado_id": None,
        "resolucion_descripcion": "Se contacto al cliente y se cerro el caso.",
    }
    assert "/feedback/registros/9" in resp.headers["Location"]


def test_web_feedback_tomar_requiere_empleado_vinculado(monkeypatch):
    monkeypatch.setattr(auth_decorators, "has_role", lambda user_id, role: True)
    monkeypatch.setattr(feedback_web_routes, "has_role", lambda user_id, role: True)
    client = _build_client(monkeypatch)
    _login(client)
    monkeypatch.setattr(feedback_web_routes, "current_empleado_id", lambda: None)

    resp = client.post("/feedback/registros/9/tomar", follow_redirects=False)

    assert resp.status_code == 302
    assert "empleado+vinculado" in resp.headers["Location"]
