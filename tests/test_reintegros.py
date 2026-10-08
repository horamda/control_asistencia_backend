"""Reimbursement lifecycle and tenant authorization on an isolated MariaDB."""

import json
import io
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
from datetime import datetime
from pathlib import Path
from uuid import uuid4
import pytest
from flask import Flask
from werkzeug.datastructures import MultiDict
from tests.test_seguridad import database, employee, photo
from services import reintegro_service as s
from routes import reintegro_routes as mobile, carga_routes
from web.reintegros import reintegro_routes as web
import web.auth.decorators as auth
import utils.jwt_guard as jwt

OWNER = dict(mode="empleado", empresa_id=1, empleado_id=10)
BOSS = dict(
    mode="web",
    empresa_id=1,
    empleado_id=11,
    user_id=99,
    review=True,
    review_global=False,
    pay=False,
)
HR = dict(
    mode="web",
    empresa_id=1,
    empleado_id=None,
    user_id=98,
    review=True,
    review_global=True,
    pay=True,
    **{"global": True},
)


@pytest.fixture(autouse=True)
def schema(database, monkeypatch):
    monkeypatch.setattr(s, "now_local", lambda: datetime(2026, 10, 8, 12))
    monkeypatch.setattr(s.monthly, "now_local", lambda: datetime(2026, 10, 8, 12))
    with s.db.transaction() as c:
        c.execute("ALTER TABLE empleados ADD reporta_a_empleado_id INT NULL")
        c.execute("UPDATE empleados SET reporta_a_empleado_id=11 WHERE id=10")
        for sql in (
            (
                Path(__file__).resolve().parents[1]
                / "migrations/20261007_02_reintegros.sql"
            )
            .read_text(encoding="utf-8")
            .split(";")
        ):
            if sql.strip():
                c.execute(sql)
        c.execute(
            "ALTER TABLE sectores ADD empresa_id INT DEFAULT 1, ADD activo INT DEFAULT 1"
        )
        from scripts.migrate_20261008_01_reintegros_mensuales import migrate_cursor

        migrate_cursor(c)
        c.execute("INSERT INTO reintegro_sectores VALUES(1,1)")
        c.execute(
            "INSERT INTO reintegro_categorias(empresa_id,nombre) VALUES(1,'General')"
        )


def payload(**kw):
    return dict(
        dict(
            envio_id=str(uuid4()),
            accion="enviar",
            periodo="2026-09",
            gastos=[
                dict(
                    fecha="2026-09-01", concepto="Peaje", importe="0.10", categoria_id=1
                ),
                dict(
                    fecha="2026-09-01",
                    concepto="Comida",
                    importe="0.20",
                    categoria_id=1,
                ),
            ],
        ),
        **kw,
    )


def photos():
    return MultiDict([("fotos_0", photo()), ("fotos_1", photo())])


def create(**kw):
    return s.store(employee(), payload(**kw), photos())[0]


def resolve(rid, who=BOSS, revision=1):
    row = s.detail(who, rid)
    s.transition(
        who,
        rid,
        dict(
            accion="resolver",
            revision=revision,
            decisiones=[dict(id=g["id"], decision="aprobado") for g in row["gastos"]],
        ),
    )


def test_total_single_approval_and_payment():
    rid = create()
    row = s.detail(OWNER, rid)
    assert row["total_solicitado"] == Decimal("0.30")
    assert s.history(BOSS, {})["total"] == 1
    resolve(rid)
    with pytest.raises(s.Error):
        resolve(rid, HR)
    with pytest.raises(s.Error):
        s.transition(BOSS, rid, dict(accion="pagar", revision=2))
    s.transition(
        HR,
        rid,
        dict(
            accion="pagar",
            revision=2,
            fecha_pago=str(s.now_local().date()),
            referencia_pago="Transferencia 123",
        ),
    )
    assert s.detail(OWNER, rid)["estado"] == "pagada"
    with pytest.raises(s.Error):
        s.transition(HR, rid, dict(accion="pagar", revision=3))


def test_partial_approval_and_validation_rollback():
    rid = create()
    g = s.detail(BOSS, rid)["gastos"]
    decisions = [
        dict(id=g[0]["id"], decision="aprobado"),
        dict(id=g[1]["id"], decision="rechazado"),
    ]
    with pytest.raises(s.Error):
        s.transition(
            BOSS, rid, dict(accion="resolver", revision=1, decisiones=decisions)
        )
    assert all(g["decision"] == "pendiente" for g in s.detail(OWNER, rid)["gastos"])
    decisions[1]["motivo"] = "No corresponde"
    s.transition(BOSS, rid, dict(accion="resolver", revision=1, decisiones=decisions))
    assert s.detail(OWNER, rid)["total_aprobado"] == Decimal("0.10")


def test_tenant_owner_current_boss_and_payment_role_boundaries():
    rid = create()
    fid = s.detail(OWNER, rid)["gastos"][0]["fotos"][0]["id"]
    for who in [
        dict(OWNER, empleado_id=13),
        dict(HR, empresa_id=2),
        dict(BOSS, empleado_id=13),
    ]:
        with pytest.raises(s.Error):
            s.detail(who, rid)
        with pytest.raises(s.Error):
            s.photo(who, fid)
    with pytest.raises(s.Error):
        resolve(rid, dict(HR, empleado_id=10))
    # A payment clerk sees company requests but cannot approve another manager's reports.
    with pytest.raises(s.Error):
        resolve(rid, dict(BOSS, empleado_id=13, pay=True, **{"global": True}))
    with s.db.transaction() as c:
        c.execute("UPDATE empleados SET reporta_a_empleado_id=13 WHERE id=10")
    with pytest.raises(s.Error):
        resolve(rid)
    resolve(rid, dict(BOSS, empleado_id=13))


def test_return_edit_draft_idempotence_and_cancel():
    data = payload()
    rid, created = s.store(employee(), data, photos())
    assert created
    assert s.store(employee(), data, photos()) == (rid, False)
    with pytest.raises(s.Error):
        s.store(employee(), dict(data, observaciones="Diferente"), photos())
    s.transition(
        HR, rid, dict(accion="devolver", revision=1, motivo="Comprobante ilegible")
    )
    s.store(employee(), dict(data, revision=2), photos(), rid)
    assert s.detail(OWNER, rid)["revision"] == 3
    with s.db.transaction(read_only=True) as c:
        assert (
            s.db.one(
                c,
                "SELECT COUNT(*) n FROM reintegro_gastos WHERE solicitud_id=%s AND activo=0",
                (rid,),
            )["n"]
            == 2
        )
    s.transition(OWNER, rid, dict(accion="cancelar", revision=3))
    draft = s.store(
        employee(),
        payload(accion="borrador", periodo="2026-10", gastos=[]),
        MultiDict(),
    )[0]
    for who in [BOSS, HR]:
        assert s.detail(who, draft)["estado"] == "borrador"
    assert s.detail(OWNER, draft)["estado"] == "borrador"


@pytest.mark.parametrize(
    "value", ["0", "-1", "1.001", 1.2, "1,20", "NaN", "1e4", "9999999999.99"]
)
def test_invalid_amounts(value):
    with pytest.raises(s.Error):
        s.amount(value)


def test_missing_photo_category_and_bad_page():
    with pytest.raises(s.Error):
        s.store(employee(), payload(), MultiDict())
    with pytest.raises(s.Error):
        s.history(OWNER, {"page": "bad"})
    with pytest.raises(s.Error):
        s.history(OWNER, {"desde": "2026-09-10", "hasta": "2026-09-01"})
    s.save_category(1, 99, dict(nombre="Comida"))
    cid = s.categories(1)[0]["id"]
    data = payload()
    data["gastos"][0]["categoria_id"] = cid
    rid = s.store(employee(), data, photos())[0]
    s.save_category(1, 99, dict(id=cid, nombre="Comida", activo="0"))
    assert s.detail(OWNER, rid)["gastos"][0]["categoria_nombre"] == "Comida"
    with pytest.raises(s.Error):
        s.store(employee(), dict(data, envio_id=str(uuid4())), photos())


@pytest.fixture
def client(monkeypatch):
    app = Flask(
        __name__, template_folder=str(Path(__file__).resolve().parents[1] / "templates")
    )
    app.secret_key = "test"
    app.config["TESTING"] = True
    app.register_blueprint(mobile.reintegros_mobile_bp)
    app.register_blueprint(web.reintegros_web_bp)
    app.jinja_env.globals.update(
        csrf_token=lambda: "test",
        can_web=lambda code, *args: code in ("reintegros", "reintegros_pagos"),
        export_toolbar={"enabled": False, "items": []},
    )
    monkeypatch.setattr(auth, "can_access_module", lambda *args: True)
    monkeypatch.setattr(web, "can_access_module", lambda *args: True)
    monkeypatch.setattr(
        web,
        "_cached_web_user",
        lambda uid: dict(id=uid, empresa_id=1, rol="rrhh", activo=1, empleado_id=None),
    )
    monkeypatch.setattr(
        jwt, "verificar_token", lambda token: dict(empleado_id=int(token))
    )
    monkeypatch.setattr(carga_routes, "get_by_id", employee)
    result = app.test_client()
    with result.session_transaction() as sess:
        sess["user_id"] = 99
    return result


def test_http_contract_templates_and_privacy(client):
    base = "/api/v1/mobile/reintegros"
    headers = {"Authorization": "Bearer 10"}
    assert client.get(base + "/config").status_code == 401
    assert client.get(base + "/config", headers=headers).json["moneda"] == "ARS"
    p = payload()
    p["gastos"] = json.dumps(p["gastos"])
    p.update(fotos_0=(photo().stream, "a.png"), fotos_1=(photo().stream, "b.png"))
    response = client.post(base + "/solicitudes", data=p, headers=headers)
    assert response.status_code == 201, response.json
    rid = response.json["solicitud"]["id"]
    fid = response.json["solicitud"]["gastos"][0]["fotos"][0]["id"]
    assert response.json["solicitud"]["total_solicitado"] == "0.30"
    assert (
        client.get(
            base + f"/fotos/{fid}", headers={"Authorization": "Bearer 20"}
        ).status_code
        == 404
    )
    assert (
        client.get(base + f"/fotos/{fid}", headers=headers).headers["Cache-Control"]
        == "private, no-store"
    )
    for path in [
        "/reintegros/",
        "/reintegros/categorias",
        f"/reintegros/solicitudes/{rid}",
        "/reintegros/exportar.csv",
    ]:
        r = client.get(path)
        assert r.status_code == 200, (path, r.data[:300])
    assert (
        client.post(
            base + f"/solicitudes/{rid}/acciones",
            json={"accion": "resolver", "revision": 1},
            headers=headers,
        ).status_code
        == 403
    )
    assert (
        client.get(base + "/solicitudes?page=bad", headers=headers).status_code == 400
    )
    assert client.get(base + "/solicitudes", headers=headers).json["total"] == 1


def test_simultaneous_review_has_one_winner():
    rid = create()

    def run(who):
        try:
            resolve(rid, who)
            return "ok"
        except s.Error as error:
            return error.status

    with ThreadPoolExecutor(max_workers=2) as pool:
        result = list(pool.map(run, [BOSS, HR]))
    assert sorted(map(str, result)) == ["409", "ok"]
    assert s.detail(OWNER, rid)["revision"] == 2


def test_simultaneous_retry_creates_one_request():
    data = payload()
    emp = employee()
    with ThreadPoolExecutor(max_workers=2) as pool:
        result = list(pool.map(lambda _: s.store(emp, data, photos()), [0, 1]))
    assert result[0][0] == result[1][0]
    assert sum(created for _, created in result) == 1


def test_web_actions_and_permission_failures(client, monkeypatch):
    rid = create()
    row = s.detail(HR, rid)
    form = dict(accion="resolver", revision=1)
    for g in row["gastos"]:
        form["decision_" + str(g["id"])] = "aprobado"
    assert (
        client.post(f"/reintegros/solicitudes/{rid}/acciones", data=form).status_code
        == 302
    )
    assert client.get(f"/reintegros/solicitudes/{rid}").status_code == 200
    assert (
        client.post(
            f"/reintegros/solicitudes/{rid}/acciones",
            data=dict(
                accion="pagar",
                revision=2,
                fecha_pago=str(s.now_local().date()),
                referencia_pago="Caja",
            ),
        ).status_code
        == 302
    )
    assert client.get(f"/reintegros/solicitudes/{rid}").status_code == 200
    monkeypatch.setattr(auth, "can_access_module", lambda *args: False)
    assert client.get("/reintegros/").status_code == 403


def test_actual_app_registration_and_csrf(monkeypatch):
    import app as main

    monkeypatch.setattr(main, "init_db", lambda: None)
    monkeypatch.setenv("SECRET_KEY", "reintegros-test-session-key-0123456789")
    monkeypatch.setenv("JWT_SECRET", "reintegros-test-jwt-key-01234567890123456789")
    app = main.create_app()
    client = app.test_client()
    assert any(
        r.rule == "/api/v1/mobile/reintegros/solicitudes"
        for r in app.url_map.iter_rules()
    )
    assert (
        client.post(
            "/reintegros/solicitudes/1/acciones", data={"accion": "pagar"}
        ).status_code
        == 400
    )
    # Bearer-only API bypasses CSRF but still requires authentication.
    assert (
        client.post("/api/v1/mobile/reintegros/solicitudes", json={}).status_code == 401
    )


def test_web_validation_error_and_missing_migration(client):
    assert client.get("/reintegros/?page=bad").status_code == 400
    with s.db.transaction() as c:
        c.execute("DROP TABLE reintegro_auditoria")
    # A missing module table must not expose a SQL traceback to mobile or panel.
    with s.db.transaction() as c:
        c.execute("DROP TABLE reintegro_fotos")
    with s.db.transaction() as c:
        c.execute("DROP TABLE reintegro_gastos")
    with s.db.transaction() as c:
        c.execute("DROP TABLE reintegro_odometros")
        c.execute("DROP TABLE reintegro_solicitudes")
    assert client.get("/reintegros/").status_code == 503
    assert (
        client.get(
            "/api/v1/mobile/reintegros/solicitudes",
            headers={"Authorization": "Bearer 10"},
        ).status_code
        == 503
    )


def admin_form(**kwargs):
    return dict(
        dict(
            envio_id=str(uuid4()),
            empleado_id="10",
            periodo="2026-09",
            categoria_0="1",
            linea=["0"],
            fecha_0="2026-09-01",
            concepto_0="Taxi",
            importe_0="1500.50",
            fotos_0=(photo().stream, "ticket.png"),
        ),
        **kwargs,
    )


def test_admin_create_edit_retain_receipt_and_cancel(client):
    assert client.get("/reintegros/nuevo").status_code == 200
    result = client.post("/reintegros/nuevo", data=admin_form())
    assert result.status_code == 302, result.data
    rid = s.history(OWNER, {})["items"][0]["id"]
    row = s.detail(HR, rid)
    fid = row["gastos"][0]["fotos"][0]["id"]
    assert row["auditoria"][0]["accion"] == "crear_admin"
    assert row["auditoria"][0]["usuario_id"] == 99
    assert client.get(f"/reintegros/solicitudes/{rid}/editar").status_code == 200
    # A browser includes an empty file part if no new file is chosen.
    data = admin_form(
        revision="1",
        importe_0="1600.25",
        conservar_0=str(fid),
        fotos_0=(io.BytesIO(b""), ""),
    )
    result = client.post(f"/reintegros/solicitudes/{rid}/editar", data=data)
    assert result.status_code == 302, result.data
    row = s.detail(OWNER, rid)
    assert row["total_solicitado"] == Decimal("1600.25") and row["revision"] == 2
    assert s.photo(OWNER, row["gastos"][0]["fotos"][0]["id"])["contenido"]
    assert (
        client.post(
            f"/reintegros/solicitudes/{rid}/acciones",
            data=dict(accion="cancelar", revision=2),
        ).status_code
        == 400
    )
    assert (
        client.post(
            f"/reintegros/solicitudes/{rid}/acciones",
            data=dict(accion="cancelar", revision=2, motivo="Carga duplicada"),
        ).status_code
        == 302
    )
    assert s.detail(OWNER, rid)["estado"] == "cancelada"
    assert client.get(f"/reintegros/solicitudes/{rid}/editar").status_code == 409


def test_admin_receipts_permissions_company_and_locked_state(client, monkeypatch):
    rid = create()
    other = create(
        periodo="2026-10",
        gastos=[
            dict(fecha="2026-10-01", concepto="Otro", importe="0.10", categoria_id=1),
            dict(fecha="2026-10-01", concepto="Otro 2", importe="0.20", categoria_id=1),
        ],
    )
    foreign = s.detail(HR, other)["gastos"][0]["fotos"][0]["id"]
    data = admin_form(revision="1", conservar_0=str(foreign))
    assert (
        client.post(f"/reintegros/solicitudes/{rid}/editar", data=data).status_code
        == 400
    )
    assert (
        client.post("/reintegros/nuevo", data=admin_form(empleado_id="20")).status_code
        == 403
    )
    assert s.detail(OWNER, rid)["revision"] == 1
    resolve(rid)
    assert (
        client.post(
            f"/reintegros/solicitudes/{rid}/editar", data=admin_form(revision="2")
        ).status_code
        == 409
    )
    assert (
        client.post(
            f"/reintegros/solicitudes/{rid}/acciones",
            data=dict(accion="cancelar", revision=2, motivo="No"),
        ).status_code
        == 409
    )
    monkeypatch.setattr(
        auth, "can_access_module", lambda uid, module, action="ver": action == "ver"
    )
    assert client.post("/reintegros/nuevo", data=admin_form()).status_code == 403
    assert client.get(f"/reintegros/solicitudes/{other}/editar").status_code == 403


def test_admin_manager_can_only_create_for_direct_reports():
    manager = dict(BOSS, manage_create=True, manage_edit=True)
    with pytest.raises(s.Error):
        s.store(employee(13), payload(), photos(), web_actor=manager)
    rid, _ = s.store(employee(10), payload(), photos(), web_actor=manager)
    assert s.detail(OWNER, rid)["estado"] == "pendiente"
    with pytest.raises(s.Error):
        s.store(employee(10), payload(), photos(), web_actor=BOSS)
