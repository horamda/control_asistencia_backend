import datetime
import io

import services.skap_seed_service as seed_service


def test_seed_base_questions_creates_for_selected_sector(monkeypatch):
    created = []

    monkeypatch.setattr(
        seed_service,
        "get_sectores",
        lambda include_inactive=False: [
            {"id": 7, "nombre": "Operaciones", "empresa_id": 3},
            {"id": 8, "nombre": "Administracion", "empresa_id": 3},
        ],
    )
    monkeypatch.setattr(seed_service, "get_by_unique", lambda *args, **kwargs: None)
    monkeypatch.setattr(seed_service, "create_pregunta", lambda payload: created.append(payload) or len(created))

    result = seed_service.seed_base_questions(sector_ids=[7])

    assert result["sectores"] == 1
    assert result["creadas"] == len(seed_service.BASE_QUESTIONS)
    assert result["omitidas"] == 0
    assert all(row["sector_id"] == 7 for row in created)


def test_seed_base_questions_skips_existing(monkeypatch):
    monkeypatch.setattr(
        seed_service,
        "get_sectores",
        lambda include_inactive=False: [{"id": 7, "nombre": "Operaciones", "empresa_id": 3}],
    )
    monkeypatch.setattr(seed_service, "get_by_unique", lambda *args, **kwargs: {"id": 99, "activo": 1})
    monkeypatch.setattr(seed_service, "create_pregunta", lambda payload: (_ for _ in ()).throw(AssertionError("should not create")))

    result = seed_service.seed_base_questions(sector_ids=[7])

    assert result["creadas"] == 0
    assert result["omitidas"] == len(seed_service.BASE_QUESTIONS)


def test_seed_base_questions_reactivates_existing_when_requested(monkeypatch):
    updated = []

    monkeypatch.setattr(
        seed_service,
        "get_sectores",
        lambda include_inactive=False: [{"id": 7, "nombre": "Operaciones", "empresa_id": 3}],
    )
    monkeypatch.setattr(seed_service, "get_by_unique", lambda *args, **kwargs: {"id": 99, "activo": 0})
    monkeypatch.setattr(seed_service, "update_pregunta", lambda pregunta_id, payload: updated.append((pregunta_id, payload)))

    result = seed_service.seed_base_questions(sector_ids=[7], reactivate=True)

    assert result["reactivadas"] == len(seed_service.BASE_QUESTIONS)
    assert all(item[0] == 99 for item in updated)
    assert all(item[1]["activo"] is True for item in updated)


def test_importar_preguntas_desde_csv_resuelve_sector_y_crea(monkeypatch):
    created = []
    csv_content = (
        "sector_id;categoria;descripcion;peso;puntaje_esperado;requiere_observacion;requiere_evidencia;activo\n"
        "7;S;Pregunta desde CSV;1,5;4;SI;NO;SI\n"
    )

    monkeypatch.setattr(
        seed_service,
        "get_sectores",
        lambda include_inactive=True: [{"id": 7, "nombre": "Operaciones", "empresa_id": 3}],
    )
    monkeypatch.setattr(seed_service, "get_puestos", lambda include_inactive=True: [])
    monkeypatch.setattr(seed_service, "get_by_unique", lambda *args, **kwargs: None)
    monkeypatch.setattr(seed_service, "create_pregunta", lambda payload: created.append(payload) or 123)

    result = seed_service.importar_preguntas_desde_csv(io.BytesIO(csv_content.encode("utf-8")))

    assert result["total_filas"] == 1
    assert result["creadas"] == 1
    assert result["errores"] == 0
    assert created[0]["sector_id"] == 7
    assert created[0]["peso"] == 1.5
    assert created[0]["requiere_observacion"] is True
    assert created[0]["requiere_evidencia"] is False


def test_build_example_evaluacion_payload_uses_active_questions(monkeypatch):
    monkeypatch.setattr(
        seed_service,
        "_find_example_employee",
        lambda **kwargs: {
            "id": 10,
            "legajo": "L10",
            "apellido": "Lopez",
            "nombre": "Ana",
            "sector_id": 7,
            "reporta_a_empleado_id": 20,
            "jefe_legajo": "L20",
            "jefe_apellido": "Perez",
            "jefe_nombre": "Jose",
        },
    )
    monkeypatch.setattr(
        seed_service,
        "get_all_active_for_sector",
        lambda sector_id, puesto_id=None: [
            {
                "id": 1,
                "categoria": "S",
                "descripcion": "Procedimientos",
                "requiere_evidencia": 0,
            },
            {
                "id": 2,
                "categoria": "P",
                "descripcion": "Resultados",
                "requiere_evidencia": 1,
            },
        ],
    )

    payload = seed_service.build_example_evaluacion_payload(
        sector_id=7,
        anio=2026,
    )

    assert payload["endpoint"] == "/api/skap/evaluacion"
    assert payload["empleado"]["id"] == 10
    assert "empleado_id=20" in payload["authorization_hint"]
    assert payload["payload"]["anio"] == 2026
    assert payload["payload"]["respuestas"][0]["puntaje"] == 4
    assert payload["payload"]["respuestas"][1]["evidencia"] == "Evidencia operativa de ejemplo"


def test_build_example_evaluacion_payload_defaults_year(monkeypatch):
    monkeypatch.setattr(
        seed_service,
        "_find_example_employee",
        lambda **kwargs: {
            "id": 10,
            "sector_id": 7,
            "reporta_a_empleado_id": 20,
            "legajo": None,
            "apellido": "Lopez",
            "nombre": "Ana",
            "jefe_apellido": "Perez",
            "jefe_nombre": "Jose",
        },
    )
    monkeypatch.setattr(
        seed_service,
        "get_all_active_for_sector",
        lambda sector_id, puesto_id=None: [{"id": 1, "categoria": "A", "descripcion": "Actitud", "requiere_evidencia": 0}],
    )
    monkeypatch.setattr(seed_service._dt, "date", datetime.date)

    payload = seed_service.build_example_evaluacion_payload(sector_id=7)

    assert payload["payload"]["anio"] == datetime.date.today().year
