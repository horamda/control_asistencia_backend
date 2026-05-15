import datetime
from decimal import Decimal

import services.vacaciones_service as vacaciones_service


def _empleado(fecha_ingreso="2020-08-10"):
    return {
        "id": 10,
        "activo": 1,
        "empresa_id": 3,
        "dni": "12345678",
        "nombre": "Juan",
        "apellido": "Perez",
        "fecha_ingreso": fecha_ingreso,
    }


def test_calcular_resumen_vacaciones_lct_regular(monkeypatch):
    monkeypatch.setattr(
        vacaciones_service,
        "get_empleado_for_vacaciones",
        lambda empleado_id: _empleado(),
    )
    monkeypatch.setattr(
        vacaciones_service,
        "count_dias_efectivamente_trabajados",
        lambda **kwargs: 220,
    )
    monkeypatch.setattr(
        vacaciones_service,
        "get_movimientos_by_empleado_anio",
        lambda **kwargs: [
            {"tipo": "compensatorio", "estado": "aprobado", "dias": Decimal("2.00")},
            {"tipo": "tomado", "estado": "aprobado", "dias": Decimal("5.00")},
            {"tipo": "tomado", "estado": "pendiente", "dias": Decimal("3.00")},
        ],
    )

    resumen = vacaciones_service.calcular_resumen_vacaciones(10, 2026)

    assert resumen["empleado"]["nombre"] == "Juan Perez"
    assert resumen["vacaciones"]["antiguedad_al_31_12"] == 6
    assert resumen["vacaciones"]["dias_base"] == 21
    assert resumen["vacaciones"]["dias_compensatorios"] == 2
    assert resumen["vacaciones"]["dias_tomados"] == 5
    assert resumen["vacaciones"]["dias_pendientes"] == 3
    assert resumen["vacaciones"]["dias_corresponden"] == 23
    assert resumen["vacaciones"]["dias_disponibles"] == 18
    assert resumen["vacaciones"]["dias_disponibles_con_pendientes"] == 15


def test_calcular_resumen_vacaciones_proporcional(monkeypatch):
    monkeypatch.setattr(
        vacaciones_service,
        "get_empleado_for_vacaciones",
        lambda empleado_id: _empleado("2026-09-01"),
    )
    monkeypatch.setattr(
        vacaciones_service,
        "count_dias_efectivamente_trabajados",
        lambda **kwargs: 80,
    )
    monkeypatch.setattr(vacaciones_service, "get_movimientos_by_empleado_anio", lambda **kwargs: [])

    resumen = vacaciones_service.calcular_resumen_vacaciones(10, 2026)

    assert resumen["vacaciones"]["calculo_proporcional"] is True
    assert resumen["vacaciones"]["dias_base"] == 4
    assert resumen["vacaciones"]["dias_corresponden"] == 4


def test_solicitar_vacaciones_registra_pendiente(monkeypatch):
    monkeypatch.setattr(
        vacaciones_service,
        "get_empleado_for_vacaciones",
        lambda empleado_id: _empleado(),
    )
    monkeypatch.setattr(
        vacaciones_service,
        "count_dias_efectivamente_trabajados",
        lambda **kwargs: 220,
    )
    monkeypatch.setattr(vacaciones_service, "get_movimientos_by_empleado_anio", lambda **kwargs: [])
    created = {}
    monkeypatch.setattr(
        vacaciones_service,
        "create_movimiento",
        lambda data: created.update(data) or 55,
    )

    result = vacaciones_service.solicitar_vacaciones(
        empleado_id=10,
        fecha_desde="2026-01-10",
        fecha_hasta="2026-01-14",
        observacion="Solicitud vacaciones",
    )

    assert result["id"] == 55
    assert result["dias_solicitados"] == 5
    assert created["tipo"] == "tomado"
    assert created["estado"] == "pendiente"
    assert created["dias"] == 5


def test_solicitar_vacaciones_rechaza_rango_invertido():
    try:
        vacaciones_service.solicitar_vacaciones(
            empleado_id=10,
            fecha_desde="2026-02-10",
            fecha_hasta="2026-02-01",
        )
    except vacaciones_service.VacacionesError as exc:
        assert "posterior" in str(exc)
    else:
        raise AssertionError("Expected VacacionesError")


def test_count_workdays_excluye_fin_de_semana():
    assert vacaciones_service._count_workdays(
        datetime.date(2026, 1, 1),
        datetime.date(2026, 1, 7),
    ) == 5
