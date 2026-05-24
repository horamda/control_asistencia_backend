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
    monkeypatch.setattr(vacaciones_service, "_today", lambda: datetime.date(2027, 1, 1))
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
    # Empleado ingresado 01-sep-2026, trabajó solo 15 días de ~88 hábiles disponibles en su período.
    # El control proporcional compara contra la mitad de SU período (desde_trabajado),
    # no contra la mitad del año completo. 15 < 44 → proporcional → 15 // 20 = 0 días.
    monkeypatch.setattr(vacaciones_service, "_today", lambda: datetime.date(2027, 1, 1))
    monkeypatch.setattr(
        vacaciones_service,
        "get_empleado_for_vacaciones",
        lambda empleado_id: _empleado("2026-09-01"),
    )
    monkeypatch.setattr(
        vacaciones_service,
        "count_dias_efectivamente_trabajados",
        lambda **kwargs: 15,
    )
    monkeypatch.setattr(vacaciones_service, "get_movimientos_by_empleado_anio", lambda **kwargs: [])

    resumen = vacaciones_service.calcular_resumen_vacaciones(10, 2026)

    assert resumen["vacaciones"]["aplica_control_proporcional"] is True
    assert resumen["vacaciones"]["calculo_proporcional"] is True
    assert resumen["vacaciones"]["dias_base"] == 0   # 15 // 20 = 0
    assert resumen["vacaciones"]["dias_corresponden"] == 0


def test_calcular_resumen_vacaciones_nuevo_ingreso_no_proporcional_si_trabajo_suficiente(monkeypatch):
    # Mismo empleado (sep 2026) pero trabajó 80 de ~88 días hábiles de su período.
    # 80 >= 44 (mitad de 88) → no proporcional → recibe los 14 días base completos.
    monkeypatch.setattr(vacaciones_service, "_today", lambda: datetime.date(2027, 1, 1))
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

    assert resumen["vacaciones"]["aplica_control_proporcional"] is True
    assert resumen["vacaciones"]["calculo_proporcional"] is False
    assert resumen["vacaciones"]["dias_base"] == 14
    assert resumen["vacaciones"]["dias_corresponden"] == 14


def test_calcular_resumen_vacaciones_empleado_antiguo_ignora_asistencias_incompletas(monkeypatch):
    monkeypatch.setattr(vacaciones_service, "_today", lambda: datetime.date(2027, 1, 1))
    monkeypatch.setattr(
        vacaciones_service,
        "get_empleado_for_vacaciones",
        lambda empleado_id: _empleado("2001-01-01"),
    )
    monkeypatch.setattr(
        vacaciones_service,
        "count_dias_efectivamente_trabajados",
        lambda **kwargs: 0,
    )
    monkeypatch.setattr(vacaciones_service, "get_movimientos_by_empleado_anio", lambda **kwargs: [])

    resumen = vacaciones_service.calcular_resumen_vacaciones(10, 2026)

    vacaciones = resumen["vacaciones"]
    assert vacaciones["antiguedad_al_31_12"] == 25
    assert vacaciones["aplica_control_proporcional"] is False
    assert vacaciones["calculo_proporcional"] is False
    assert vacaciones["dias_base"] == 35
    assert vacaciones["dias_corresponden"] == 35


def test_calcular_resumen_vacaciones_anio_en_curso_no_penaliza_dias_futuros(monkeypatch):
    monkeypatch.setattr(vacaciones_service, "_today", lambda: datetime.date(2026, 5, 15))
    monkeypatch.setattr(
        vacaciones_service,
        "get_empleado_for_vacaciones",
        lambda empleado_id: _empleado("2001-01-01"),
    )
    monkeypatch.setattr(
        vacaciones_service,
        "count_dias_efectivamente_trabajados",
        lambda **kwargs: 60,
    )
    monkeypatch.setattr(vacaciones_service, "get_movimientos_by_empleado_anio", lambda **kwargs: [])

    resumen = vacaciones_service.calcular_resumen_vacaciones(10, 2026)

    vacaciones = resumen["vacaciones"]
    assert vacaciones["antiguedad_al_31_12"] == 25
    assert vacaciones["calculo_proporcional"] is False
    assert vacaciones["dias_base"] == 35
    assert vacaciones["dias_habiles_anio"] == vacaciones["dias_habiles_evaluados"]
    assert vacaciones["dias_habiles_anio_total"] > vacaciones["dias_habiles_evaluados"]
    assert vacaciones["fecha_evaluacion_trabajo"] == "2026-05-15"


def test_solicitar_vacaciones_registra_pendiente(monkeypatch):
    monkeypatch.setattr(vacaciones_service, "_today", lambda: datetime.date(2027, 1, 1))
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
    monkeypatch.setattr(vacaciones_service, "exists_movimiento_tomado_overlap", lambda **kwargs: False)
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


def test_aprobar_movimiento_vacaciones_crea_periodo_legacy(monkeypatch):
    rows = {
        "before": {
            "id": 55,
            "empleado_id": 10,
            "empresa_id": 3,
            "anio": 2026,
            "tipo": "tomado",
            "dias": Decimal("5.00"),
            "estado": "pendiente",
            "fecha_desde": "2026-01-10",
            "fecha_hasta": "2026-01-14",
            "observacion": "Solicitud mobile",
        },
        "after": {
            "id": 55,
            "empleado_id": 10,
            "empresa_id": 3,
            "anio": 2026,
            "tipo": "tomado",
            "dias": Decimal("5.00"),
            "estado": "aprobado",
            "fecha_desde": "2026-01-10",
            "fecha_hasta": "2026-01-14",
            "observacion": "Solicitud mobile",
        },
    }
    calls = {"updated": None, "legacy": None}

    monkeypatch.setattr(
        vacaciones_service,
        "get_movimiento_by_id",
        lambda movimiento_id: rows["after"] if calls["updated"] else rows["before"],
    )
    monkeypatch.setattr(
        vacaciones_service,
        "calcular_resumen_vacaciones",
        lambda empleado_id, anio: {"vacaciones": {"dias_disponibles": 10}},
    )
    monkeypatch.setattr(vacaciones_service, "exists_movimiento_tomado_overlap", lambda **kwargs: False)
    monkeypatch.setattr(
        vacaciones_service,
        "update_movimiento_estado",
        lambda movimiento_id, estado, **kwargs: calls.update({"updated": (movimiento_id, estado)}) or True,
    )
    monkeypatch.setattr(vacaciones_service, "exists_legacy_vacacion_rango", lambda *args: False)
    monkeypatch.setattr(
        vacaciones_service,
        "create_legacy_vacacion",
        lambda data: calls.update({"legacy": data}) or 99,
    )

    vacaciones_service.aprobar_movimiento_vacaciones(55)

    assert calls["updated"] == (55, "aprobado")
    assert calls["legacy"]["empleado_id"] == 10
    assert calls["legacy"]["fecha_desde"] == "2026-01-10"
    assert calls["legacy"]["fecha_hasta"] == "2026-01-14"


def test_cancelar_movimiento_vacaciones_crea_ajuste_reversion(monkeypatch):
    row = {
        "id": 55,
        "empleado_id": 10,
        "empresa_id": 3,
        "anio": 2026,
        "tipo": "tomado",
        "dias": Decimal("5.00"),
        "estado": "aprobado",
        "fecha_desde": "2026-01-10",
        "fecha_hasta": "2026-01-14",
        "observacion": "Vacaciones aprobadas",
    }
    calls = {"created": None, "marked": None}
    monkeypatch.setattr(vacaciones_service, "get_movimiento_by_id", lambda movimiento_id: row)
    monkeypatch.setattr(
        vacaciones_service,
        "create_movimiento",
        lambda data: calls.update({"created": data}) or 88,
    )
    monkeypatch.setattr(
        vacaciones_service,
        "mark_movimiento_revertido",
        lambda movimiento_id, **kw: calls.update({"marked": {"movimiento_id": movimiento_id, **kw}}),
    )

    ajuste_id = vacaciones_service.cancelar_movimiento_vacaciones(55, actor_id=99, motivo="Error de carga")

    assert ajuste_id == 88
    assert calls["created"]["tipo"] == "ajuste"
    assert calls["created"]["dias"] == Decimal("5.00")
    assert calls["created"]["origen_movimiento_id"] == 55
    assert calls["marked"]["movimiento_id"] == 55
    assert calls["marked"]["ajuste_id"] == 88
    assert calls["marked"]["motivo"] == "Error de carga"


def test_rechazar_movimiento_vacaciones_requiere_motivo():
    try:
        vacaciones_service.rechazar_movimiento_vacaciones(55, motivo="")
    except vacaciones_service.VacacionesError as exc:
        assert "Motivo" in str(exc)
    else:
        raise AssertionError("Expected VacacionesError")


def test_count_workdays_excluye_fin_de_semana():
    assert vacaciones_service._count_workdays(
        datetime.date(2026, 1, 1),
        datetime.date(2026, 1, 7),
    ) == 5
