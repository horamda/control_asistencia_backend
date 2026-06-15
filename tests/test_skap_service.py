import datetime

import services.skap_service as skap_service


def test_can_evaluate_employee_accepts_direct_boss(monkeypatch):
    empleados = {
        10: {
            "id": 10,
            "activo": 1,
            "reporta_a_empleado_id": 20,
            "empresa_id": 3,
            "sector_id": 7,
        },
        20: {
            "id": 20,
            "activo": 1,
            "reporta_a_empleado_id": None,
            "empresa_id": 3,
            "sector_id": 7,
        },
    }

    monkeypatch.setattr(skap_service, "get_empleado_by_id", lambda empleado_id: empleados[int(empleado_id)])
    monkeypatch.setattr(skap_service, "get_roles_by_empleado", lambda empleado_id: [])

    assert skap_service.can_evaluate_employee(20, 10) is True
    assert skap_service.can_evaluate_employee(10, 20) is False


def test_get_mi_desarrollo_uses_selected_year_and_ranking(monkeypatch):
    empleado = {
        "id": 10,
        "activo": 1,
        "empresa_id": 3,
        "sector_id": 7,
        "puesto_id": 4,
        "legajo": "L10",
        "dni": "30111222",
        "apellido": "Lopez",
        "nombre": "Ana",
        "reporta_a_empleado_id": 20,
        "sector_nombre": "Operaciones",
    }
    evaluacion = {
        "id": 100,
        "empresa_id": 3,
        "empleado_id": 10,
        "sector_id": 7,
        "puesto_id": 4,
        "anio": 2025,
        "evaluador_empleado_id": 20,
        "evaluador_usuario_id": None,
        "fecha_evaluacion": datetime.date(2025, 1, 10),
        "hora_evaluacion": datetime.time(9, 30),
        "promedio_skills": 4.5,
        "promedio_knowledge": 4.0,
        "promedio_attitude": 4.2,
        "promedio_performance": 4.1,
        "promedio_general": 4.2,
        "nivel": "Destacado",
        "observaciones_generales": "Buen ciclo",
        "pdp_generado_at": None,
        "created_at": datetime.datetime(2025, 1, 10, 12, 0, 0),
        "updated_at": datetime.datetime(2025, 1, 10, 12, 0, 0),
        "empleado_legajo": "L10",
        "empleado_dni": "30111222",
        "empleado_apellido": "Lopez",
        "empleado_nombre": "Ana",
        "sector_nombre": "Operaciones",
        "puesto_nombre": "Analista",
        "evaluador_legajo": "L20",
        "evaluador_apellido": "Perez",
        "evaluador_nombre": "Jose",
        "evaluador_usuario": None,
    }
    plan = {
        "id": 500,
        "evaluacion_id": 100,
        "empresa_id": 3,
        "empleado_id": 10,
        "sector_id": 7,
        "puesto_id": 4,
        "anio": 2025,
        "promedio_general": 4.2,
        "nivel": "Destacado",
        "observaciones": "Seguimiento",
        "created_at": datetime.datetime(2025, 1, 10, 12, 0, 0),
        "updated_at": datetime.datetime(2025, 1, 10, 12, 0, 0),
        "empleado_legajo": "L10",
        "empleado_dni": "30111222",
        "empleado_apellido": "Lopez",
        "empleado_nombre": "Ana",
        "sector_nombre": "Operaciones",
        "puesto_nombre": "Analista",
        "evaluador_apellido": "Perez",
        "evaluador_nombre": "Jose",
        "acciones_total": 1,
        "acciones_completadas": 0,
        "acciones_vencidas": 0,
    }
    detalles = [
        {
            "id": 1,
            "evaluacion_id": 100,
            "pregunta_id": 11,
            "categoria": "S",
            "descripcion_snapshot": "Cumple procedimientos",
            "peso_snapshot": 1,
            "puntaje_esperado_snapshot": 4,
            "puntaje_obtenido": 5,
            "observacion": "Bien",
            "evidencia": "Foto",
            "cumple_esperado": True,
            "created_at": datetime.datetime(2025, 1, 10, 12, 0, 0),
            "updated_at": datetime.datetime(2025, 1, 10, 12, 0, 0),
        }
    ]
    acciones = [
        {
            "id": 1,
            "plan_id": 500,
            "categoria": "S",
            "accion": "Capacitar",
            "responsable_empleado_id": 20,
            "responsable_nombre": "Perez Jose",
            "responsable_legajo": "L20",
            "fecha_compromiso": datetime.date(2025, 3, 31),
            "estado": "pendiente",
            "estado_actual": "pendiente",
            "completado_at": None,
            "comentarios": "Seguimiento",
            "created_at": datetime.datetime(2025, 1, 10, 12, 0, 0),
            "updated_at": datetime.datetime(2025, 1, 10, 12, 0, 0),
        }
    ]

    monkeypatch.setattr(skap_service, "get_empleado_by_id", lambda empleado_id: empleado)
    monkeypatch.setattr(skap_service, "get_historial_empleado", lambda *args, **kwargs: [
        {"anio": 2025, "promedio_general": 4.2, "nivel": "Destacado", "sector_nombre": "Operaciones"},
        {"anio": 2024, "promedio_general": 3.9, "nivel": "Cumple", "sector_nombre": "Operaciones"},
    ])
    monkeypatch.setattr(skap_service, "get_evaluacion_by_empleado_anio", lambda empleado_id, anio: evaluacion if anio == 2025 else None)
    monkeypatch.setattr(skap_service, "get_evaluacion_detalles", lambda evaluacion_id: detalles)
    monkeypatch.setattr(skap_service, "get_plan_by_empleado_anio", lambda empleado_id, anio, empresa_id=None: plan if anio == 2025 else None)
    monkeypatch.setattr(skap_service, "get_plan_actions", lambda plan_id: acciones)
    monkeypatch.setattr(
        skap_service,
        "get_employee_ranking_rows",
        lambda **kwargs: [
            {"empleado_id": 99, "promedio_general": 4.6, "sector_nombre": "Operaciones"},
            {"empleado_id": 10, "promedio_general": 4.2, "sector_nombre": "Operaciones"},
        ],
    )

    payload = skap_service.get_mi_desarrollo(empleado_id=10, anio=2025)

    assert payload["anio_evaluado"] == 2025
    assert payload["badge"] == "Plata"
    assert payload["ranking"]["posicion"] == 2
    assert payload["ranking"]["total"] == 2
    assert payload["plan"]["acciones_total"] == 1
    assert len(payload["categoria_cards"]) == 4


def test_get_dashboard_data_serializes_results(monkeypatch):
    monkeypatch.setattr(
        skap_service,
        "get_dashboard_summary",
        lambda **kwargs: {
            "empleados_activos": 8,
            "empleados_evaluados": 5,
            "empleados_pendientes": 3,
            "promedio_general": 4.1,
            "promedio_skills": 4.2,
            "promedio_knowledge": 4.0,
            "promedio_attitude": 4.1,
            "promedio_performance": 4.2,
            "planes_total": 2,
            "acciones_completadas": 1,
            "acciones_canceladas": 0,
            "acciones_vencidas": 1,
            "acciones_pendientes": 1,
            "acciones_en_proceso": 0,
        },
    )
    monkeypatch.setattr(
        skap_service,
        "get_sector_ranking_rows",
        lambda **kwargs: [
            {
                "sector_id": 7,
                "sector_nombre": "Operaciones",
                "evaluaciones": 5,
                "promedio_general": 4.3,
                "promedio_skills": 4.4,
                "promedio_knowledge": 4.1,
                "promedio_attitude": 4.2,
                "promedio_performance": 4.5,
            }
        ],
    )
    monkeypatch.setattr(
        skap_service,
        "get_employee_ranking_rows",
        lambda **kwargs: [
            {"empleado_id": 10, "legajo": "L10", "apellido": "Lopez", "nombre": "Ana", "sector_nombre": "Operaciones", "puesto_nombre": "Analista", "promedio_general": 4.7, "nivel": "Excelente"},
            {"empleado_id": 11, "legajo": "L11", "apellido": "Perez", "nombre": "Jose", "sector_nombre": "Operaciones", "puesto_nombre": "Supervisor", "promedio_general": 2.8, "nivel": "Necesita Desarrollo"},
        ],
    )
    monkeypatch.setattr(
        skap_service,
        "get_historical_evolution_rows",
        lambda **kwargs: [
            {"anio": 2024, "evaluaciones": 4, "promedio_general": 3.9},
        ],
    )
    monkeypatch.setattr(
        skap_service,
        "get_category_averages_rows",
        lambda **kwargs: [
            {"categoria": "S", "respuestas": 6, "promedio_obtenido": 4.2, "promedio_esperado": 4.0},
        ],
    )

    def _fake_question_averages_rows(*, ascending, **kwargs):
        if ascending:
            return [
                {"pregunta_id": 1, "categoria": "S", "descripcion_snapshot": "Brecha 1", "respuestas": 3, "promedio_obtenido": 2.5, "promedio_esperado": 4.0, "peso_promedio": 1.0},
            ]
        return [
            {"pregunta_id": 2, "categoria": "K", "descripcion_snapshot": "Fortaleza 1", "respuestas": 4, "promedio_obtenido": 4.8, "promedio_esperado": 4.0, "peso_promedio": 1.0},
        ]

    monkeypatch.setattr(skap_service, "get_question_averages_rows", _fake_question_averages_rows)

    payload = skap_service.get_dashboard_data(anio=2025, sector_id=7)

    assert payload["anio"] == 2025
    assert payload["resumen"]["planes_total"] == 2
    assert payload["sector_ranking"][0]["sector_nombre"] == "Operaciones"
    assert payload["destacados"][0]["empleado_id"] == 10
    assert payload["criticos"][0]["empleado_id"] == 11
    assert payload["weakest_competencies"][0]["pregunta_id"] == 1
    assert payload["strongest_competencies"][0]["pregunta_id"] == 2
