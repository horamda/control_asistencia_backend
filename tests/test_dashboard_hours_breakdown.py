import web.web_routes as web_routes


def test_build_hours_breakdowns_splits_template_by_empresa_y_sucursal():
    expected_by_employee_day = {
        (10, "2026-03-01"): {
            "minutos": 480,
            "horario_id": 7,
            "horario_nombre": "Diurno",
            "empresa_id": 1,
            "empresa_nombre": "Empresa A",
            "sucursal_id": 11,
            "sucursal_nombre": "Centro",
        },
        (20, "2026-03-01"): {
            "minutos": 480,
            "horario_id": 7,
            "horario_nombre": "Diurno",
            "empresa_id": 2,
            "empresa_nombre": "Empresa B",
            "sucursal_id": 22,
            "sucursal_nombre": "Norte",
        },
    }
    registered_by_employee_day = {
        (10, "2026-03-01"): 450,
        (20, "2026-03-01"): 420,
    }

    horas_por_plantilla, horas_por_sucursal = web_routes._build_hours_breakdowns(
        expected_by_employee_day,
        registered_by_employee_day,
    )

    assert len(horas_por_plantilla) == 2
    assert len(horas_por_sucursal) == 2
    by_scope = {(row["empresa_id"], row["sucursal_id"]): row for row in horas_por_plantilla}
    assert (1, 11) in by_scope
    assert (2, 22) in by_scope
    assert by_scope[(1, 11)]["horas_esperadas"] == 8.0
    assert by_scope[(1, 11)]["horas_registradas"] == 7.5
    assert by_scope[(2, 22)]["horas_esperadas"] == 8.0
    assert by_scope[(2, 22)]["horas_registradas"] == 7.0
