import datetime as dt
from unittest.mock import MagicMock

import pytest
from flask import Flask
from jinja2 import ChoiceLoader, DictLoader, FileSystemLoader

import services.feedback_dates_service as svc
import web.auth.decorators as auth
import web.feedback.feedback_routes as routes


def record():
    return dict(id=1, motivo_id=2, estado="resuelto", estado_actual="resuelto",
                created_at=dt.datetime(2026, 9, 1, 10), resuelto_at=dt.datetime(2026, 9, 3, 11),
                fecha_limite=dt.datetime(2026, 9, 3, 10), fecha_vencimiento=dt.date(2026, 9, 3),
                resuelto_en_sla=0, updated_at=dt.datetime(2026, 9, 3, 11),
                condicion_temporal="resuelto_fuera_termino", empleado_nombre="Ana", numero="FB-1")


def form(row):
    return dict(created_at="2026-09-02T10:00:00", resuelto_at="2026-09-03T11:00:00",
                version=svc.date_version(row), motivo_correccion="Corrección de carga")


def test_dates_change_deadline_and_result():
    result = svc.calculate_dates(record(), {"sla_dias": 2}, form(record()))
    assert result["fecha_limite"] == dt.datetime(2026, 9, 4, 10)
    assert result["resuelto_en_sla"] == 1
    assert result["fecha_vencimiento"] == dt.date(2026, 9, 4)


def test_resolution_only_preserves_deadline_and_recomputes_result():
    row = record()
    data = form(row) | {"created_at": row["created_at"].isoformat(), "resuelto_at": "2026-09-02T10:00"}
    result = svc.calculate_dates(row, {"sla_dias": 99}, data)
    assert result["fecha_limite"] == row["fecha_limite"]
    assert result["resuelto_en_sla"] == 1


def test_hours_and_pending():
    row = record() | {"estado": "pendiente", "resuelto_at": None}
    result = svc.calculate_dates(row, {"tiempo_resolucion_valor": 3, "tiempo_resolucion_unidad": "HORAS"}, form(row) | {"resuelto_at": ""})
    assert result["fecha_limite"] == dt.datetime(2026, 9, 2, 13)
    assert result["resuelto_at"] is None


@pytest.mark.parametrize("updates", [{"created_at": "bad"}, {"resuelto_at": ""}, {"resuelto_at": "2026-08-01T10:00"}, {"created_at": "2026-09-01T10:00+03:00"}])
def test_invalid_dates(updates):
    with pytest.raises(ValueError):
        svc.calculate_dates(record(), {"sla_dias": 2}, form(record()) | updates)


def database(monkeypatch):
    db = MagicMock()
    cursor = db.cursor.return_value
    cursor.fetchone.side_effect = [record(), {"sla_dias": 2}]
    monkeypatch.setattr(svc, "get_db", lambda: db)
    return db, cursor


def test_atomic_audit_and_values(monkeypatch):
    db, cur = database(monkeypatch)
    svc.correct_dates(1, form(record()), 99)
    db.commit.assert_called_once()
    db.rollback.assert_not_called()
    inserts = [c.args[1] for c in cur.execute.call_args_list if "INSERT INTO auditoria" in c.args[0]]
    assert inserts and all(c[0] == 99 and c[2:] == ("feedback_fechas", 1) and len(c[1]) <= 255 for c in inserts)
    assert any("2026-09-01 10:00:00 -> 2026-09-02 10:00:00" in c[1] for c in inserts)


def test_audit_failure_rolls_back(monkeypatch):
    db, cur = database(monkeypatch)
    def execute(sql, params):
        if "INSERT INTO auditoria" in sql:
            raise RuntimeError("audit unavailable")
    cur.execute.side_effect = execute
    with pytest.raises(RuntimeError):
        svc.correct_dates(1, form(record()), 99)
    db.commit.assert_not_called()
    db.rollback.assert_called_once()


def test_concurrent_edit_rejected(monkeypatch):
    db, cur = database(monkeypatch)
    with pytest.raises(ValueError, match="cambió"):
        svc.correct_dates(1, form(record()) | {"version": "old"}, 99)
    assert not any("UPDATE" in c.args[0] and "SELECT" not in c.args[0] for c in cur.execute.call_args_list)
    db.commit.assert_not_called()


def client(monkeypatch, role="admin", active=True):
    app = Flask(__name__)
    app.secret_key = "test"
    app.jinja_loader = ChoiceLoader([DictLoader({"base.html": "{% block content %}{% endblock %}"}), FileSystemLoader("templates")])
    app.jinja_env.globals["csrf_token"] = lambda: "test-token"
    app.register_blueprint(routes.feedback_web_bp)
    monkeypatch.setattr(auth, "get_web_user_by_id", lambda uid: {"id": uid, "rol": role, "activo": active})
    monkeypatch.setattr(auth, "can_access_module", lambda *args: True)
    result = app.test_client()
    with result.session_transaction() as session:
        session["user_id"] = 99
    return result


@pytest.mark.parametrize("role,active", [("rrhh", True), ("supervisor", True), ("jefe", True), ("admin", False)])
def test_strict_access_even_with_feedback_permission(monkeypatch, role, active):
    c = client(monkeypatch, role, active)
    assert c.get("/feedback/correccion-fechas").status_code == 403
    assert c.get("/feedback/correccion-fechas/1").status_code == 403
    assert c.post("/feedback/correccion-fechas/1", data=form(record())).status_code == 403


def test_admin_render_and_save(monkeypatch):
    c = client(monkeypatch)
    monkeypatch.setattr(routes, "get_feedback_by_id", lambda fid: record())
    save = MagicMock()
    monkeypatch.setattr(routes, "correct_dates", save)
    response = c.get("/feedback/correccion-fechas/1")
    assert response.status_code == 200
    assert b'datetime-local' in response.data and b'csrf_token' in response.data
    response = c.post("/feedback/correccion-fechas/1", data=form(record()))
    assert response.status_code == 302
    save.assert_called_once()


def test_audit_hidden_from_non_admin(monkeypatch):
    import repositories.auditoria_repository as audit
    db = MagicMock()
    db.cursor.return_value.fetchone.return_value = {"total": 0}
    monkeypatch.setattr(audit, "get_db", lambda: db)
    audit.get_page(1, 20)
    for call in db.cursor.return_value.execute.call_args_list:
        assert "feedback_fechas" in call.args[0]
        assert call.args[1][0] is False


def test_full_app_templates_csrf_and_navigation(monkeypatch):
    import app as app_module
    monkeypatch.setattr(app_module, "init_db", lambda: None)
    monkeypatch.setattr(auth, "get_web_user_by_id", lambda uid: {"id": uid, "rol": "admin", "activo": True})
    monkeypatch.setattr(routes, "get_feedback_by_id", lambda fid: record())
    monkeypatch.setattr(routes, "get_feedbacks_page", lambda *a, **kw: ([record()], 1))
    monkeypatch.setattr(routes, "get_sucursales", lambda **kw: [])
    monkeypatch.setattr(routes, "get_empleados", lambda **kw: [])
    monkeypatch.setattr(routes, "get_motivos", lambda **kw: [])
    monkeypatch.setattr(routes, "get_sectores", lambda **kw: [])
    app = app_module.create_app()
    app.config.update(TESTING=True, WTF_CSRF_ENABLED=True)
    c = app.test_client()
    assert c.get("/feedback/correccion-fechas").status_code == 302
    with c.session_transaction() as session:
        session["user_id"] = 99
    response = c.get("/feedback/correccion-fechas")
    assert response.status_code == 200
    assert "Corrección FDBK" in response.get_data(as_text=True)
    response = c.get("/feedback/correccion-fechas/1")
    assert response.status_code == 200
    assert c.post("/feedback/correccion-fechas/1", data=form(record())).status_code == 400


def test_nonadmin_navigation_hidden(monkeypatch):
    c = client(monkeypatch, "rrhh")
    with c.application.test_request_context():
        from flask import session
        session["user_id"] = 99
        assert routes.feedback_dates_context()["can_correct_feedback_dates"]() is False


def test_pending_cannot_receive_resolution():
    with pytest.raises(ValueError, match="Solo se puede"):
        svc.calculate_dates(record() | {"estado": "pendiente"}, {"sla_dias": 2}, form(record()))


def test_reason_required_before_database(monkeypatch):
    db = MagicMock()
    monkeypatch.setattr(svc, "get_db", db)
    with pytest.raises(ValueError):
        svc.correct_dates(1, form(record()) | {"motivo_correccion": ""}, 99)
    db.assert_not_called()


def test_filter_dates_include_entire_last_day_and_exact_client(monkeypatch):
    import repositories.feedback_repository as repo
    fetch = MagicMock(return_value=([], 0))
    monkeypatch.setattr(repo, "_fetch_page", fetch)
    repo.get_page(1, 20, cliente_codigo="00123", carga_desde=dt.date(2026, 9, 1),
                  carga_hasta=dt.date(2026, 9, 14), resolucion_hasta=dt.date(2026, 9, 15),
                  empleado_id=5, motivo_id=2)
    sql, params = fetch.call_args.args[2:]
    assert "f.created_at >= %s" in sql and "f.created_at < %s" in sql
    assert "f.resuelto_at < %s" in sql
    assert "COALESCE(c.codigo_externo, f.cliente_codigo_snapshot) = %s" in sql
    assert params == [5, 2, "00123", dt.date(2026, 9, 1), dt.date(2026, 9, 15), dt.date(2026, 9, 16)]


def test_filter_validation_and_pagination(monkeypatch):
    c = client(monkeypatch)
    for name in ("get_sucursales", "get_empleados", "get_motivos", "get_sectores"):
        monkeypatch.setattr(routes, name, lambda **kw: [])
    fetch = MagicMock(return_value=([], 45))
    monkeypatch.setattr(routes, "get_feedbacks_page", fetch)
    response = c.get("/feedback/correccion-fechas?cliente_codigo=00123&carga_desde=2026-09-01&motivo_id=2")
    assert response.status_code == 200
    assert fetch.call_args.kwargs["carga_desde"] == dt.date(2026, 9, 1)
    assert fetch.call_args.kwargs["motivo_id"] == 2
    from html import unescape
    import re
    links = re.findall(r'href="([^"]+)"', unescape(response.get_data(as_text=True)))
    assert any("page=2" in link and "cliente_codigo=00123" in link and "carga_desde=2026-09-01" in link for link in links)
    fetch.reset_mock()
    response = c.get("/feedback/correccion-fechas?carga_desde=2026-09-15&carga_hasta=2026-09-01")
    assert "Revisá las fechas" in response.get_data(as_text=True)
    fetch.assert_not_called()
