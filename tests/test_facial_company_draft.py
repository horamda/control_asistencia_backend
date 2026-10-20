from unittest.mock import MagicMock

import pytest
from flask import Flask

from repositories import configuracion_empresa_repository as repo
from web.configuracion import configuracion_empresa_routes as routes


@pytest.fixture
def connection(monkeypatch):
    db = MagicMock()
    cursor = db.cursor.return_value
    cursor.fetchall.return_value = [("facial_policy_draft",), ("facial_policy_revision",)]
    cursor.rowcount = 1
    monkeypatch.setattr(repo, "get_db", lambda: db)
    return db, cursor


def test_draft_and_audit_share_commit(connection):
    db, cursor = connection
    repo.save_facial_draft(1, {"mode": "trial"}, revision=0, actor_id=9)
    calls = cursor.execute.call_args_list
    assert len(calls) == 3
    assert "UPDATE configuracion_empresa" in calls[1].args[0]
    assert "INSERT INTO auditoria" in calls[2].args[0]
    assert calls[1].args[1][1:] == (1, 0)
    db.commit.assert_called_once()
    db.rollback.assert_not_called()


@pytest.mark.parametrize("failure", ["migration", "conflict", "audit"])
def test_failed_save_rolls_back(connection, failure):
    db, cursor = connection
    if failure == "migration":
        cursor.fetchall.return_value = []
    elif failure == "conflict":
        cursor.rowcount = 0
    else:
        cursor.execute.side_effect = [None, None, RuntimeError("audit unavailable")]
    with pytest.raises((ValueError, RuntimeError)):
        repo.save_facial_draft(1, {"mode": "required"}, revision=0, actor_id=9)
    db.commit.assert_not_called()
    db.rollback.assert_called_once()
    db.close.assert_called_once()


@pytest.fixture
def client(monkeypatch):
    app = Flask(__name__)
    app.secret_key = "unit-test-only"
    app.register_blueprint(routes.configuracion_bp)
    # Exercise the route body; authorization decorator has its own test suite.
    app.view_functions["configuracion_empresa.editar"] = routes.editar.__wrapped__
    monkeypatch.setattr(routes, "get_empresas", lambda **kw: [{"id": 1}])
    monkeypatch.setattr(routes, "get_by_empresa_id", lambda _: {
        "empresa_id": 1, "facial_policy_revision": 0,
    })
    monkeypatch.setattr(routes, "render_template", lambda *args, **kw: kw.get("error") or "form")
    with app.test_client() as client:
        with client.session_transaction() as session:
            session["user_id"] = 9
        yield client


@pytest.mark.parametrize("company,role,active", [(2, "admin", 1), (1, "rrhh", 1), (1, "admin", 0)])
def test_draft_rejects_unauthorized_scope(client, monkeypatch, company, role, active):
    monkeypatch.setattr(routes, "get_panel_user", lambda _: {
        "empresa_id": company, "rol": role, "activo": active,
    })
    save = MagicMock()
    monkeypatch.setattr(routes, "save_facial_draft", save)
    response = client.post("/configuracion-empresa/editar/1", data={"action": "save_facial_draft"})
    assert response.status_code == 403
    save.assert_not_called()


def test_draft_does_not_save_attendance_settings(client, monkeypatch):
    monkeypatch.setattr(routes, "get_panel_user", lambda _: {
        "empresa_id": 1, "rol": "admin", "activo": 1,
    })
    save = MagicMock()
    original = MagicMock()
    monkeypatch.setattr(routes, "save_facial_draft", save)
    monkeypatch.setattr(routes, "upsert", original)
    response = client.post("/configuracion-empresa/editar/1", data={
        "action": "save_facial_draft", "facial_mode": "trial", "facial_revision": "0",
    })
    assert response.status_code == 302
    save.assert_called_once_with(1, {"mode": "trial"}, revision=0, actor_id=9)
    original.assert_not_called()
