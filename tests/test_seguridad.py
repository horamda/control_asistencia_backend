"""Integration on an isolated MariaDB, never .env. Set SH_TEST_DB_PORT."""
import io
import os
from contextlib import contextmanager
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path
from uuid import uuid4

import mysql.connector
import pytest
from flask import Flask
from PIL import Image
from werkzeug.datastructures import FileStorage
from services import seguridad_service as s
from services import seguridad_import_service as imp
from routes import seguridad_routes as mobile
from routes import carga_routes
from web.seguridad import seguridad_routes as web
from web.carga import carga_routes as carga_web
import web.auth.decorators as auth
import utils.jwt_guard as jwt


@pytest.fixture
def database(monkeypatch):
    port=os.getenv('SH_TEST_DB_PORT')
    if not port: pytest.skip('SH_TEST_DB_PORT required; never connects using .env')
    name='seguridad_test_'+uuid4().hex
    settings=dict(host='127.0.0.1',port=int(port),user='root',password=os.getenv('SH_TEST_DB_PASSWORD',''),collation='utf8mb4_general_ci')
    root=mysql.connector.connect(**settings); cur=root.cursor()
    cur.execute(f'CREATE DATABASE `{name}` CHARACTER SET utf8mb4')
    def connect(): return mysql.connector.connect(**settings,database=name)
    db=connect(); c=db.cursor()
    try:
        for sql in [
            'CREATE TABLE empresas(id INT PRIMARY KEY)',
            'CREATE TABLE sucursales(id INT PRIMARY KEY,nombre VARCHAR(100))',
            'CREATE TABLE sectores(id INT PRIMARY KEY,nombre VARCHAR(100))',
            'CREATE TABLE puestos(id INT PRIMARY KEY,nombre VARCHAR(100))',
            'CREATE TABLE empleados(id INT PRIMARY KEY,empresa_id INT,sucursal_id INT,sector_id INT,puesto_id INT,activo INT,legajo VARCHAR(80),nombre VARCHAR(100),apellido VARCHAR(100))',
            'INSERT INTO empresas VALUES(1),(2)',
            "INSERT INTO sucursales VALUES(1,'Central'),(2,'Otra'),(3,'Empresa B')",
            "INSERT INTO sectores VALUES(1,'Entrega')", "INSERT INTO puestos VALUES(1,'Chofer')",
            "INSERT INTO empleados VALUES(10,1,1,1,1,1,'0010','Ana','Perez'),(11,1,1,1,1,1,'0011','Luis','Garcia'),(12,1,2,1,1,1,'0012','Otra','Sucursal'),(13,1,1,1,1,1,'0013','Persona','Ajena'),(20,2,3,1,1,1,'0020','Otra','Empresa')",
        ]: c.execute(sql)
        sql=(Path(__file__).resolve().parents[1]/'migrations/20261002_01_seguridad_higiene.sql').read_text(encoding='utf-8')
        for _ in range(2):
            for statement in sql.split(';'):
                if statement.strip(): c.execute(statement)
        c.execute("INSERT INTO sh_catalogos(id,empresa_id,clase,tipo,nombre) VALUES(1,1,'categoria','seguro','EPP correcto'),(2,1,'categoria','inseguro','Falta EPP'),(3,2,'categoria','seguro','Otra empresa')")
        db.commit()
        @contextmanager
        def transaction():
            conn=connect(); cursor=conn.cursor(dictionary=True)
            try: yield cursor; conn.commit()
            except Exception: conn.rollback(); raise
            finally: cursor.close(); conn.close()
        monkeypatch.setattr(s.db,'transaction',transaction)
        monkeypatch.setattr(s,'now_local',lambda:datetime(2026,10,2,12))
        yield connect
    finally:
        c.close();db.close()
        assert name.startswith('seguridad_test_') and len(name)==47
        cur.execute(f'DROP DATABASE `{name}`');cur.close();root.close()


def employee(eid=10):
    with s.db.transaction() as c: return s.db.one(c,'SELECT * FROM empleados WHERE id=%s',(eid,))


def payload(**kwargs):
    return dict(dict(tipo='seguro',fecha_evento='2026-09-01',categoria_id=1,descripcion='Usa protección correctamente.',involucrados=[10,11],envio_id=str(uuid4())),**kwargs)


def photo():
    buffer=io.BytesIO();Image.new('RGB',(4,4),'blue').save(buffer,format='PNG');buffer.seek(0)
    return FileStorage(stream=buffer,filename='test.png')


def test_approval_history_privacy_ranking_and_edit(database):
    eid,_=s.create(1,payload(),[photo()],reporter=employee())
    assert s.history(1,employee_id=11)['total']==0
    assert s.history(1,employee_id=10,mode='enviados')['total']==1
    with pytest.raises(s.Error): s.detail(1,eid,11)
    s.review(1,eid,99,'aprobado',1,'Verificado')
    detail=s.detail(1,eid,11)
    assert 'reportante_id' not in detail and 'auditoria' not in detail and 'motivo' not in detail
    assert len(detail['involucrados'])==1
    assert s.history(1,employee_id=11)['total']==1
    for company,person in [(1,13),(2,20)]:
        with pytest.raises(s.Error): s.detail(company,eid,person)
        with pytest.raises(s.Error): s.photo(company,detail['fotos'][0]['id'],person)
    result=s.rankings(1,2026,9)
    assert result['eventos']==[{'tipo':'seguro','cantidad':1}]
    assert len(result['rankings']['seguro'])==2
    assert all(r['cantidad']==1 and r['posicion']==1 for r in result['rankings']['seguro'])
    assert s.rankings(1,2026,10)['eventos']==[]
    with pytest.raises(s.Error): s.review(1,eid,99,'rechazado',1,'Duplicado')
    photo_id=detail['fotos'][0]['id']
    s.edit(1,eid,99,payload(revision=2,descripcion='Corrección',quitar_fotos=[photo_id]))
    assert s.rankings(1,2026)['eventos']==[]
    assert s.detail(1,eid)['estado']=='pendiente'
    assert s.detail(1,eid)['fotos']==[]
    with pytest.raises(s.Error): s.photo(1,photo_id)
    with s.db.transaction() as c:
        assert s.db.one(c,'SELECT LENGTH(contenido) size FROM sh_fotos WHERE id=%s',(photo_id,))['size']>0


@pytest.mark.parametrize('changes',[
    {'involucrados':[12]}, {'involucrados':[20]}, {'categoria_id':3}, {'categoria_id':2},
    {'fecha_evento':'2026-10-03'},{'tipo':'inseguro','categoria_id':2},
    {'tipo':'accidente','categoria_id':None}, {'envio_id':'bad'}, {'involucrados':[]},
])
def test_reject_invalid_payloads(database,changes):
    with pytest.raises(s.Error): s.create(1,payload(**changes),reporter=employee())
    assert s.history(1)['total']==0


def test_duplicate_concurrent_requests_and_rollback(database,monkeypatch):
    data=payload(); reporter=employee()
    with ThreadPoolExecutor(max_workers=2) as executor:
        results=list(executor.map(lambda _:s.create(1,data,reporter=reporter),range(2)))
    assert results[0][0]==results[1][0] and sum(int(r[1]) for r in results)==1
    with pytest.raises(s.Error): s.create(1,{**data,'descripcion':'Otra'},reporter=reporter)
    original=s.audit
    def fail(*args,**kwargs): raise RuntimeError('audit storage failure')
    monkeypatch.setattr(s,'audit',fail)
    with pytest.raises(RuntimeError): s.create(1,payload(),[photo()],reporter=reporter)
    monkeypatch.setattr(s,'audit',original)
    assert s.history(1)['total']==1


@pytest.fixture
def client(database,monkeypatch):
    app=Flask(__name__,template_folder=str(Path(__file__).resolve().parents[1]/'templates'))
    app.secret_key='test'; app.config['TESTING']=True
    app.register_blueprint(web.seguridad_web_bp);app.register_blueprint(mobile.seguridad_mobile_bp)
    app.jinja_env.globals.update(csrf_token=lambda:'test',can_web=lambda code,*args:code=='seguridad_higiene',export_toolbar={'enabled':False,'items':[]})
    monkeypatch.setattr(auth,'can_access_module',lambda *args:True)
    monkeypatch.setattr(carga_web,'get_user',lambda uid:dict(id=uid,empresa_id=1,rol='supervisor',activo=1))
    monkeypatch.setattr(jwt,'verificar_token',lambda token:dict(empleado_id=int(token)))
    monkeypatch.setattr(carga_routes,'get_by_id',employee)
    client=app.test_client()
    with client.session_transaction() as sess: sess['user_id']=99
    return client


def test_web_templates_and_permissions_and_mobile(client,monkeypatch):
    eid,_=s.create(1,payload(),user=99)
    for path in ['', 'nuevo','catalogos','ranking','importar',f'eventos/{eid}',f'eventos/{eid}/editar']:
        response=client.get('/seguridad-higiene/'+path)
        assert response.status_code==200,(path,response.data[:500])
    assert client.get('/seguridad-higiene/?empresa_id=2').status_code==200
    export=client.get('/seguridad-higiene/exportar')
    assert export.status_code==200
    assert '0010' in export.get_data(as_text=True) and 'Perez Ana' in export.get_data(as_text=True)
    assert client.get('/api/v1/mobile/seguridad/config').status_code==401
    headers={'Authorization':'Bearer 10'}
    config=client.get('/api/v1/mobile/seguridad/config',headers=headers).json
    assert {p['id'] for p in config['empleados']}=={10,11,13}
    response=client.post('/api/v1/mobile/seguridad/eventos',json=payload(),headers=headers)
    assert response.status_code==201
    assert client.get('/api/v1/mobile/seguridad/ranking',headers=headers).json['rankings']=={'seguro':[],'inseguro':[]}
    monkeypatch.setattr(auth,'can_access_module',lambda uid,module,action='ver':action=='ver')
    assert client.post(f'/seguridad-higiene/eventos/{eid}/revisar',data=dict(estado='aprobado',revision=1)).status_code==403
    assert client.post('/seguridad-higiene/nuevo',data={}).status_code==403
    assert client.get('/seguridad-higiene/exportar').status_code==403


def test_review_cannot_bypass_annul_permission(client,monkeypatch):
    eid,_=s.create(1,payload(),user=99)
    monkeypatch.setattr(auth,'can_access_module',lambda uid,module,action='ver':action in ('ver','aprobar'))
    assert client.post(f'/seguridad-higiene/eventos/{eid}/revisar',data=dict(estado='anulado',revision=1,motivo='x')).status_code==400
    assert client.post(f'/seguridad-higiene/eventos/{eid}/anular',data=dict(revision=1,motivo='x')).status_code==403


def test_actions_catalog_and_cross_company(database):
    eid,_=s.create(1,payload(),user=99)
    s.save_action(1,eid,99,dict(descripcion='Capacitar',responsable_id=11,vencimiento='2026-10-10'))
    detail=s.detail(1,eid)
    assert detail['acciones'][0]['estado']=='pendiente'
    with pytest.raises(s.Error): s.save_action(2,eid,99,dict(descripcion='x',responsable_id=20,vencimiento='2026-10-10'))
    with pytest.raises(s.Error): s.save_action(1,eid,99,dict(descripcion='x',responsable_id=11,vencimiento='2026-10-10',estado='cerrada'))
    s.save_catalog(1,99,dict(clase='categoria',tipo='seguro',nombre='Otra categoría'))
    assert len(s.config(1)['catalogos'])==3


def test_import_keeps_every_row_original_and_duplicates(database,monkeypatch):
    # No spreadsheet authoring library: parsed synthetic rows exercise the real staging SQL.
    headers=['Marca temporal','Apellido y nombre completo de la persona a informar','Que va a notificar','Fecha del evento','Fecha del evento','Comportamiento Seguro','Comentarios, describir la tarea que se realizo']
    rows=[dict(hoja='Respuestas',fila=3,original=dict(encabezados=headers,celdas=['2026-09-01','Perez Ana','Comportamiento Seguro',None,'2026-09-01','EPP correcto','Usa protección'])),
          dict(hoja='Respuestas',fila=4,original=dict(encabezados=headers,celdas=['2026-09-02',None,None]))]
    monkeypatch.setattr(imp,'read_file',lambda file:(b'original-file-preserved',rows))
    file=FileStorage(filename='respuestas.xlsx')
    bid=imp.stage(1,99,file)
    assert imp.stage(1,99,file)==bid
    info=imp.batch(1,bid)
    assert info['totales']['total']==2
    assert imp.import_ready(1,bid,99)==(1,1)
    assert imp.import_ready(1,bid,99)==(0,1)
    assert s.history(1)['items'][0]['estado']=='pendiente'
    with s.db.transaction() as c:
        assert s.db.one(c,'SELECT archivo FROM sh_importaciones WHERE id=%s',(bid,))['archivo']==b'original-file-preserved'
    with pytest.raises(s.Error): imp.batch(2,bid)
    monkeypatch.setattr(imp,'read_file',lambda file:(b'new-export-same-responses',rows))
    second=imp.stage(1,98,file)
    assert second!=bid
    assert imp.import_ready(1,second,98)==(0,1)
    assert imp.batch(1,second)['totales']['resueltas']==1
    assert s.history(1)['total']==1


def test_migration_seeds_idempotently_without_reactivation(database,monkeypatch):
    import importlib.util
    path=Path(__file__).resolve().parents[1]/'scripts/migrate_20261002_01_seguridad_higiene.py'
    spec=importlib.util.spec_from_file_location('sh_migration',path)
    module=importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    monkeypatch.setattr(module,'init_orm',lambda:None)
    monkeypatch.setattr(module,'get_db',database)
    module.migrate()
    with s.db.transaction() as c:
        count=s.db.one(c,'SELECT COUNT(*) n FROM sh_catalogos')['n']
        c.execute('UPDATE sh_catalogos SET activo=0')
    module.migrate()
    with s.db.transaction() as c:
        assert s.db.one(c,'SELECT COUNT(*) n FROM sh_catalogos')['n']==count
        assert s.db.one(c,'SELECT COUNT(*) n FROM sh_catalogos WHERE activo=1')['n']==0


def test_web_requires_csrf(client):
    from flask_wtf.csrf import CSRFProtect
    CSRFProtect(client.application)
    response=client.post('/seguridad-higiene/nuevo',data=payload())
    assert response.status_code==400
    assert s.history(1)['total']==0
