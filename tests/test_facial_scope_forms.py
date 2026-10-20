from unittest.mock import MagicMock

import pytest
from flask import Flask
from werkzeug.exceptions import Forbidden
from web import facial_draft_forms as forms
from repositories import configuracion_empresa_repository as repo


@pytest.mark.parametrize("scope,table", [("branch", "sucursales"), ("employee", "empleados")])
def test_scoped_update_includes_company_and_atomic_audit(monkeypatch, scope, table):
    db = MagicMock()
    cursor = db.cursor.return_value
    cursor.fetchall.return_value = [("facial_policy_draft",), ("facial_policy_revision",)]
    cursor.rowcount = 1
    monkeypatch.setattr(repo, "get_db", lambda: db)
    repo.save_facial_draft(7, {}, revision=2, actor_id=9, scope=scope, record_id=8)
    update = cursor.execute.call_args_list[1]
    assert f"UPDATE {table}" in update.args[0]
    assert "AND empresa_id=%s" in update.args[0]
    assert update.args[1] == ("{}", 8, 2, 7)
    assert cursor.execute.call_args_list[2].args[1][-2:] == (table, 8)
    db.commit.assert_called_once()


@pytest.mark.parametrize("role,company,allowed", [
    ("admin", 7, True), ("admin", None, True),
    ("admin", 8, False), ("rrhh", 7, False),
])
def test_form_permissions_and_inheritance(monkeypatch, role, company, allowed):
    app = Flask(__name__)
    app.secret_key = "test"
    monkeypatch.setattr(forms, "get_panel_user", lambda _: {
        "rol": role, "empresa_id": company, "activo": 1,
    })
    save = MagicMock()
    monkeypatch.setattr(forms, "save_facial_draft", save)
    with app.test_request_context("/", method="POST", data={
        "action": "save_facial_draft", "facial_mode": "inherit", "facial_revision": "2",
    }):
        forms.session["user_id"] = 9
        record = {"id": 8, "empresa_id": 7, "facial_policy_revision": 2}
        if not allowed:
            with pytest.raises(Forbidden):
                forms.prepare_facial_form(record, scope="employee", return_url="/editar/8")
            save.assert_not_called()
        else:
            result = forms.prepare_facial_form(record, scope="employee", return_url="/editar/8")
            assert result.status_code == 302
            assert save.call_args.args == (7, {})


def test_legacy_schema_does_not_query_new_dependencies(monkeypatch):
    app = Flask(__name__)
    read = MagicMock(side_effect=AssertionError("unexpected read"))
    monkeypatch.setattr(forms, "get_panel_user", read)
    with app.test_request_context("/"):
        assert forms.prepare_facial_form({"id": 1}, scope="branch", return_url="/") is None
    read.assert_not_called()


def test_failed_draft_does_not_fall_into_entity_save(monkeypatch):
    app = Flask(__name__)
    app.secret_key = "test"
    monkeypatch.setattr(forms, "get_panel_user", lambda _: {
        "rol": "admin", "empresa_id": 7, "activo": 1,
    })
    monkeypatch.setattr(forms, "save_facial_draft", MagicMock(side_effect=ValueError("conflict")))
    with app.test_request_context("/", method="POST", data={
        "action": "save_facial_draft", "facial_mode": "trial", "facial_revision": "2",
    }):
        forms.session["user_id"] = 9
        record = {"id": 8, "empresa_id": 7, "facial_policy_revision": 2}
        assert forms.prepare_facial_form(record, scope="branch", return_url="/") is False
        assert record["facial_error"] == "conflict"
