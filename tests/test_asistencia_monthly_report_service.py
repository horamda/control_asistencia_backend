import datetime as dt

from services.asistencia_monthly_report_service import build_monthly_attendance_report


def test_monthly_report_counts_absences_justifications_and_jornada():
    empleados = [
        {"id": 1, "apellido": "Aguirre", "nombre": "Leandro", "sector_nombre": "Operaciones", "activo": 1},
        {"id": 2, "apellido": "Rocha", "nombre": "Nicolas", "sector_nombre": "Almacen", "activo": 1},
    ]
    marcas = [
        {"id": 1, "empleado_id": 1, "fecha": "2026-07-01", "hora": "08:00", "accion": "ingreso"},
        {"id": 2, "empleado_id": 1, "fecha": "2026-07-01", "hora": "17:00", "accion": "egreso"},
        {"id": 3, "empleado_id": 2, "fecha": "2026-07-01", "hora": "08:00", "accion": "ingreso"},
        {"id": 4, "empleado_id": 2, "fecha": "2026-07-01", "hora": "21:30", "accion": "egreso"},
        {"id": 5, "empleado_id": 1, "fecha": "2026-07-02", "hora": "08:00", "accion": "ingreso"},
    ]
    justificaciones = [
        {
            "empleado_id": 2,
            "fecha": "2026-07-02",
            "fecha_desde": "2026-07-02",
            "fecha_hasta": "2026-07-02",
            "estado": "aprobada",
        }
    ]

    report = build_monthly_attendance_report(
        year=2026,
        month=7,
        empleados=empleados,
        marcas=marcas,
        justificaciones=justificaciones,
        non_laborable_days={dt.date(2026, 7, day).isoformat() for day in range(3, 32)},
    )

    assert report["kpis"]["dias_laborables"] == 2
    assert report["kpis"]["ausencias_computables"] == 0
    assert report["kpis"]["ausencias_justificadas"] == 1
    assert report["kpis"]["jornadas_mayores_12"] == 1
    assert report["kpis"]["sin_egreso"] == 1


def test_monthly_report_treats_approved_vacations_as_justified_days():
    empleados = [
        {"id": 1, "apellido": "Aguirre", "nombre": "Leandro", "sector_nombre": "Operaciones", "activo": 1},
    ]

    report = build_monthly_attendance_report(
        year=2026,
        month=7,
        empleados=empleados,
        marcas=[],
        justificaciones=[],
        vacaciones=[
            {
                "id": 1,
                "empleado_id": 1,
                "tipo": "tomado",
                "estado": "aprobado",
                "fecha_desde": "2026-07-01",
                "fecha_hasta": "2026-07-02",
            }
        ],
        non_laborable_days={dt.date(2026, 7, day).isoformat() for day in range(3, 32)},
    )

    assert report["kpis"]["dias_laborables"] == 2
    assert report["kpis"]["ausencias_computables"] == 0
    assert report["kpis"]["ausencias_justificadas"] == 2
    assert report["kpis"]["ausentismo_pct"] == 0.0


def test_monthly_report_excludes_employees_without_attendance_control():
    empleados = [
        {"id": 1, "apellido": "Controla", "nombre": "Si", "sector_nombre": "Operaciones", "activo": 1, "requiere_control_asistencia": 1},
        {"id": 2, "apellido": "Controla", "nombre": "No", "sector_nombre": "Operaciones", "activo": 1, "requiere_control_asistencia": 0},
    ]

    report = build_monthly_attendance_report(
        year=2026,
        month=7,
        empleados=empleados,
        marcas=[],
        justificaciones=[],
        non_laborable_days={dt.date(2026, 7, day).isoformat() for day in range(2, 32)},
    )

    assert report["kpis"]["empleados_activos"] == 1
    assert report["kpis"]["dias_posibles"] == 1
    assert report["kpis"]["ausencias_computables"] == 1
