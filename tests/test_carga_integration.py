"""Pruebas en MySQL/MariaDB AISLADO. Activar CARGA_TEST_DB_PORT, nunca usa .env.

El usuario local debe poder crear bases. Se crea/elimina exclusivamente una base
con prefijo carga_test_ y sufijo UUID, sin usar datos ni tablas de produccion.
"""
import io
import os
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, date
from pathlib import Path
from uuid import uuid4

import mysql.connector
import pytest
from flask import Flask
from PIL import Image
from werkzeug.datastructures import FileStorage
from repositories import carga_repository as repo
from services import carga_service as service
from routes import carga_routes as mobile
from web.carga import carga_routes as web
import web.auth.decorators as auth
import utils.jwt_guard as jwt


@pytest.fixture
def database(monkeypatch):
    port = os.getenv('CARGA_TEST_DB_PORT')
    if not port:
        pytest.skip('Requiere CARGA_TEST_DB_PORT de un MySQL local aislado.')
    settings = dict(host='127.0.0.1', port=int(port), user='root', password='', collation='utf8mb4_general_ci')
    name = 'carga_test_' + uuid4().hex
    admin = mysql.connector.connect(**settings)
    c = admin.cursor()
    c.execute(f'CREATE DATABASE `{name}` CHARACTER SET utf8mb4 COLLATE utf8mb4_general_ci')
    def connect():
        return mysql.connector.connect(**settings, database=name)
    monkeypatch.setattr(repo, 'get_db', connect)
    db = connect()
    cur = db.cursor()
    try:
        for sql in [
            'CREATE TABLE empresas (id INT PRIMARY KEY, razon_social VARCHAR(80))',
            'CREATE TABLE sucursales (id INT PRIMARY KEY, empresa_id INT, nombre VARCHAR(100), activa INT)',
            'CREATE TABLE puestos (id INT PRIMARY KEY, empresa_id INT, nombre VARCHAR(100), activo INT)',
            'CREATE TABLE empleados (id INT PRIMARY KEY, empresa_id INT, sucursal_id INT, puesto_id INT, activo INT, legajo VARCHAR(80), nombre VARCHAR(100), apellido VARCHAR(100))',
            'CREATE TABLE empleado_puestos (empleado_id INT, empresa_id INT, puesto_id INT, activo INT)',
            "INSERT INTO empresas VALUES (1,'Empresa A'),(2,'Empresa B')",
            "INSERT INTO sucursales VALUES (1,1,'Sucursal empleado',1),(2,1,'Sucursal camión',1),(3,2,'Otra empresa',1)",
            "INSERT INTO puestos VALUES (1,1,'Chofer',1),(2,1,'Administración',1),(3,1,'Ayudante reparto',1),(4,2,'Chofer B',1)",
            "INSERT INTO empleados VALUES (10,1,1,1,1,'0010','Ana','Chofer'),(11,1,1,2,1,'0011','Luis','Ayudante'),(12,1,1,2,1,'0012','María','Admin'),(20,2,3,4,1,'0020','Otra','Persona')",
            'INSERT INTO empleado_puestos VALUES (11,1,3,1)',
        ]:
            cur.execute(sql)
        sql = (Path(__file__).resolve().parents[1] / 'migrations/20260929_01_validacion_carga.sql').read_text(encoding='utf-8')
        sql = '\n'.join(line for line in sql.splitlines() if not line.startswith('--'))
        for _ in range(2):  # Migracion repetible, incluidos los horarios iniciales.
            for statement in sql.split(';'):
                if statement.strip():
                    cur.execute(statement)
        cur.execute("INSERT INTO carga_camiones (id,empresa_id,sucursal_id,numero,patente) VALUES (1,1,2,'01','AA001AA'),(2,1,2,'02','AA002AA'),(3,2,3,'03','AA003AA')")
        cur.execute('INSERT INTO carga_puestos VALUES (1,1),(1,3),(2,4)')
        db.commit()
        monkeypatch.setattr(service, 'now_local', lambda: datetime(2026, 9, 29, 8, 4, 59))
        yield connect
    finally:
        cur.close()
        db.close()
        assert name.startswith('carga_test_') and len(name) == 43
        c.execute(f'DROP DATABASE `{name}`')
        c.close()
        admin.close()


def payload(**kwargs):
    return dict(camion_id=1, tipo='inicial', consolidado='000123', valida=True, observaciones='', envio_id=str(uuid4()), origen='app', **kwargs)


def get_employee(employee_id):
    with repo.transaction() as c:
        return repo.one(c, 'SELECT * FROM empleados WHERE id=%s', (employee_id,))


def test_snapshots_idempotency_and_recargas(database, monkeypatch):
    data = payload()
    first, created = service.create(10, data, [])
    assert created
    assert service.create(10, data, []) == (first, False)
    with pytest.raises(service.CargaError, match='otros datos'):
        service.create(10, {**data, 'consolidado': 'changed'}, [])
    row = repo.detail(first, 1)
    assert row['en_horario'] == 1 and row['legajo'] == '0010'
    assert row['sucursal_empleado_nombre'] == 'Sucursal empleado'
    assert row['sucursal_camion_nombre'] == 'Sucursal camión'
    with repo.transaction() as c:
        c.execute("UPDATE empleados SET sucursal_id=2,legajo='NEW' WHERE id=10")
        c.execute("UPDATE sucursales SET nombre='Renombrada' WHERE id=1")
        c.execute("UPDATE carga_camiones SET numero='99' WHERE id=1")
    assert repo.detail(first, 1)['legajo'] == '0010'
    assert repo.detail(first, 1)['sucursal_empleado_nombre'] == 'Sucursal empleado'
    assert repo.detail(first, 1)['camion_numero'] == '01'
    monkeypatch.setattr(service, 'now_local', lambda: datetime(2026, 9, 29, 11, 0))
    for consolidated in ('000124', '000125'):
        record, _ = service.create(11, {**payload(), 'tipo': 'recarga', 'consolidado': consolidated}, [])
        assert repo.detail(record, 1)['en_horario'] == 1
    assert repo.history(1, {})[1] == 3
    assert repo.history(1, {}, empleado_id=11)[1] == 2
    assert repo.detail(first, 2) is None
    assert repo.detail(first, 1, 11) is None


def test_no_response_late_and_require_initial(database, monkeypatch):
    with pytest.raises(service.CargaError, match='Primero'):
        service.create(10, {**payload(), 'tipo': 'recarga'}, [])
    with pytest.raises(service.CargaError, match='observaciones'):
        service.create(10, {**payload(), 'valida': False}, [])
    monkeypatch.setattr(service, 'now_local', lambda: datetime(2026, 9, 29, 8, 5))
    record, _ = service.create(10, {**payload(), 'valida': False, 'observaciones': 'Faltan bultos'}, [])
    assert repo.detail(record, 1)['valida'] == 0
    assert repo.detail(record, 1)['en_horario'] == 0
    monkeypatch.setattr(service, 'now_local', lambda: datetime(2026, 9, 29, 10, 59, 59))
    record, _ = service.create(10, {**payload(), 'tipo': 'recarga', 'consolidado': 'new'}, [])
    assert repo.detail(record, 1)['en_horario'] == 0


def test_permissions_and_cross_company(database):
    with pytest.raises(service.CargaError) as error:
        service.create(12, payload(), [])
    assert error.value.status == 403
    with pytest.raises(service.CargaError) as error:
        service.create(20, payload(), [])
    assert error.value.status == 404
    assert service.config(get_employee(11))['habilitado'] is True
    assert service.config(get_employee(12))['habilitado'] is False
    with repo.transaction() as c:
        c.execute("UPDATE empleados SET legajo='' WHERE id=10")
    with pytest.raises(service.CargaError, match='legajo'):
        service.create(10, payload(), [])


def test_one_initial_under_concurrency(database):
    def send(employee_id):
        try:
            return service.create(employee_id, payload(), [])[0]
        except service.CargaError as error:
            return error.status
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(send, (10, 11)))
    assert results.count(409) == 1
    assert repo.history(1, {})[1] == 1


def test_idempotent_concurrent_retry_and_new_day(database, monkeypatch):
    data = payload()
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: service.create(10, data, []), range(2)))
    assert results[0][0] == results[1][0]
    assert sorted(r[1] for r in results) == [False, True]
    monkeypatch.setattr(service, 'now_local', lambda: datetime(2026, 9, 30, 7, 0))
    new_record, _ = service.create(11, payload(), [])
    assert repo.detail(new_record, 1)['fecha'] == date(2026, 9, 30)
    assert repo.history(1, {})[1] == 2


def test_rule_overlap_scope_and_history(database):
    data = dict(nombre='Sucursal', sucursal_id='2', tipo='inicial', desde='00:00', hasta='08:00',
        vigente_desde='2026-09-01', vigente_hasta='', activo='1')
    rule = service.save_catalog('horarios', None, 1, 99, data)
    with pytest.raises(service.CargaError, match='superpuesta'):
        service.save_catalog('horarios', None, 1, 99, data)
    record, _ = service.create(10, payload(), [])
    assert repo.detail(record, 1)['en_horario'] == 0
    service.save_catalog('horarios', rule, 1, 99, {**data, 'hasta': '09:00'})
    assert repo.detail(record, 1)['hasta_minuto'] == 480
    with pytest.raises(service.CargaError, match='pertenece'):
        service.save_catalog('horarios', rule, 1, 99, {**data, 'sucursal_id': '3'})
    with pytest.raises(service.CargaError, match='activos'):
        service.save_positions(1, 99, ['4'])


def test_photos_transactional_private_and_catalog_crud(database, monkeypatch):
    out = io.BytesIO()
    Image.new('RGB', (20, 20)).save(out, format='PNG')
    out.seek(0)
    record, _ = service.create(10, payload(), [FileStorage(stream=out, filename='test.png')])
    photo_id = repo.detail(record, 1)['fotos'][0]['id']
    assert repo.photo(photo_id, 1, 10)['contenido'].startswith(b'\xff\xd8')
    assert repo.photo(photo_id, 1, 11) is None
    assert repo.photo(photo_id, 2) is None
    truck_data = dict(sucursal_id='2', numero='NEW', patente='NEW123', descripcion='', activo='1')
    truck_id = service.save_catalog('camiones', None, 1, 99, truck_data)
    service.save_catalog('camiones', truck_id, 1, 99, {**truck_data, 'activo': '0'})
    assert not next(t for t in repo.catalogs(1)['camiones'] if t['id'] == truck_id)['activo']
    with pytest.raises(service.CargaError, match='inactivo'):
        service.create(10, {**payload(), 'camion_id': truck_id}, [])
    original_insert = repo.insert
    def fail_photo(cursor, table, values):
        if table == 'carga_fotos':
            raise RuntimeError('simulated storage failure')
        return original_insert(cursor, table, values)
    monkeypatch.setattr(repo, 'insert', fail_photo)
    out.seek(0)
    with pytest.raises(RuntimeError):
        service.create(10, {**payload(), 'camion_id': 2}, [FileStorage(stream=out, filename='x.png')])
    assert repo.history(1, {})[1] == 1


@pytest.fixture
def client(database, monkeypatch):
    app = Flask(__name__, template_folder=str(Path(__file__).resolve().parents[1] / 'templates'))
    app.secret_key = 'test-only'
    app.config['TESTING'] = True
    app.register_blueprint(mobile.carga_mobile_bp)
    app.register_blueprint(web.carga_web_bp)
    monkeypatch.setattr(jwt, 'verificar_token', lambda token: {'empleado_id': int(token)})
    monkeypatch.setattr(mobile, 'get_by_id', get_employee)
    monkeypatch.setattr(web, 'get_user', lambda uid: {'id': uid, 'empresa_id': 1, 'rol': 'supervisor', 'activo': 1})
    monkeypatch.setattr(auth, 'can_access_module', lambda uid, module, action='ver': action == 'ver')
    monkeypatch.setattr(web, 'can_access_module', lambda uid, module, action='ver': action == 'ver')
    app.jinja_env.globals.update(csrf_token=lambda: 'test', can_web=lambda *a: False, export_toolbar={'enabled': False, 'items': []})
    return app.test_client()


def test_api_and_web_permissions(client):
    assert client.get('/api/v1/mobile/cargas/config').status_code == 401
    headers = {'Authorization': 'Bearer 10'}
    response = client.post('/api/v1/mobile/cargas', headers=headers, json=payload())
    assert response.status_code == 201
    record = response.json['registro']
    assert record['registrado_at'].endswith('-03:00')
    assert client.get(f"/api/v1/mobile/cargas/{record['id']}", headers={'Authorization': 'Bearer 11'}).status_code == 404
    with client.session_transaction() as sess:
        sess['user_id'] = 99
    assert client.get('/validacion-carga/').status_code == 200
    assert client.get('/validacion-carga/catalogos').status_code == 200
    assert client.get(f"/validacion-carga/{record['id']}").status_code == 200
    assert client.get('/validacion-carga/auditoria').status_code == 200
    assert client.get('/validacion-carga/?desde=invalid').status_code == 400
    assert client.get('/validacion-carga/?empresa_id=2').status_code == 200  # No-admin scope ignores override.
    assert client.get('/validacion-carga/exportar').status_code == 403
    assert client.post('/validacion-carga/catalogos/camiones/nuevo', data={'numero': 'bad'}).status_code == 403


def test_web_catalog_edit_and_export(client, monkeypatch):
    monkeypatch.setattr(auth, 'can_access_module', lambda *a: True)
    monkeypatch.setattr(web, 'can_access_module', lambda *a: True)
    with client.session_transaction() as sess:
        sess['user_id'] = 99
    for route in ('/validacion-carga/catalogos/camiones/nuevo', '/validacion-carga/catalogos/horarios/nuevo',
                  '/validacion-carga/catalogos/camiones/1/editar', '/validacion-carga/catalogos/horarios/1/editar'):
        assert client.get(route).status_code == 200
    response = client.post('/validacion-carga/catalogos/camiones/nuevo', data={
        'empresa_id': '2', 'sucursal_id': '2', 'numero': '04', 'patente': 'AA004AA', 'activo': '1'})
    assert response.status_code == 302
    assert len(repo.catalogs(1)['camiones']) == 3  # Written to user's own company, despite submitted override.
    assert len(repo.catalogs(2)['camiones']) == 1
    response = client.get('/validacion-carga/exportar')
    assert response.status_code == 200 and 'text/csv' in response.content_type
    assert b'sucursal_empleado_nombre' in response.data


def test_csv_formula_escape():
    assert web.csv_safe('=HYPERLINK("bad")').startswith("'")
    assert web.csv_safe(' +CMD').startswith("'")
