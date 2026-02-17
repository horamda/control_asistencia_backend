import app as app_module
import web.auth.decorators as auth_decorators
import web.asistencias.asistencias_routes as asistencias_routes
import web.empleado_excepciones.empleado_excepciones_routes as excepciones_routes
import web.empleado_horarios.empleado_horarios_routes as empleado_horarios_routes
import web.horarios.horarios_routes as horarios_routes


def _build_client(monkeypatch):
    monkeypatch.setattr(app_module, "init_db", lambda: None)
    monkeypatch.setattr(auth_decorators, "has_role", lambda user_id, role: True)

    app = app_module.create_app()
    app.config["TESTING"] = True
    app.config["WTF_CSRF_ENABLED"] = False

    client = app.test_client()
    with client.session_transaction() as sess:
        sess["user_id"] = 1
        sess["user_role"] = "admin"
    return client


def test_integracion_horarios_api_create_ok(monkeypatch):
    client = _build_client(monkeypatch)
    monkeypatch.setattr(horarios_routes, "create_horario_estructurado", lambda payload: 101)
    monkeypatch.setattr(horarios_routes, "log_audit", lambda *args, **kwargs: None)

    payload = {
        "empresa_id": 1,
        "nombre": "Horario Verano",
        "tolerancia_min": 5,
        "dias": [
            {
                "dia_semana": 1,
                "bloques": [
                    {"entrada": "08:00", "salida": "12:00"},
                    {"entrada": "16:00", "salida": "20:00"},
                ],
            }
        ],
    }

    response = client.post("/horarios/api", json=payload)
    assert response.status_code == 201
    assert response.get_json() == {"id": 101}


def test_integracion_horarios_api_create_error_de_validacion(monkeypatch):
    client = _build_client(monkeypatch)

    def _raise_validation(_payload):
        raise ValueError("empresa_id es requerido.")

    monkeypatch.setattr(horarios_routes, "create_horario_estructurado", _raise_validation)

    response = client.post("/horarios/api", json={"nombre": "sin empresa"})
    assert response.status_code == 400
    assert response.get_json()["error"] == "empresa_id es requerido."


def test_integracion_asignaciones_api_asignar_ok(monkeypatch):
    client = _build_client(monkeypatch)
    monkeypatch.setattr(empleado_horarios_routes, "get_by_id", lambda empleado_id: {"id": empleado_id, "empresa_id": 1})
    monkeypatch.setattr(empleado_horarios_routes, "get_horario_by_id", lambda horario_id: {"id": horario_id, "empresa_id": 1})
    monkeypatch.setattr(empleado_horarios_routes, "create_asignacion", lambda *args, **kwargs: 202)
    monkeypatch.setattr(empleado_horarios_routes, "log_audit", lambda *args, **kwargs: None)

    payload = {
        "empleado_id": 1,
        "horario_id": 2,
        "fecha_desde": "2026-02-01",
        "fecha_hasta": "2026-02-28",
    }
    response = client.post("/empleado-horarios/api", json=payload)
    assert response.status_code == 201
    assert response.get_json() == {"id": 202}


def test_integracion_asignaciones_api_rechaza_empresa_inconsistente(monkeypatch):
    client = _build_client(monkeypatch)
    monkeypatch.setattr(empleado_horarios_routes, "get_by_id", lambda empleado_id: {"id": empleado_id, "empresa_id": 1})
    monkeypatch.setattr(empleado_horarios_routes, "get_horario_by_id", lambda horario_id: {"id": horario_id, "empresa_id": 2})

    payload = {
        "empleado_id": 1,
        "horario_id": 2,
        "fecha_desde": "2026-02-01",
    }
    response = client.post("/empleado-horarios/api", json=payload)
    assert response.status_code == 400
    assert response.get_json()["error"] == "Empresa inconsistente entre empleado y horario"


def test_integracion_excepciones_api_create_ok(monkeypatch):
    client = _build_client(monkeypatch)
    monkeypatch.setattr(excepciones_routes, "get_empleado_by_id", lambda empleado_id: {"id": empleado_id, "empresa_id": 1})
    monkeypatch.setattr(excepciones_routes, "create_excepcion", lambda data, bloques: 303)
    monkeypatch.setattr(excepciones_routes, "log_audit", lambda *args, **kwargs: None)

    payload = {
        "empleado_id": 1,
        "fecha": "2026-02-13",
        "tipo": "CAMBIO_HORARIO",
        "descripcion": "Cambio puntual",
        "anula_horario": False,
        "bloques": [{"entrada": "10:00", "salida": "18:00"}],
    }
    response = client.post("/empleado-excepciones/api", json=payload)
    assert response.status_code == 201
    assert response.get_json() == {"id": 303}


def test_integracion_asistencias_horario_esperado_ok(monkeypatch):
    client = _build_client(monkeypatch)
    monkeypatch.setattr(
        asistencias_routes,
        "get_horario_esperado",
        lambda empleado_id, fecha: {
            "tiene_excepcion": False,
            "bloques": [{"entrada": "08:00", "salida": "16:00"}],
            "tolerancia": 5,
        },
    )

    response = client.get("/asistencias/horario-esperado?empleado_id=1&fecha=2026-02-13")
    assert response.status_code == 200
    assert response.get_json()["tolerancia"] == 5
    assert response.get_json()["bloques"] == [{"entrada": "08:00", "salida": "16:00"}]


def test_integracion_asistencias_horario_esperado_sin_horario(monkeypatch):
    client = _build_client(monkeypatch)
    monkeypatch.setattr(asistencias_routes, "get_horario_esperado", lambda empleado_id, fecha: None)

    response = client.get("/asistencias/horario-esperado?empleado_id=1&fecha=2026-02-13")
    assert response.status_code == 404
    assert response.get_json()["error"] == "sin horario esperado"
