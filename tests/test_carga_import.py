import io
import sqlite3
from contextlib import contextmanager
from pathlib import Path

import pytest
from flask import Flask
from itsdangerous import URLSafeTimedSerializer, TimestampSigner
from werkzeug.datastructures import FileStorage

from repositories import carga_repository as repo
from services import carga_import_service as importer
from services.carga_service import CargaError
from web.carga import carga_routes as web
import web.auth.decorators as auth


def csv_file(text, encoding='utf-8-sig'):
    return FileStorage(stream=io.BytesIO(text.encode(encoding)), filename='camiones.csv')


@pytest.fixture
def database(monkeypatch):
    # Motor aislado para comprobar SQL, rollback y auditoria sin tocar .env.
    db = sqlite3.connect(':memory:')
    db.row_factory = sqlite3.Row
    db.executescript('''
        CREATE TABLE empresas(id INTEGER PRIMARY KEY);
        INSERT INTO empresas VALUES (1),(2);
        CREATE TABLE sucursales(id INTEGER PRIMARY KEY, empresa_id INTEGER, nombre TEXT, activa INTEGER);
        INSERT INTO sucursales VALUES(1,1,'Central',1),(2,2,'Otra empresa',1),(3,1,'Inactiva',0);
        CREATE TABLE carga_camiones(id INTEGER PRIMARY KEY,empresa_id INTEGER,sucursal_id INTEGER,
            numero TEXT,patente TEXT,descripcion TEXT,activo INTEGER,
            UNIQUE(empresa_id,numero),UNIQUE(empresa_id,patente));
        CREATE TABLE carga_auditoria(id INTEGER PRIMARY KEY,empresa_id INTEGER,usuario_id INTEGER,
            entidad TEXT,registro_id INTEGER,detalle TEXT);
    ''')

    class Cursor:
        def __init__(self):
            self.cursor = db.cursor()

        def execute(self, sql, params=()):
            self.cursor.execute(sql.replace('%s', '?').replace(' FOR UPDATE', ''), params)

        def fetchone(self):
            row = self.cursor.fetchone()
            return dict(row) if row else None

        def fetchall(self):
            return [dict(row) for row in self.cursor.fetchall()]

        @property
        def lastrowid(self):
            return self.cursor.lastrowid

    @contextmanager
    def transaction():
        c = Cursor()
        try:
            yield c
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            c.cursor.close()

    monkeypatch.setattr(repo, 'transaction', transaction)
    yield db
    db.close()


@pytest.mark.parametrize('delimiter', [';', ',', '\t'])
def test_parse_formats_preserves_zeroes_and_defaults(delimiter):
    text = delimiter.join(['numero','patente','descripcion','activo'])+'\n'+delimiter.join(['001','aa001aa','Vehículo','sí'])
    rows, errors = importer.parse_file(csv_file(text), '1')
    assert not errors
    assert rows == [dict(fila=2,numero='001',patente='AA001AA',descripcion='Vehículo',activo=1,sucursal_id=1)]


def test_excel_encoding_quotes_and_blanks():
    rows, errors = importer.parse_file(csv_file('numero;patente;sucursal_id;descripcion;activo\n001;AA001AA;1;"Camión; reparto"; \n;;;;\n', 'cp1252'))
    assert not errors and len(rows) == 1
    assert rows[0]['descripcion'] == 'Camión; reparto'
    assert rows[0]['activo'] == 1


@pytest.mark.parametrize('text', ['numero;patente\n', 'numero;numero;patente\n', 'foo;bar\n1;2', 'numero;patente\n"unterminated'])
def test_invalid_file(text):
    with pytest.raises(CargaError):
        importer.parse_file(csv_file(text), '1')


def test_duplicates_bad_rows_and_limits():
    rows, errors = importer.parse_file(csv_file('numero;patente;activo\n1;AA1;1\n1;AA2;1\n3;AA3;talvez\n4;AA4;1;extra\n'), '1')
    assert len(rows) == 1
    assert [e['fila'] for e in errors] == [3,4,5]
    with pytest.raises(CargaError):
        importer.parse_file(csv_file('x' * (importer.MAX_BYTES + 1)))
    with pytest.raises(CargaError):
        importer.parse_file(csv_file('numero;patente\n' + '\n'.join(f'{i};AA{i}' for i in range(501))), '1')


def test_preview_atomic_import_audit_and_retries(database):
    rows, _ = importer.parse_file(csv_file('numero;patente\n001;AA001AA\n002;AA002AA'), '1')
    plan, errors = importer.preview(rows,1)
    assert not errors and len(plan) == 2
    assert database.execute('SELECT COUNT(*) FROM carga_camiones').fetchone()[0] == 0
    assert importer.import_rows(rows,1,99) == {'creados':2,'omitidos':0,'errores':[]}
    assert database.execute('SELECT COUNT(*) FROM carga_auditoria').fetchone()[0] == 2
    assert importer.import_rows(rows,1,99) == {'creados':0,'omitidos':2,'errores':[]}
    conflict = [{**rows[0], 'patente':'CHANGED'}, {**rows[1], 'numero':'NEW','patente':'NEW'}]
    assert importer.import_rows(conflict,1,99)['errores']
    assert database.execute('SELECT COUNT(*) FROM carga_camiones').fetchone()[0] == 2


@pytest.mark.parametrize('branch', ['2','3'])
def test_other_company_and_inactive_branch_rejected(database, branch):
    rows, _ = importer.parse_file(csv_file(f'numero;patente;sucursal_id\n1;AA1;{branch}'))
    assert importer.import_rows(rows,1,99)['errores']
    assert database.execute('SELECT COUNT(*) FROM carga_camiones').fetchone()[0] == 0


def test_audit_failure_rolls_back_whole_batch(database,monkeypatch):
    rows, _ = importer.parse_file(csv_file('numero;patente\n001;AA001AA\n002;AA002AA'), '1')
    count = 0
    original = importer.audit
    def fail_second(*args):
        nonlocal count
        count += 1
        if count == 2:
            raise RuntimeError('storage failure')
        original(*args)
    monkeypatch.setattr(importer,'audit',fail_second)
    with pytest.raises(RuntimeError):
        importer.import_rows(rows,1,99)
    assert database.execute('SELECT COUNT(*) FROM carga_camiones').fetchone()[0] == 0
    assert database.execute('SELECT COUNT(*) FROM carga_auditoria').fetchone()[0] == 0


@pytest.fixture
def client(database, monkeypatch):
    app=Flask(__name__,template_folder=str(Path(__file__).resolve().parents[1]/'templates'))
    app.secret_key='isolated-test'
    app.config['TESTING']=True
    app.register_blueprint(web.carga_web_bp)
    app.jinja_env.globals.update(csrf_token=lambda:'test',can_web=lambda *args:False,export_toolbar={'enabled':False,'items':[]})
    monkeypatch.setattr(auth,'can_access_module',lambda *args:True)
    monkeypatch.setattr(web,'get_user',lambda uid:{'id':uid,'empresa_id':1,'rol':'supervisor','activo':1})
    monkeypatch.setattr(repo,'catalogs',lambda empresa_id:{'sucursales':[{'id':1,'nombre':'Central','activa':1}]})
    client=app.test_client()
    with client.session_transaction() as session:
        session['user_id']=99
    return client


def test_web_preview_and_confirm(client,database):
    assert client.get('/validacion-carga/camiones/importar').status_code == 200
    assert client.get('/validacion-carga/camiones/plantilla.csv').data.decode('utf-8-sig').startswith('numero;patente;')
    response=client.post('/validacion-carga/camiones/importar',data={
        'archivo':(io.BytesIO(b'numero;patente\n001;AA001AA'), 'camiones.csv'), 'sucursal_id':'1', 'empresa_id':'2'})
    assert response.status_code==200
    from html.parser import HTMLParser
    class TokenParser(HTMLParser):
        token=None
        def handle_starttag(self,tag,attrs):
            attrs=dict(attrs)
            if attrs.get('name')=='import_token': self.token=attrs['value']
    parser=TokenParser();parser.feed(response.get_data(as_text=True))
    assert parser.token
    assert database.execute('SELECT COUNT(*) FROM carga_camiones').fetchone()[0] == 0
    response=client.post('/validacion-carga/camiones/importar',data={'accion':'confirmar','import_token':parser.token,'empresa_id':'2'})
    assert response.status_code==302
    assert database.execute('SELECT empresa_id FROM carga_camiones').fetchone()[0]==1
    assert client.post('/validacion-carga/camiones/importar',data={'accion':'confirmar','import_token':parser.token}).status_code==302
    assert database.execute('SELECT COUNT(*) FROM carga_camiones').fetchone()[0]==1


def test_invalid_expired_other_user_tokens_and_permission(client,database,monkeypatch):
    rows,_=importer.parse_file(csv_file('numero;patente\n1;AA1'),'1')
    signer=URLSafeTimedSerializer(client.application.secret_key,salt='carga-import-camiones-v1')
    payload={'rows':rows,'empresa_id':1,'usuario_id':99}
    other=signer.dumps({**payload,'usuario_id':100})
    assert client.post('/validacion-carga/camiones/importar',data={'accion':'confirmar','import_token':other}).status_code==403
    with monkeypatch.context() as m:
        original=TimestampSigner.get_timestamp
        m.setattr(TimestampSigner,'get_timestamp',lambda self:original(self)-1000)
        expired=signer.dumps(payload)
    for token in ['invalid',expired]:
        response=client.post('/validacion-carga/camiones/importar',data={'accion':'confirmar','import_token':token})
        assert response.status_code==200
        assert b'Confirmar importaci' not in response.data
    assert database.execute('SELECT COUNT(*) FROM carga_camiones').fetchone()[0]==0
    monkeypatch.setattr(auth,'can_access_module',lambda uid,module,action:action=='ver')
    assert client.get('/validacion-carga/camiones/importar').status_code==403
