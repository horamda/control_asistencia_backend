import io

import app as app_module
import web.auth.decorators as auth_decorators
import web.pedidos_mercaderia.pedidos_mercaderia_routes as pedidos_routes


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


def test_pedidos_mercaderia_listado_ok(monkeypatch):
    monkeypatch.setattr(
        pedidos_routes,
        "get_page",
        lambda **kw: (
            [
                {
                    "id": 91,
                    "empresa_nombre": "Acme",
                    "apellido": "Lopez",
                    "nombre": "Ana",
                    "dni": "12345",
                    "periodo_year": 2026,
                    "periodo_month": 4,
                    "fecha_pedido": "2026-04-18",
                    "estado": "aprobado",
                    "cantidad_items": 2,
                    "total_bultos": 3,
                    "resuelto_by_usuario": "rrhh",
                    "resuelto_at": "2026-04-18 10:00:00",
                    "motivo_rechazo": None,
                }
            ],
            1,
        ),
    )
    monkeypatch.setattr(
        pedidos_routes,
        "get_summary",
        lambda **kw: {"total": 1, "pendientes": 0, "aprobados": 1, "rechazados": 0, "cancelados": 0},
    )
    monkeypatch.setattr(pedidos_routes, "get_empleados", lambda **kw: _stub_empleados())
    client = _build_authed_client(monkeypatch)
    resp = client.get("/pedidos-mercaderia/")
    assert resp.status_code == 200
    assert b"Pedidos de mercaderia" in resp.data
    assert b"rrhh" in resp.data


def test_pedidos_mercaderia_export_csv_ok(monkeypatch):
    monkeypatch.setattr(
        pedidos_routes,
        "get_export",
        lambda **kw: [
            {
                "id": 91,
                "empresa_nombre": "Acme",
                "dni": "12345",
                "apellido": "Lopez",
                "nombre": "Ana",
                "periodo_year": 2026,
                "periodo_month": 4,
                "fecha_pedido": "2026-04-18",
                "estado": "pendiente",
                "codigo_articulo_snapshot": "A1",
                "descripcion_snapshot": "Gaseosa",
                "cantidad_bultos": 2,
                "unidades_por_bulto_snapshot": 8,
                "resuelto_by_usuario": "rrhh",
                "resuelto_at": "2026-04-18 12:00:00",
                "motivo_rechazo": "",
            }
        ],
    )
    client = _build_authed_client(monkeypatch)
    resp = client.get("/pedidos-mercaderia/export.csv?estado=pendiente&anio=2026&mes=4")
    assert resp.status_code == 200
    assert resp.mimetype == "text/csv"
    assert b"Acme" in resp.data
    assert b"Gaseosa" in resp.data


def test_pedidos_mercaderia_aprobar_redirige_con_msg(monkeypatch):
    captured = {}
    monkeypatch.setattr(
        pedidos_routes,
        "aprobar_pedido",
        lambda pedido_id, **kw: captured.update({"pedido_id": pedido_id, "actor_id": kw.get("actor_id")}),
    )
    monkeypatch.setattr(pedidos_routes, "log_audit", lambda *a, **kw: None)
    client = _build_authed_client(monkeypatch)
    resp = client.post("/pedidos-mercaderia/aprobar/91")
    assert resp.status_code == 302
    assert "msg=" in resp.headers["Location"]
    assert captured == {"pedido_id": 91, "actor_id": 99}


def test_pedidos_mercaderia_rechazar_redirige_con_msg(monkeypatch):
    captured = {}
    monkeypatch.setattr(
        pedidos_routes,
        "rechazar_pedido",
        lambda pedido_id, **kw: captured.update(
            {
                "pedido_id": pedido_id,
                "actor_id": kw.get("actor_id"),
                "motivo_rechazo": kw.get("motivo_rechazo"),
            }
        ),
    )
    monkeypatch.setattr(pedidos_routes, "log_audit", lambda *a, **kw: None)
    client = _build_authed_client(monkeypatch)
    resp = client.post("/pedidos-mercaderia/rechazar/91", data={"motivo_rechazo": "Sin stock"})
    assert resp.status_code == 302
    assert "msg=" in resp.headers["Location"]
    assert captured == {"pedido_id": 91, "actor_id": 99, "motivo_rechazo": "Sin stock"}


def test_pedidos_mercaderia_importar_csv_ok(monkeypatch):
    monkeypatch.setattr(
        pedidos_routes,
        "importar_articulos_desde_csv",
        lambda stream: {
            "total_filas": 3,
            "importables": 1,
            "creados": 1,
            "actualizados": 0,
            "deshabilitados": 0,
            "ignorados": 2,
            "errores": [],
        },
    )
    monkeypatch.setattr(pedidos_routes, "log_audit", lambda *a, **kw: None)
    client = _build_authed_client(monkeypatch)
    resp = client.post(
        "/pedidos-mercaderia/articulos/importar-csv",
        data={"archivo_csv": (io.BytesIO(b"Articulo;Descripcion articulo\n"), "articulos.csv")},
        content_type="multipart/form-data",
    )
    assert resp.status_code == 200
    assert b"Importacion completada sin errores" in resp.data
