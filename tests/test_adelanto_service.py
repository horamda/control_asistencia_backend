import pytest

import services.adelanto_service as adelanto_service


def test_get_adelanto_mes_actual_usa_periodo_derivado_de_fecha(monkeypatch):
    captured = {}

    def _fake_get_by_empleado_periodo(empleado_id, periodo_year, periodo_month):
        captured.update(
            {
                "empleado_id": empleado_id,
                "periodo_year": periodo_year,
                "periodo_month": periodo_month,
            }
        )
        return None

    monkeypatch.setattr(adelanto_service, "get_by_empleado_periodo", _fake_get_by_empleado_periodo)

    adelanto_service.get_adelanto_mes_actual(10, fecha_solicitud="2026-04-17")

    assert captured == {
        "empleado_id": 10,
        "periodo_year": 2026,
        "periodo_month": 4,
    }


def test_solicitar_adelanto_ok(monkeypatch):
    created = {}

    monkeypatch.setattr(
        adelanto_service,
        "get_empleado_by_id",
        lambda empleado_id: {"id": empleado_id, "empresa_id": 3},
    )
    monkeypatch.setattr(adelanto_service, "get_by_empleado_periodo", lambda *args: None)
    monkeypatch.setattr(
        adelanto_service,
        "create",
        lambda data: created.update(data) or 81,
    )

    adelanto_id = adelanto_service.solicitar_adelanto(
        empleado_id=10,
        empresa_id=3,
        fecha_solicitud="2026-04-17",
    )

    assert adelanto_id == 81
    assert created["empleado_id"] == 10
    assert created["empresa_id"] == 3
    assert created["periodo_year"] == 2026
    assert created["periodo_month"] == 4
    assert created["fecha_solicitud"] == "2026-04-17"
    assert created["estado"] == "pendiente"


def test_solicitar_adelanto_rechaza_duplicado_logico(monkeypatch):
    monkeypatch.setattr(
        adelanto_service,
        "get_empleado_by_id",
        lambda empleado_id: {"id": empleado_id, "empresa_id": 3},
    )
    monkeypatch.setattr(
        adelanto_service,
        "get_by_empleado_periodo",
        lambda *args: {"id": 99, "periodo_year": 2026, "periodo_month": 4},
    )

    with pytest.raises(
        adelanto_service.AdelantoAlreadyRequestedError,
        match="Ya solicitaste un adelanto en este mes",
    ):
        adelanto_service.solicitar_adelanto(
            empleado_id=10,
            empresa_id=3,
            fecha_solicitud="2026-04-17",
        )


def test_solicitar_adelanto_rechaza_duplicado_por_constraint(monkeypatch):
    class DuplicatePeriodError(Exception):
        errno = 1062

    monkeypatch.setattr(
        adelanto_service,
        "get_empleado_by_id",
        lambda empleado_id: {"id": empleado_id, "empresa_id": 3},
    )
    monkeypatch.setattr(adelanto_service, "get_by_empleado_periodo", lambda *args: None)
    monkeypatch.setattr(
        adelanto_service,
        "create",
        lambda data: (_ for _ in ()).throw(DuplicatePeriodError()),
    )

    with pytest.raises(
        adelanto_service.AdelantoAlreadyRequestedError,
        match="Ya solicitaste un adelanto en este mes",
    ):
        adelanto_service.solicitar_adelanto(
            empleado_id=10,
            empresa_id=3,
            fecha_solicitud="2026-04-17",
        )


def test_aprobar_adelanto_desde_pendiente(monkeypatch):
    called = {}
    monkeypatch.setattr(
        adelanto_service,
        "get_by_id",
        lambda adelanto_id: {"id": adelanto_id, "estado": "pendiente"},
    )
    monkeypatch.setattr(
        adelanto_service,
        "update_estado",
        lambda adelanto_id, estado, **kw: called.update(
            {"id": adelanto_id, "estado": estado, "actor_id": kw.get("resuelto_by_usuario_id")}
        ),
    )

    adelanto_service.aprobar_adelanto(81, actor_id=99)

    assert called == {"id": 81, "estado": "aprobado", "actor_id": 99}


def test_aprobar_adelanto_rechaza_estado_no_pendiente(monkeypatch):
    monkeypatch.setattr(
        adelanto_service,
        "get_by_id",
        lambda adelanto_id: {"id": adelanto_id, "estado": "rechazado"},
    )

    with pytest.raises(ValueError, match="aprobar"):
        adelanto_service.aprobar_adelanto(81)


def test_rechazar_adelanto_desde_pendiente(monkeypatch):
    called = {}
    monkeypatch.setattr(
        adelanto_service,
        "get_by_id",
        lambda adelanto_id: {"id": adelanto_id, "estado": "pendiente"},
    )
    monkeypatch.setattr(
        adelanto_service,
        "update_estado",
        lambda adelanto_id, estado, **kw: called.update(
            {"id": adelanto_id, "estado": estado, "actor_id": kw.get("resuelto_by_usuario_id")}
        ),
    )

    adelanto_service.rechazar_adelanto(81, actor_id=88)

    assert called == {"id": 81, "estado": "rechazado", "actor_id": 88}


def test_rechazar_adelanto_rechaza_estado_no_pendiente(monkeypatch):
    monkeypatch.setattr(
        adelanto_service,
        "get_by_id",
        lambda adelanto_id: {"id": adelanto_id, "estado": "aprobado"},
    )

    with pytest.raises(ValueError, match="rechazar"):
        adelanto_service.rechazar_adelanto(81)
