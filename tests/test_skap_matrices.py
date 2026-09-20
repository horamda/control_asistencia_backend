import copy
import io
import json
import re
import sqlite3
import zipfile
from pathlib import Path
from xml.sax.saxutils import escape

import pytest
from flask import Flask

from repositories import skap_matriz_repository as repo
from services.skap_excel_service import match_employees, parse_workbook, summarize
from web.skap import matriz_routes as web
from routes import skap_routes as mobile


def workbook(cells, name='OPERARIOS DOL'):
    rows = {}
    for address, value in cells.items():
        row = re.sub(r'\D','',address)
        rows.setdefault(row,[]).append(f'<c r="{address}" t="inlineStr"><is><t>{escape(str(value))}</t></is></c>')
    data = io.BytesIO()
    with zipfile.ZipFile(data,'w') as z:
        z.writestr('xl/workbook.xml',f'<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets><sheet name="{name}" sheetId="1" r:id="rId1"/></sheets></workbook>')
        z.writestr('xl/_rels/workbook.xml.rels','<Relationships><Relationship Id="rId1" Target="worksheets/sheet1.xml"/></Relationships>')
        z.writestr('xl/worksheets/sheet1.xml','<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData>'+''.join(f'<row r="{r}">{"".join(cs)}</row>' for r,cs in rows.items())+'</sheetData></worksheet>')
    return data.getvalue()


def sample():
    return parse_workbook(workbook({'D6':'EVALUACION - 2019','D7':'Operarios','F7':'ESTANDAR','H7':'PEREZ ANA',
                    'D12':'Seguridad','C13':'A','D13':'Carga','F13':3,'H13':0,
                    'C14':'B','D14':'Equipo','F14':3,'H14':'NA',
                    'D15':'Orden','F15':3}), 'test.xlsx')


def test_parser_preserves_zero_na_missing_and_2019():
    ev = sample()['evaluaciones'][0]
    assert ev['anio'] == 2019 and ev['sucursal'] == 'Dolores'
    assert [(r['estado'],r['puntaje']) for r in ev['respuestas']] == [('evaluado',0),('no_aplica',None),('sin_evaluar',None)]
    assert ev['resumen']['cumplimiento_pct'] is None
    assert ev['resumen']['parcial_pct'] == 0
    assert ev['resumen']['criticidad_sin_definir'] == 1
    assert ev['resumen']['criticas']['cumplimiento_pct'] is None
    assert ev['fecha_evaluacion'] is None and ev['evaluador'] is None


def test_na_excludes_denominator_and_missing_is_not_zero():
    rows = sample()['evaluaciones'][0]['respuestas'][:2]
    rows[0]['puntaje'] = 3
    assert summarize(rows)['cumplimiento_pct'] == 100
    assert summarize(rows)['esperado'] == 3
    rows[0]['estado'] = 'sin_evaluar'; rows[0]['puntaje'] = None
    assert summarize(rows)['cumplimiento_pct'] is None


def test_invalid_score_and_broken_zip_rejected():
    with pytest.raises(ValueError): parse_workbook(b'not a zip')
    with pytest.raises(ValueError,match='puntaje inválido'):
        parse_workbook(workbook({'D6':'EVALUACION - 2026','D7':'Operarios','F7':'ESTANDAR','H7':'ANA','C13':'A','D13':'X','F13':3,'H13':5}))


def test_names_beyond_column_z_are_imported():
    data=parse_workbook(workbook({'D6':'EVALUACION - 2026','D7':'Operarios','F7':'ESTANDAR',
                                 'AA7':'ANA','C13':'A','D13':'X','F13':3,'AA13':4}))
    assert data['evaluaciones'][0]['respuestas'][0]['puntaje'] == 4


STAFF = [{'id':10,'empresa_id':1,'sucursal_id':1,'legajo':'001','apellido':'Pérez','nombre':'Ana','activo':1}]
BRANCHES = [{'id':2,'empresa_id':1,'nombre':'DOLORES'}]


def test_match_exact_across_historical_branch_without_changing_employee():
    payload = match_employees(sample(),STAFF,BRANCHES)
    ev = payload['evaluaciones'][0]
    assert ev['empleado_id'] == 10 and ev['legajo'] == '001' and ev['sucursal_id'] == 2
    assert ev['sucursal_actual_distinta'] and STAFF[0]['sucursal_id'] == 1


def test_ambiguous_or_short_name_requires_manual_mapping():
    staff = STAFF + [{**STAFF[0],'id':11}]
    assert match_employees(sample(),staff,BRANCHES)['pendientes'] == 1
    staff = [{**STAFF[0],'nombre':'Ana María'}]
    assert match_employees(sample(),staff,BRANCHES)['pendientes'] == 1
    assert match_employees(sample(),staff,BRANCHES,{'OPERARIOS DOL:H':10})['pendientes'] == 0
    with pytest.raises(ValueError): match_employees(sample(),staff,BRANCHES,{'OPERARIOS DOL:H':999})


@pytest.fixture
def database(monkeypatch):
    """Exercise repository SQL, transactions and scopes on an isolated in-memory DB."""
    conn = sqlite3.connect(':memory:')
    conn.row_factory = sqlite3.Row
    conn.create_function('CONCAT',-1,lambda *args: ''.join(str(a or '') for a in args))
    conn.executescript('''PRAGMA foreign_keys=ON;
      CREATE TABLE empresas(id INTEGER PRIMARY KEY);
      CREATE TABLE usuarios(id INTEGER PRIMARY KEY);
      CREATE TABLE sectores(id INTEGER PRIMARY KEY);
      CREATE TABLE sucursales(id INTEGER PRIMARY KEY,empresa_id INTEGER,nombre TEXT);
      CREATE TABLE empleados(id INTEGER PRIMARY KEY,empresa_id INTEGER,sector_id INTEGER,sucursal_id INTEGER,
                            nombre TEXT,apellido TEXT,legajo TEXT,reporta_a_empleado_id INTEGER,activo INTEGER);
      INSERT INTO empresas VALUES(1),(2); INSERT INTO usuarios VALUES(99);
      INSERT INTO sectores VALUES(1); INSERT INTO sucursales VALUES(1,1,'Casa Central'),(2,1,'Dolores'),(3,2,'Dolores');
      INSERT INTO empleados VALUES(10,1,1,1,'Ana','Perez','001',20,1),(11,1,1,1,'Luis','Perez','002',21,1),
      (20,1,1,1,'Jefe','Uno','020',NULL,1),(21,1,1,1,'Jefe','Dos','021',NULL,1),(30,2,1,3,'Otro','Empresa','030',NULL,1);
    ''')
    sql = (Path(__file__).parents[1]/'migrations/20260919_01_skap_matrices.sql').read_text(encoding='utf-8')
    sql = re.sub(r'^--.*$', '',sql,flags=re.M)
    sql = sql.replace('id BIGINT AUTO_INCREMENT PRIMARY KEY','id INTEGER PRIMARY KEY AUTOINCREMENT')
    sql = re.sub(r' INDEX \w+ \([^\n]+\),\n','',sql)
    sql = re.sub(r'UNIQUE KEY \w+','UNIQUE',sql)
    sql = re.sub(r'\) ENGINE=InnoDB[^;]+;',');',sql)
    conn.executescript(sql)
    class Cursor:
        def execute(self,sql,args=()):
            self.c = conn.execute(sql.replace('%s','?').replace(' FOR UPDATE',''),args)
            self.lastrowid = self.c.lastrowid; self.rowcount = self.c.rowcount
        def fetchone(self):
            row = self.c.fetchone(); return dict(row) if row else None
        def fetchall(self): return [dict(r) for r in self.c.fetchall()]
        def close(self): pass
    class Connection:
        def cursor(self,**kwargs): return Cursor()
        def commit(self): conn.commit()
        def rollback(self): conn.rollback()
        def close(self): pass
    monkeypatch.setattr(repo,'get_db',Connection)
    yield conn
    conn.close()


ACTOR = {'id':99,'empresa_id':1,'rol':'admin','empleado_id':None,'activo':1}


def import_sample(actor=ACTOR):
    payload = match_employees(sample(),STAFF,BRANCHES)
    batch_id = repo.save_preview(payload,actor['empresa_id'],actor['id'])
    result = repo.commit_import(batch_id,payload,actor,{'OPERARIOS DOL:H'})
    return batch_id,result,payload


def test_import_duplicate_conflict_and_atomic_rollback(database):
    batch,result,payload = import_sample()
    assert len(result['creadas']) == 1
    second = repo.save_preview(payload,1,99)
    assert repo.commit_import(second,payload,ACTOR,{'OPERARIOS DOL:H'})['duplicadas_omitidas']
    conflicting = copy.deepcopy(payload)
    new = copy.deepcopy(conflicting['evaluaciones'][0]); new.update(clave='otra',rol='Chofer')
    conflicting['evaluaciones'].insert(0,new)
    conflicting['evaluaciones'][1]['respuestas'][0]['puntaje'] = 4
    third = repo.save_preview(conflicting,1,99)
    with pytest.raises(ValueError,match='distintos puntajes'):
        repo.commit_import(third,conflicting,ACTOR,{'otra','OPERARIOS DOL:H'})
    assert database.execute('SELECT COUNT(*) FROM skap_matriz_evaluaciones').fetchone()[0] == 1
    assert repo.get_import(third,1)['estado'] == 'vista_previa'
    assert repo.get_import(batch,2) is None


def test_scope_own_supervisor_company_and_action_parent(database):
    batch,result,_ = import_sample(); eid = result['creadas'][0]
    owner = {**ACTOR,'rol':'empleado','empleado_id':10}
    assert len(repo.list_evaluations(owner)) == 1
    assert repo.list_evaluations({**owner,'empleado_id':11}) == []
    assert repo.get_evaluation(eid,{**owner,'empleado_id':11}) is None
    assert repo.get_evaluation(eid,{**ACTOR,'empresa_id':2}) is None
    assert repo.get_evaluation(eid,{**ACTOR,'rol':'supervisor','empleado_id':20})
    assert repo.get_evaluation(eid,{**ACTOR,'rol':'supervisor','empleado_id':21}) is None
    assert repo.get_evaluation(eid,{**ACTOR,'rol':'supervisor','empleado_id':20},own=True) is None
    assert repo.list_evaluations({**owner,'empleado_id':None}) == []
    assert repo.list_evaluations(owner,empleado_id=11) == []


def test_revert_and_action_audit(database):
    batch,result,_ = import_sample(); eid=result['creadas'][0]
    ev = repo.get_evaluation(eid,ACTOR)
    form={'accion':'Practicar carga','estado':'completado','progreso':'10','responsable_empleado_id':'20'}
    data = web.action_data(form,repo.employee_options(1))
    assert data['progreso'] == 100
    with pytest.raises(ValueError,match='Acción no encontrada'):
        repo.update_action(ev,999,data,ACTOR)
    repo.update_action(ev,ev['acciones'][0]['id'],data,ACTOR)
    with pytest.raises(ValueError,match='seguimiento'): repo.revert_import(batch,ACTOR)
    assert database.execute("SELECT COUNT(*) FROM skap_matriz_auditoria WHERE evento='editar_accion'").fetchone()[0] == 1
    assert repo.get_evaluation(eid,ACTOR)


def test_revert_preserves_source_and_allows_reimport(database):
    batch,result,_ = import_sample()
    assert repo.revert_import(batch,ACTOR) == 1
    assert repo.get_import(batch,1)['estado'] == 'revertida'
    assert repo.get_import(batch,1)['payload']['evaluaciones']
    assert repo.get_evaluation(result['creadas'][0],ACTOR) is None
    assert import_sample()[1]['creadas']


def test_confirmed_alias_is_reused(database):
    staff = [{**STAFF[0], 'nombre':'Ana María'}]
    payload = match_employees(sample(),staff,BRANCHES,{'OPERARIOS DOL:H':10})
    batch = repo.save_preview(payload,1,99)
    repo.commit_import(batch,payload,ACTOR,{'OPERARIOS DOL:H'})
    fresh = match_employees(sample(),staff,BRANCHES,aliases=repo.name_aliases(1))
    assert fresh['pendientes'] == 0
    assert fresh['evaluaciones'][0]['empleado_id'] == 10


def test_mobile_token_scope_and_no_write_or_ranking(database,monkeypatch):
    _,result,_=import_sample(); eid=result['creadas'][0]
    import utils.jwt_guard as jwt
    monkeypatch.setattr(jwt,'verificar_token',lambda token:{'empleado_id':int(token)})
    monkeypatch.setattr(mobile,'get_empleado_by_id',lambda i:{'id':i,'empresa_id':1,'activo':1})
    app=Flask(__name__);app.register_blueprint(mobile.skap_bp);client=app.test_client()
    assert client.get('/api/skap/matrices').status_code == 401
    owner={'Authorization':'Bearer 10'}; peer={'Authorization':'Bearer 11'}
    response=client.get('/api/skap/matrices?empleado_id=11',headers=owner)
    assert len(response.json['data']['items']) == 1
    assert client.get(f'/api/skap/matrices/{eid}',headers=peer).status_code == 404
    detail=client.get(f'/api/skap/matrices/{eid}',headers=owner)
    assert detail.status_code == 200 and 'contenido' not in detail.json['data']
    assert client.post('/api/skap/planes',json={'evaluacion_id':eid},headers=owner).status_code == 403
    assert client.get('/api/skap/ranking',headers=owner).status_code == 403


def test_web_employee_cannot_import_edit_or_view_peer(database,monkeypatch):
    _,result,_=import_sample(); eid=result['creadas'][0]
    actor={**ACTOR,'rol':'empleado','empleado_id':11}
    monkeypatch.setattr(web,'current_actor',lambda:actor)
    app=Flask(__name__);app.secret_key='test';app.register_blueprint(web.skap_matriz_bp)
    client=app.test_client()
    with client.session_transaction() as s:s['user_id']=99
    assert client.get(f'/skap/matrices/{eid}').status_code == 404
    assert client.get('/skap/matrices/importar').status_code == 403
    assert client.post(f'/skap/matrices/{eid}/acciones/1').status_code == 404
    actor['empleado_id']=10
    assert client.post(f'/skap/matrices/{eid}/acciones/1').status_code == 403


def test_render_operational_templates(database,monkeypatch):
    batch,result,_=import_sample()
    monkeypatch.setattr(web,'current_actor',lambda:ACTOR)
    from jinja2 import ChoiceLoader,DictLoader,FileSystemLoader
    app=Flask(__name__);app.secret_key='test';app.register_blueprint(web.skap_matriz_bp)
    app.jinja_loader=ChoiceLoader([DictLoader({'base.html':'{% block content %}{% endblock %}'}),FileSystemLoader(str(Path(__file__).parents[1]/'templates'))])
    app.jinja_env.globals['csrf_token']=lambda:'test'
    client=app.test_client()
    with client.session_transaction() as s:s['user_id']=99
    for path in ['/skap/matrices','/skap/matrices/importar',f'/skap/matrices/importaciones/{batch}',f"/skap/matrices/{result['creadas'][0]}"]:
        response=client.get(path)
        assert response.status_code == 200, path


def test_web_upload_review_and_apply(database,monkeypatch):
    monkeypatch.setattr(web,'current_actor',lambda:ACTOR)
    app=Flask(__name__);app.secret_key='test';app.register_blueprint(web.skap_matriz_bp)
    client=app.test_client()
    with client.session_transaction() as s:s['user_id']=99
    raw=workbook({'D6':'EVALUACION - 2026','D7':'Operarios','F7':'ESTANDAR','H7':'PEREZ ANA',
                  'C13':'A','D13':'Carga','F13':3,'H13':1})
    response=client.post('/skap/matrices/importar',data={'archivo':(io.BytesIO(raw),'matriz.xlsx')})
    assert response.status_code == 302
    response=client.post(response.location,data={'operacion':'importar','seleccion':'OPERARIOS DOL:H','empleado_OPERARIOS DOL:H':'10'})
    assert response.status_code == 302
    assert len(repo.list_evaluations(ACTOR)) == 1
