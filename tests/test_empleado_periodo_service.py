import datetime as dt

import pytest

from services import empleado_periodo_service as svc

D = dt.date


def _p(id_, desde, hasta):
    return {"id": id_, "fecha_desde": desde, "fecha_hasta": hasta}


def _rangos(periodos):
    return [(p["desde"], p["hasta"]) for p in periodos]


def test_baja_cierra_el_periodo_abierto():
    resultado = svc.plan_baja([_p(1, D(2024, 1, 1), None)], "2026-10-10")
    assert _rangos(resultado) == [(D(2024, 1, 1), D(2026, 10, 10))]


def test_baja_anterior_al_inicio_del_periodo_falla():
    with pytest.raises(svc.PeriodoLaboralError, match="anterior al inicio"):
        svc.plan_baja([_p(1, D(2026, 6, 1), None)], D(2026, 5, 1))


def test_baja_sin_periodos_crea_uno_desde_el_ingreso():
    # Inactivos viejos sin fecha de baja: al cargarla aparece su historia.
    resultado = svc.plan_baja([], D(2025, 12, 31), D(2023, 3, 1))
    assert _rangos(resultado) == [(D(2023, 3, 1), D(2025, 12, 31))]


def test_reingreso_agrega_periodo_y_conserva_el_anterior():
    resultado = svc.plan_reingreso([_p(1, D(2024, 1, 1), D(2026, 3, 31))], D(2026, 6, 1))
    assert _rangos(resultado) == [(D(2024, 1, 1), D(2026, 3, 31)), (D(2026, 6, 1), None)]


def test_reingreso_no_puede_pisar_la_baja():
    with pytest.raises(svc.PeriodoLaboralError, match="posterior a la ultima baja"):
        svc.plan_reingreso([_p(1, D(2024, 1, 1), D(2026, 3, 31))], D(2026, 3, 31))


def test_reingreso_con_periodo_ya_abierto_no_duplica():
    resultado = svc.plan_reingreso([_p(1, D(2024, 1, 1), None)], D(2026, 6, 1))
    assert _rangos(resultado) == [(D(2024, 1, 1), None)]


def test_edicion_activo_a_inactivo_exige_fecha_de_baja():
    antes = {"activo": 1, "fecha_ingreso": D(2024, 1, 1), "fecha_baja": None}
    with pytest.raises(svc.PeriodoLaboralError, match="fecha de baja"):
        svc.plan_edicion([_p(1, D(2024, 1, 1), None)], antes, {"estado": "suspendido", "fecha_ingreso": "2024-01-01"})


def test_edicion_reactivar_abre_periodo_y_limpia_la_baja_vieja():
    antes = {"activo": 0, "fecha_ingreso": D(2024, 1, 1), "fecha_baja": D(2026, 3, 31)}
    despues = {"estado": "activo", "fecha_ingreso": "2024-01-01", "fecha_baja": "2026-03-31"}
    resultado, baja = svc.plan_edicion(
        [_p(1, D(2024, 1, 1), D(2026, 3, 31))], antes, despues, fecha_reingreso="2026-06-01",
    )
    assert _rangos(resultado) == [(D(2024, 1, 1), D(2026, 3, 31)), (D(2026, 6, 1), None)]
    assert baja is None


def test_edicion_reactivar_sin_fecha_usa_hoy():
    antes = {"activo": 0, "fecha_ingreso": D(2024, 1, 1), "fecha_baja": D(2026, 3, 31)}
    resultado, _ = svc.plan_edicion(
        [_p(1, D(2024, 1, 1), D(2026, 3, 31))], antes, {"estado": "eventual"}, hoy=D(2026, 10, 16),
    )
    assert resultado[-1]["desde"] == D(2026, 10, 16)


def test_edicion_cambia_ingreso_del_primer_periodo():
    antes = {"activo": 1, "fecha_ingreso": D(2024, 1, 1), "fecha_baja": None}
    resultado, _ = svc.plan_edicion(
        [_p(1, D(2024, 1, 1), D(2025, 1, 31)), _p(2, D(2026, 1, 1), None)],
        antes,
        {"estado": "activo", "fecha_ingreso": "2023-11-15"},
    )
    assert _rangos(resultado) == [(D(2023, 11, 15), D(2025, 1, 31)), (D(2026, 1, 1), None)]


def test_edicion_inactivo_carga_baja_por_primera_vez():
    antes = {"activo": 0, "fecha_ingreso": D(2022, 5, 1), "fecha_baja": None}
    resultado, baja = svc.plan_edicion([], antes, {"estado": "inactivo", "fecha_ingreso": "2022-05-01", "fecha_baja": "2025-08-15"})
    assert _rangos(resultado) == [(D(2022, 5, 1), D(2025, 8, 15))]
    assert baja == D(2025, 8, 15)


def test_aplicar_solo_escribe_cambios():
    executed = []

    class Cursor:
        def execute(self, sql, params):
            executed.append((sql.split()[0], params))

    originales = [_p(1, D(2024, 1, 1), D(2026, 3, 31))]
    svc.aplicar(Cursor(), 9, originales, svc.plan_reingreso(originales, D(2026, 6, 1)))
    assert executed == [("INSERT", (9, D(2026, 6, 1), None))]


def test_en_periodo_respeta_extremos_y_huecos():
    periodos = [(D(2025, 1, 1), D(2026, 3, 31)), (D(2026, 6, 1), None)]
    assert svc.en_periodo(periodos, D(2026, 3, 31))
    assert not svc.en_periodo(periodos, D(2026, 4, 15))
    assert svc.en_periodo(periodos, D(2030, 1, 1))
    assert not svc.en_periodo([], D(2026, 1, 1))
