import sqlite3

import pytest
from flask import Flask

import repositories.presencia_repository as repository
import services.presencia_service as service
import web.presencia_routes as routes


def test_no_ingress_list_is_separate_and_reconciles():
    employees = [dict(id=i, empresa_id=1, empresa="Empresa", nombre="Persona", apellido=str(i))
                 for i in range(1, 5)]
    marks = [dict(empleado_id=1, accion="ingreso"), dict(empleado_id=2, accion="ingreso"),
             dict(empleado_id=2, accion="egreso"), dict(empleado_id=3, accion="egreso")]
    result = service.summarize_presence(employees, marks)
    branch = result["sucursales"][0]
    assert len(branch["sin_ingreso_personas"]) == branch["sin_ingreso"] == 2
    assert {p["estado"] for p in branch["sin_ingreso_personas"]} == {"sin_fichadas", "solo_salida"}
    assert len({p["clave"] for p in branch["personal"]}) == 4
    assert not ({p["clave"] for p in branch["personas"]} & {p["clave"] for p in branch["sin_ingreso_personas"]})


def test_roster_validates_ingress_evidence_not_work_modality():
    employees = [dict(id=i, empresa_id=1, empresa="Empresa", sucursal_id=1,
                      sucursal="Central", sector_id=1, sector="Ventas", modalidad=mode,
                      nombre="Persona", apellido=str(i), dni="PRIVATE")
                 for i, mode in enumerate(["remoto", "presencial", "hibrido", "presencial"], 1)]
    marks = [dict(empleado_id=1, accion="ingreso", hora="08:00:00", metodo="qr", gps_ok=1),
             dict(empleado_id=2, accion="ingreso", hora="08:00:00", metodo="qr", gps_ok=0),
             dict(empleado_id=3, accion="ingreso", hora="08:00:00", metodo="manual", gps_ok=1),
             dict(empleado_id=4, accion="ingreso", hora="08:00:00", metodo="qr", gps_ok=1),
             dict(empleado_id=4, accion="egreso", hora="09:00:00", metodo="qr", gps_ok=1)]
    result = service.summarize_presence(employees, marks)
    people = result["sucursales"][0]["personas"]
    assert len(people) == result["totales"]["presentes"] == 3
    assert [person["ingreso_validado"] for person in people] == [True, False, False]
    assert all("dni" not in person and "id" not in person for person in people)
    assert people[0]["ultimo_ingreso"] == "08:00:00"
    # A later unverified reentry must replace a previously verified ingress.
    marks += [dict(empleado_id=1, accion="egreso", hora="10:00:00"),
              dict(empleado_id=1, accion="ingreso", hora="11:00:00", metodo="manual")]
    person = service.summarize_presence(employees, marks)["sucursales"][0]["personas"][0]
    assert person["ingreso_validado"] is False
    assert person["ultimo_ingreso"] == "11:00:00"


def test_modalities_reconcile_with_sectors_and_branches():
    employees = [dict(id=i, empresa_id=1, empresa="Empresa", sucursal_id=1,
                      sucursal="Central", sector_id=1, sector="Ventas", modalidad=mode)
                 for i, mode in enumerate(["presencial", "remoto", "hibrido", None], 1)]
    marks = [dict(empleado_id=2, accion="ingreso"), dict(empleado_id=3, accion="ingreso"),
             dict(empleado_id=3, accion="egreso")]
    result = service.summarize_presence(employees, marks)
    branch = result["sucursales"][0]
    for parent in (branch, branch["sectores"][0]):
        for key in result["totales"]:
            assert sum(mode[key] for mode in parent["modalidades"]) == parent[key]
    assert branch["modalidades"][1]["codigo"] == "remoto"
    assert branch["modalidades"][1]["presentes"] == 1
    assert branch["modalidades"][-1]["codigo"] == "sin_definir"


def test_daily_counts_reentry_duplicates_and_departures():
    empleados = [{"id": i, "empresa_id": 1, "empresa": "Empresa"} for i in range(1, 5)]
    marcas = [
        {"empleado_id": 1, "accion": "ingreso"},
        {"empleado_id": 1, "accion": "ingreso"},
        {"empleado_id": 2, "accion": "ingreso"},
        {"empleado_id": 1, "accion": "egreso"},
        {"empleado_id": 2, "accion": "egreso"},
        {"empleado_id": 1, "accion": "ingreso"},
        {"empleado_id": 3, "accion": "egreso"},
        {"empleado_id": 999, "accion": "ingreso"},
    ]
    result = service.summarize_presence(empleados, marcas)
    assert result["totales"] == dict(empleados=4, presentes=1, vinieron=2, retirados=1, sin_ingreso=2)
    assert service.summarize_presence([], [])["totales"]["presentes"] == 0


def test_repository_day_scope_future_marks_and_legacy_fallback(monkeypatch):
    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    connection.executescript("""
        CREATE TABLE empresas(id INTEGER, razon_social TEXT, activa INTEGER);
        CREATE TABLE empleados(id INTEGER, empresa_id INTEGER, activo INTEGER, sucursal_id INTEGER, sector_id INTEGER, modalidad TEXT, nombre TEXT, apellido TEXT);
        CREATE TABLE sucursales(id INTEGER, nombre TEXT);
        CREATE TABLE sectores(id INTEGER, nombre TEXT);
        CREATE TABLE asistencia_marcas(id INTEGER, empleado_id INTEGER, fecha TEXT, hora TEXT, accion TEXT, metodo TEXT, gps_ok INTEGER);
        CREATE TABLE asistencias(id INTEGER, empleado_id INTEGER, fecha TEXT, hora_entrada TEXT, hora_salida TEXT, metodo_entrada TEXT, gps_ok_entrada INTEGER, metodo_salida TEXT, gps_ok_salida INTEGER);
        INSERT INTO empresas VALUES(1, 'Uno', 1), (2, 'Dos', 1);
        INSERT INTO empleados(id, empresa_id, activo) VALUES(1, 1, 1), (2, 1, 1), (3, 1, 0), (4, 2, 1);
        INSERT INTO asistencia_marcas(id, empleado_id, fecha, hora, accion) VALUES
          (1, 1, '2026-09-11', '08:00:00', 'ingreso'),
          (2, 1, '2026-09-11', '09:00:00', 'egreso'),
          (3, 1, '2026-09-11', '10:00:00', 'ingreso'),
          (4, 1, '2026-09-11', '18:00:00', 'egreso'),
          (5, 2, '2026-09-10', '23:00:00', 'egreso'),
          (6, 3, '2026-09-11', '08:00:00', 'ingreso'),
          (7, 4, '2026-09-11', '08:00:00', 'ingreso');
        INSERT INTO asistencias(id, empleado_id, fecha, hora_entrada, hora_salida) VALUES
          (1, 1, '2026-09-11', '08:00:00', '11:00:00'),
          (2, 2, '2026-09-11', '08:00:00', '09:00:00');
    """)

    class Cursor:
        def execute(self, sql, params):
            self.cursor = connection.execute(sql.replace('%s', '?'), params)

        def fetchall(self):
            return [dict(row) for row in self.cursor.fetchall()]

        def close(self):
            self.cursor.close()

    class DB:
        def cursor(self, **kwargs):
            return Cursor()

        def close(self):
            pass

    monkeypatch.setattr(repository, "get_db", DB)
    try:
        employees, marks = repository.get_daily_presence('2026-09-11', '12:00:00', 1)
        assert {row['id'] for row in employees} == {1, 2}
        assert len(marks) == 5
        assert service.summarize_presence(employees, marks)['totales'] == dict(
            empleados=2, presentes=1, vinieron=2, retirados=1, sin_ingreso=0
        )
    finally:
        connection.close()


@pytest.fixture
def client():
    app = Flask(__name__, template_folder="../templates", static_folder="../static")
    app.register_blueprint(routes.presencia_bp)
    app.config['TESTING'] = True
    return app.test_client()


def test_public_page_and_aggregates(client, monkeypatch):
    monkeypatch.setattr(routes, 'build_presence', lambda empresa_id: service.summarize_presence(
        [{"id": 123, "empresa_id": 1, "empresa": "Empresa"}], []
    ))
    assert client.get('/presencia').status_code == 200
    response = client.get('/presencia/datos')
    assert response.status_code == 200
    assert response.headers['Cache-Control'] == 'no-store'
    assert b'123' not in response.data
    assert response.json['totales']['empleados'] == 1


@pytest.mark.parametrize('value', ['-1', '0', 'texto', '1 OR 1=1'])
def test_rejects_invalid_company(client, value):
    assert client.get('/presencia/datos', query_string={'empresa_id': value}).status_code == 400


def test_database_failure_is_not_zero_attendance(client, monkeypatch):
    def fail(*args):
        raise RuntimeError('private database details')
    monkeypatch.setattr(routes, 'build_presence', fail)
    response = client.get('/presencia/datos')
    assert response.status_code == 503
    assert 'totales' not in response.json
    assert b'private' not in response.data


def test_registered_in_full_app(monkeypatch):
    import app as app_module
    monkeypatch.setattr(app_module, 'init_db', lambda: None)
    app = app_module.create_app()
    assert app.test_client().get('/presencia').status_code == 200
