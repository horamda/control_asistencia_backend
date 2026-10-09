"""EPP integration tests: isolated schema only, never production."""

from uuid import uuid4
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor
import pytest
from tests.test_seguridad import database, photo
from services import epp_service as s
from scripts.migrate_20261008_02_epp import migrate_cursor

ADMIN = dict(
    mode="web",
    empresa_id=1,
    user_id=98,
    empleado_id=None,
    approve=True,
    deliver=True,
    **{"global": True},
)
OWNER = dict(mode="empleado", empresa_id=1, empleado_id=10)
BOSS = dict(
    mode="web",
    empresa_id=1,
    user_id=99,
    empleado_id=11,
    approve=True,
    deliver=False,
    **{"global": False},
)


@pytest.fixture(autouse=True)
def schema(database, monkeypatch):
    monkeypatch.setattr(s, "now_local", lambda: datetime(2026, 10, 8, 12))
    with s.db.transaction() as c:
        c.execute("ALTER TABLE empleados ADD reporta_a_empleado_id INT NULL")
        c.execute("UPDATE empleados SET reporta_a_empleado_id=11 WHERE id=10")
        c.execute("ALTER TABLE sectores ADD empresa_id INT DEFAULT 1")
        c.execute("ALTER TABLE puestos ADD empresa_id INT DEFAULT 1")
        migrate_cursor(c)
        migrate_cursor(c)
    aid = s.save_article(
        ADMIN,
        dict(
            nombre="Buzo",
            categoria="Ropa",
            talles=["M", "XL"],
            sectores=[1],
            puestos=[1],
            aviso_anual=2,
        ),
        photo(),
    )
    return aid


def payload(aid, **kw):
    return dict(
        envio_id=str(uuid4()),
        motivo="Reposición",
        items=[dict(articulo_id=aid, talle="XL", cantidad=2)],
        **kw,
    )


def order(aid):
    return s.create(OWNER, 10, payload(aid))[0]


def approve(pid, qty=2):
    row = s.detail(ADMIN, pid)
    s.action(
        BOSS,
        pid,
        dict(
            accion="resolver",
            revision=row["revision"],
            cantidades={str(i["id"]): qty for i in row["items"]},
            motivo="Aprobación",
        ),
    )


def delivery(pid, n=1, **kw):
    row = s.detail(ADMIN, pid)
    return dict(
        envio_id=str(uuid4()),
        revision=row["revision"],
        fecha="2026-10-08",
        cantidades={str(i["id"]): n for i in row["items"]},
        **kw,
    )


def test_sizes_scope_and_snapshot(schema):
    s.save_size(OWNER, 10, dict(articulo_id=schema, talle="XL", medidas="Pecho 110 cm"))
    pid = order(schema)
    s.save_size(OWNER, 10, dict(articulo_id=schema, talle="M"))
    assert s.detail(OWNER, pid)["items"][0]["talle"] == "XL"
    with pytest.raises(s.Error):
        s.sizes(OWNER, 11)
    with pytest.raises(s.Error):
        s.save_size(OWNER, 10, dict(articulo_id=schema, talle="XXXL"))
    with pytest.raises(s.Error):
        s.catalogs(dict(OWNER, empresa_id=2), 10)


def test_partial_delivery_report_undo_and_receipt(schema):
    pid = order(schema)
    approve(pid)
    did, _ = s.deliver(ADMIN, pid, delivery(pid))
    assert s.detail(OWNER, pid)["estado"] == "parcial"
    assert s.report(OWNER, {"anio": 2026})["items"][0]["cantidad"] == 1
    assert s.report(OWNER, {"anio": 2025})["items"] == []
    s.delivery_update(ADMIN, did, {}, photo())
    assert s.receipt(OWNER, did)["firmada"]
    s.deliver(ADMIN, pid, delivery(pid))
    assert s.detail(OWNER, pid)["estado"] == "entregado"
    s.delivery_update(ADMIN, did, dict(accion="anular", motivo="Error de registro"))
    assert s.detail(OWNER, pid)["estado"] == "parcial"
    assert s.report(OWNER, {"anio": 2026})["items"][0]["cantidad"] == 1


def test_retries_and_revision(schema):
    p = payload(schema)
    with ThreadPoolExecutor(max_workers=2) as pool:
        rows = list(pool.map(lambda _: s.create(OWNER, 10, p), range(2)))
    assert rows[0][0] == rows[1][0] and sum(created for _, created in rows) == 1
    pid = rows[0][0]
    approve(pid)
    data = delivery(pid)
    with ThreadPoolExecutor(max_workers=2) as pool:
        rows = list(pool.map(lambda _: s.deliver(ADMIN, pid, data), range(2)))
    assert rows[0][0] == rows[1][0] and sum(created for _, created in rows) == 1
    with pytest.raises(s.Error):
        s.deliver(ADMIN, pid, dict(data, observaciones="different"))
    with pytest.raises(s.Error):
        s.action(BOSS, pid, dict(accion="resolver", revision=1))


def test_approval_scope_and_overdelivery(schema):
    pid = order(schema)
    with pytest.raises(s.Error):
        s.detail(dict(BOSS, empleado_id=12), pid)
    with pytest.raises(s.Error):
        s.action(dict(ADMIN, empleado_id=10), pid, dict(accion="resolver", revision=1))
    with pytest.raises(s.Error):
        s.action(OWNER, pid, dict(accion="resolver", revision=1))
    approve(pid)
    with pytest.raises(s.Error):
        s.deliver(BOSS, pid, delivery(pid))
    with pytest.raises(s.Error):
        s.deliver(ADMIN, pid, delivery(pid, 3))
    s.deliver(ADMIN, pid, delivery(pid, 2))
    other = order(schema)
    approve(other)
    with pytest.raises(s.Error):
        s.deliver(ADMIN, other, delivery(other))
    s.deliver(ADMIN, other, delivery(other, observaciones="Desgaste excepcional"))
    assert s.report(OWNER, {"anio": 2026})["items"][0]["cantidad"] == 3


def test_filters_and_pending_edit(schema):
    s.save_article(
        ADMIN,
        dict(
            id=schema,
            nombre="Buzo",
            categoria="Ropa",
            talles=["XL"],
            sectores=[],
            puestos=[1],
            activo=0,
        ),
    )
    assert s.catalogs(OWNER, 10) == []
    with pytest.raises(s.Error):
        order(schema)
    s.save_article(
        ADMIN,
        dict(
            id=schema,
            nombre="Buzo",
            categoria="Ropa",
            talles=["XL"],
            sectores=[],
            puestos=[],
            activo=1,
        ),
    )
    pid = order(schema)
    data = payload(schema)
    data["revision"] = 1
    data["items"][0]["cantidad"] = 1
    s.edit_order(OWNER, pid, data)
    assert s.detail(OWNER, pid)["revision"] == 2
    with pytest.raises(s.Error):
        s.edit_order(OWNER, pid, data)
    s.action(OWNER, pid, dict(accion="cancelar", revision=2, motivo="Ya no necesito"))
    assert s.detail(OWNER, pid)["estado"] == "cancelado"


@pytest.fixture
def client(monkeypatch):
    from pathlib import Path
    from flask import Flask
    from web.epp import routes as w
    from tests.test_seguridad import employee
    from routes import carga_routes
    import web.auth.decorators as auth
    import utils.jwt_guard as jwt

    app = Flask(
        __name__, template_folder=str(Path(__file__).resolve().parents[1] / "templates")
    )
    app.secret_key = "test"
    app.config["TESTING"] = True
    app.register_blueprint(w.web)
    app.register_blueprint(w.mobile)
    app.jinja_env.globals.update(
        csrf_token=lambda: "test",
        can_web=lambda code, *args: code in ("epp", "epp_responsables"),
        export_toolbar={"enabled": False, "items": []},
    )
    monkeypatch.setattr(auth, "can_access_module", lambda *args: True)
    monkeypatch.setattr(w, "can_access_module", lambda *args: True)
    monkeypatch.setattr(
        w,
        "_cached_web_user",
        lambda uid: dict(id=uid, empresa_id=1, activo=1, empleado_id=None),
    )
    monkeypatch.setattr(
        jwt, "verificar_token", lambda token: dict(empleado_id=int(token))
    )
    monkeypatch.setattr(carga_routes, "get_by_id", employee)
    result = app.test_client()
    with result.session_transaction() as session:
        session["user_id"] = 98
    with s.db.transaction() as c:
        c.execute("ALTER TABLE sucursales ADD empresa_id INT DEFAULT 1")
    return result


def test_http_ui_pdf_and_mobile_privacy(schema, client):
    root = "/api/v1/mobile/epp"
    headers = {"Authorization": "Bearer 10"}
    assert client.get(root + "/config").status_code == 401
    response = client.get(root + "/config", headers=headers)
    assert response.status_code == 200 and response.json["articulos"][0]["id"] == schema
    assert "no-store" in response.headers["Cache-Control"]
    resp = client.post(root + "/pedidos", headers=headers, json=payload(schema))
    assert resp.status_code == 201
    pid = resp.json["pedido"]["id"]
    assert (
        client.get(
            root + f"/pedidos/{pid}", headers={"Authorization": "Bearer 11"}
        ).status_code
        == 403
    )
    for path in (
        "/epp/",
        "/epp/catalogo",
        "/epp/categorias",
        "/epp/talles?empleado_id=10",
        "/epp/nuevo?empleado_id=10",
        f"/epp/pedidos/{pid}",
        f"/epp/pedidos/{pid}/editar",
        "/epp/reporte",
    ):
        response = client.get(path)
        assert response.status_code == 200, (path, response.data[:200])
    approve(pid)
    did, _ = s.deliver(ADMIN, pid, delivery(pid))
    assert client.get(f"/epp/entregas/{did}").status_code == 200
    response = client.get(f"/epp/entregas/{did}/pdf")
    assert response.status_code == 200 and response.data.startswith(b"%PDF")
    assert (
        client.get(
            root + f"/entregas/{did}/pdf", headers={"Authorization": "Bearer 11"}
        ).status_code
        == 403
    )
    assert (
        client.get(root + "/resumen?anio=2026", headers=headers).json["items"][0][
            "cantidad"
        ]
        == 1
    )
    assert client.get("/epp/reporte?formato=csv").status_code == 200
    assert (
        client.get(root + f"/imagenes/articulos/{schema}", headers=headers).status_code
        == 200
    )


def test_categories_and_foreign_catalog(schema):
    with pytest.raises(s.Error):
        s.save_category(BOSS, dict(nombre="Otra"))
    cid = s.save_category(ADMIN, dict(nombre="Protección lumbar"))
    s.save_category(ADMIN, dict(id=cid, nombre="Protección personal", activo=0))
    with pytest.raises(s.Error):
        s.save_article(
            ADMIN, dict(nombre="Faja", categoria="Protección personal", talles=["XL"])
        )
    with pytest.raises(s.Error):
        s.save_article(
            ADMIN, dict(nombre="Faja", categoria="Ropa", talles=["XL"], sectores=[999])
        )


def test_draft_transition_and_edit_history(schema):
    p = payload(schema, accion="borrador")
    pid, _ = s.create(OWNER, 10, p)
    assert s.detail(OWNER, pid)["estado"] == "borrador"
    with pytest.raises(s.Error):
        approve(pid)
    s.edit_order(OWNER, pid, dict(p, revision=1, accion="enviar"))
    row = s.detail(OWNER, pid)
    assert row["estado"] == "pendiente" and row["revision"] == 2
    assert any(h["accion"] == "editar_pedido" for h in row["historial"])
    approve(pid)
    with pytest.raises(s.Error):
        s.edit_order(OWNER, pid, dict(p, revision=3))


def test_actual_app_registration_and_csrf(monkeypatch):
    import app as main
    monkeypatch.setattr(main,'init_db',lambda:None)
    monkeypatch.setenv('SECRET_KEY','epp-test-session-key-0123456789012345')
    monkeypatch.setenv('JWT_SECRET','epp-test-jwt-key-01234567890123456789')
    app=main.create_app();client=app.test_client()
    assert any(r.rule=='/api/v1/mobile/epp/config' for r in app.url_map.iter_rules())
    assert client.post('/epp/catalogo',data={'nombre':'test'}).status_code==400
    assert client.post('/api/v1/mobile/epp/pedidos',json={}).status_code==401
