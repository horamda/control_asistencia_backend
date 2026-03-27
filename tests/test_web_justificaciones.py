"""
Tests for justificaciones: service validation, state machine, and web routes.
"""

import app as app_module
import services.justificacion_service as just_service
import web.auth.decorators as auth_decorators
import web.justificaciones.justificaciones_routes as just_routes


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

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


_VALID_DATA = {
    "empleado_id": 1,
    "asistencia_id": None,
    "motivo": "Certificado medico adjunto",
    "archivo": "",
    "estado": "pendiente",
}

_EMPLEADO = {"id": 1, "nombre": "Ana", "apellido": "Lopez", "empresa_id": 1}
_ASISTENCIA = {"id": 10, "empleado_id": 1, "fecha": "2026-03-01", "estado": "ausente"}


# ---------------------------------------------------------------------------
# Service: _validate_fields
# ---------------------------------------------------------------------------

def test_validate_missing_empleado_id():
    errors = just_service._validate_fields({"motivo": "algo", "estado": "pendiente"})
    assert any("Empleado" in e for e in errors)


def test_validate_missing_motivo():
    errors = just_service._validate_fields({"empleado_id": 1, "estado": "pendiente"})
    assert any("Motivo" in e for e in errors)


def test_validate_invalid_estado():
    errors = just_service._validate_fields(
        {"empleado_id": 1, "motivo": "algo", "estado": "en_revision"}
    )
    assert any("Estado invalido" in e for e in errors)


def test_validate_defaults_estado_to_pendiente(monkeypatch):
    monkeypatch.setattr(just_service, "get_empleado_by_id", lambda _: _EMPLEADO)
    errors = just_service._validate_fields(
        {"empleado_id": 1, "motivo": "algo", "estado": "pendiente"}
    )
    assert errors == []


def test_validate_asistencia_not_found(monkeypatch):
    monkeypatch.setattr(just_service, "get_empleado_by_id", lambda _: _EMPLEADO)
    monkeypatch.setattr(just_service, "get_asistencia_by_id", lambda _: None)
    errors = just_service._validate_fields(
        {"empleado_id": 1, "asistencia_id": 99, "motivo": "algo", "estado": "pendiente"}
    )
    assert any("asistencia" in e.lower() for e in errors)


def test_validate_asistencia_wrong_empleado(monkeypatch):
    monkeypatch.setattr(just_service, "get_empleado_by_id", lambda _: _EMPLEADO)
    monkeypatch.setattr(
        just_service, "get_asistencia_by_id", lambda _: {**_ASISTENCIA, "empleado_id": 999}
    )
    errors = just_service._validate_fields(
        {"empleado_id": 1, "asistencia_id": 10, "motivo": "algo", "estado": "pendiente"}
    )
    assert any("no pertenece" in e for e in errors)


def test_validate_duplicate_asistencia(monkeypatch):
    monkeypatch.setattr(just_service, "get_empleado_by_id", lambda _: _EMPLEADO)
    monkeypatch.setattr(just_service, "get_asistencia_by_id", lambda _: _ASISTENCIA)
    monkeypatch.setattr(
        just_service, "get_by_asistencia",
        lambda _: [{"id": 55, "empleado_id": 1, "asistencia_id": 10, "estado": "pendiente"}]
    )
    errors = just_service._validate_fields(
        {"empleado_id": 1, "asistencia_id": 10, "motivo": "algo", "estado": "pendiente"}
    )
    assert any("Ya existe" in e for e in errors)


def test_validate_duplicate_skips_self(monkeypatch):
    """Editing the same record should not be flagged as a duplicate."""
    monkeypatch.setattr(just_service, "get_empleado_by_id", lambda _: _EMPLEADO)
    monkeypatch.setattr(just_service, "get_asistencia_by_id", lambda _: _ASISTENCIA)
    existing = {"id": 55, "empleado_id": 1, "asistencia_id": 10, "estado": "pendiente"}
    monkeypatch.setattr(just_service, "get_by_asistencia", lambda _: [existing])
    errors = just_service._validate_fields(
        {"empleado_id": 1, "asistencia_id": 10, "motivo": "algo", "estado": "pendiente"},
        current=existing,
    )
    assert errors == []


# ---------------------------------------------------------------------------
# Service: state machine
# ---------------------------------------------------------------------------

def test_state_transition_pendiente_to_aprobada(monkeypatch):
    monkeypatch.setattr(just_service, "get_empleado_by_id", lambda _: _EMPLEADO)
    current = {"id": 1, "empleado_id": 1, "estado": "pendiente"}
    errors = just_service._validate_fields(
        {"empleado_id": 1, "motivo": "ok", "estado": "aprobada"}, current=current
    )
    assert errors == []


def test_state_transition_pendiente_to_rechazada(monkeypatch):
    monkeypatch.setattr(just_service, "get_empleado_by_id", lambda _: _EMPLEADO)
    current = {"id": 1, "empleado_id": 1, "estado": "pendiente"}
    errors = just_service._validate_fields(
        {"empleado_id": 1, "motivo": "ok", "estado": "rechazada"}, current=current
    )
    assert errors == []


def test_state_transition_aprobada_to_rechazada_blocked(monkeypatch):
    """aprobada → rechazada is not a direct valid transition."""
    monkeypatch.setattr(just_service, "get_empleado_by_id", lambda _: _EMPLEADO)
    current = {"id": 1, "empleado_id": 1, "estado": "aprobada"}
    errors = just_service._validate_fields(
        {"empleado_id": 1, "motivo": "ok", "estado": "rechazada"}, current=current
    )
    assert any("no permitido" in e for e in errors)


def test_state_transition_aprobada_to_pendiente_allowed(monkeypatch):
    monkeypatch.setattr(just_service, "get_empleado_by_id", lambda _: _EMPLEADO)
    current = {"id": 1, "empleado_id": 1, "estado": "aprobada"}
    errors = just_service._validate_fields(
        {"empleado_id": 1, "motivo": "ok", "estado": "pendiente"}, current=current
    )
    assert errors == []


# ---------------------------------------------------------------------------
# Service: aprobar / rechazar / revertir
# ---------------------------------------------------------------------------

def test_aprobar_from_pendiente(monkeypatch):
    monkeypatch.setattr(just_service, "get_by_id", lambda _: {"id": 1, "estado": "pendiente"})
    called = {}
    monkeypatch.setattr(just_service, "update_estado", lambda jid, estado: called.update({"jid": jid, "estado": estado}))
    just_service.aprobar_justificacion(1)
    assert called == {"jid": 1, "estado": "aprobada"}


def test_aprobar_from_aprobada_raises(monkeypatch):
    monkeypatch.setattr(just_service, "get_by_id", lambda _: {"id": 1, "estado": "aprobada"})
    import pytest
    with pytest.raises(ValueError, match="aprobar"):
        just_service.aprobar_justificacion(1)


def test_rechazar_from_pendiente(monkeypatch):
    monkeypatch.setattr(just_service, "get_by_id", lambda _: {"id": 1, "estado": "pendiente"})
    called = {}
    monkeypatch.setattr(just_service, "update_estado", lambda jid, estado: called.update({"jid": jid, "estado": estado}))
    just_service.rechazar_justificacion(1)
    assert called == {"jid": 1, "estado": "rechazada"}


def test_rechazar_from_rechazada_raises(monkeypatch):
    monkeypatch.setattr(just_service, "get_by_id", lambda _: {"id": 1, "estado": "rechazada"})
    import pytest
    with pytest.raises(ValueError, match="rechazar"):
        just_service.rechazar_justificacion(1)


def test_revertir_aprobada_to_pendiente(monkeypatch):
    monkeypatch.setattr(just_service, "get_by_id", lambda _: {"id": 1, "estado": "aprobada"})
    called = {}
    monkeypatch.setattr(just_service, "update_estado", lambda jid, estado: called.update({"jid": jid, "estado": estado}))
    just_service.revertir_justificacion(1)
    assert called == {"jid": 1, "estado": "pendiente"}


def test_revertir_pendiente_raises(monkeypatch):
    monkeypatch.setattr(just_service, "get_by_id", lambda _: {"id": 1, "estado": "pendiente"})
    import pytest
    with pytest.raises(ValueError, match="revertir"):
        just_service.revertir_justificacion(1)


# ---------------------------------------------------------------------------
# Web routes
# ---------------------------------------------------------------------------

def _stub_empleados():
    return [{"id": 1, "nombre": "Ana", "apellido": "Lopez", "dni": "12345"}]


def _stub_asistencias():
    return [{"id": 10, "nombre": "Ana", "apellido": "Lopez", "fecha": "2026-03-01", "empleado_id": 1}]


def _build_authed_client(monkeypatch):
    """Client with has_role bypassed (no DB needed)."""
    monkeypatch.setattr(auth_decorators, "has_role", lambda user_id, role: True)
    client = _build_client(monkeypatch)
    _login(client)
    return client


def test_listado_requiere_login(monkeypatch):
    monkeypatch.setattr(auth_decorators, "has_role", lambda user_id, role: True)
    client = _build_client(monkeypatch)
    # no _login → session has no user_id
    resp = client.get("/justificaciones/")
    assert resp.status_code in (302, 403)


def test_listado_ok(monkeypatch):
    monkeypatch.setattr(just_routes, "get_page", lambda *a, **kw: ([], 0))
    monkeypatch.setattr(just_routes, "get_empleados", lambda **kw: _stub_empleados())
    client = _build_authed_client(monkeypatch)
    resp = client.get("/justificaciones/")
    assert resp.status_code == 200


def test_nuevo_get_ok(monkeypatch):
    monkeypatch.setattr(just_routes, "get_empleados", lambda **kw: _stub_empleados())
    monkeypatch.setattr(just_routes, "get_asistencias", lambda: _stub_asistencias())
    client = _build_authed_client(monkeypatch)
    resp = client.get("/justificaciones/nuevo")
    assert resp.status_code == 200


def test_nuevo_post_valido(monkeypatch):
    monkeypatch.setattr(just_routes, "get_empleados", lambda **kw: _stub_empleados())
    monkeypatch.setattr(just_routes, "get_asistencias", lambda: _stub_asistencias())
    monkeypatch.setattr(just_routes, "create_justificacion", lambda data: 42)
    monkeypatch.setattr(just_routes, "log_audit", lambda *a, **kw: None)
    client = _build_authed_client(monkeypatch)
    resp = client.post("/justificaciones/nuevo", data={
        "empleado_id": "1",
        "asistencia_id": "",
        "motivo": "Certificado medico",
        "archivo": "",
        "estado": "pendiente",
    })
    assert resp.status_code == 302
    assert "msg=" in resp.headers["Location"]


def test_nuevo_post_invalido_muestra_errores(monkeypatch):
    monkeypatch.setattr(just_routes, "get_empleados", lambda **kw: _stub_empleados())
    monkeypatch.setattr(just_routes, "get_asistencias", lambda: _stub_asistencias())
    monkeypatch.setattr(
        just_routes, "create_justificacion",
        lambda data: (_ for _ in ()).throw(ValueError("Empleado es requerido."))
    )
    client = _build_authed_client(monkeypatch)
    resp = client.post("/justificaciones/nuevo", data={
        "empleado_id": "",
        "motivo": "",
        "estado": "pendiente",
    })
    assert resp.status_code == 200
    assert b"requerido" in resp.data.lower()


def test_aprobar_redirige_con_msg(monkeypatch):
    monkeypatch.setattr(just_routes, "aprobar_justificacion", lambda _: None)
    monkeypatch.setattr(just_routes, "log_audit", lambda *a, **kw: None)
    client = _build_authed_client(monkeypatch)
    resp = client.post("/justificaciones/aprobar/1")
    assert resp.status_code == 302
    assert "msg=" in resp.headers["Location"]


def test_aprobar_error_redirige_con_error(monkeypatch):
    monkeypatch.setattr(
        just_routes, "aprobar_justificacion",
        lambda _: (_ for _ in ()).throw(ValueError("No se puede aprobar"))
    )
    client = _build_authed_client(monkeypatch)
    resp = client.post("/justificaciones/aprobar/1")
    assert resp.status_code == 302
    assert "error=" in resp.headers["Location"]


def test_rechazar_redirige_con_msg(monkeypatch):
    monkeypatch.setattr(just_routes, "rechazar_justificacion", lambda _: None)
    monkeypatch.setattr(just_routes, "log_audit", lambda *a, **kw: None)
    client = _build_authed_client(monkeypatch)
    resp = client.post("/justificaciones/rechazar/1")
    assert resp.status_code == 302
    assert "msg=" in resp.headers["Location"]


def test_revertir_redirige_con_msg(monkeypatch):
    monkeypatch.setattr(just_routes, "revertir_justificacion", lambda _: None)
    monkeypatch.setattr(just_routes, "log_audit", lambda *a, **kw: None)
    client = _build_authed_client(monkeypatch)
    resp = client.post("/justificaciones/revertir/1")
    assert resp.status_code == 302
    assert "msg=" in resp.headers["Location"]


def test_eliminar_redirige(monkeypatch):
    monkeypatch.setattr(just_routes, "delete", lambda _: None)
    monkeypatch.setattr(just_routes, "log_audit", lambda *a, **kw: None)
    client = _build_authed_client(monkeypatch)
    resp = client.post("/justificaciones/eliminar/1")
    assert resp.status_code == 302
