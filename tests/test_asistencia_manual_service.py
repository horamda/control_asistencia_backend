import json
import sqlite3
from pathlib import Path
import pytest
from services import asistencia_manual_service as service
from repositories import asistencia_repository as summaries
from repositories import asistencia_marca_repository as marks
import utils.asistencia as rules

@pytest.fixture
def attendance_db(monkeypatch):
    db=sqlite3.connect(':memory:');db.row_factory=sqlite3.Row
    db.create_function('CONCAT',-1,lambda *args: ''.join(str(a or '') for a in args))
    basic=['empresa_id','empleado_id','fecha','hora_entrada','hora_salida','estado','observaciones','created_at']
    for side in ['entrada','salida']:
        basic += [f'{c}_{side}' for c in ['lat','lon','foto','metodo','gps_ok','gps_ref_lat','gps_ref_lon']]
        basic += [f'gps_{c}_{side}_m' for c in ['distancia','tolerancia']]
    db.execute('CREATE TABLE asistencias (id INTEGER PRIMARY KEY AUTOINCREMENT,'+','.join(c+' TEXT' for c in basic)+')')
    markcols=['empresa_id','empleado_id','asistencia_id','fecha','hora','accion','metodo','tipo_marca','lat','lon','foto','gps_ok','gps_distancia_m','gps_tolerancia_m','gps_ref_lat','gps_ref_lon','estado','observaciones','fecha_creacion']
    db.execute('CREATE TABLE asistencia_marcas (id INTEGER PRIMARY KEY AUTOINCREMENT,corregida_manualmente INTEGER DEFAULT 0,'+','.join(c+' TEXT' for c in markcols)+')')
    db.executescript('''CREATE TABLE asistencia_correcciones(id INTEGER PRIMARY KEY,asistencia_id INTEGER,usuario_id INTEGER,accion TEXT,antes TEXT,despues TEXT);
      CREATE TABLE empleados(id INTEGER PRIMARY KEY,empresa_id INTEGER,legajo TEXT,nombre TEXT,apellido TEXT,dni TEXT,sucursal_id INTEGER,sector_id INTEGER,activo INTEGER,estado TEXT);
      CREATE TABLE empresas(id INTEGER PRIMARY KEY,razon_social TEXT);
      CREATE TABLE sucursales(id INTEGER PRIMARY KEY,nombre TEXT);
      CREATE TABLE sectores(id INTEGER PRIMARY KEY,nombre TEXT);
      INSERT INTO empleados VALUES(10,1,'10','Ana','Perez','10',1,1,1,'activo');
      INSERT INTO empresas VALUES(1,'Empresa');
      INSERT INTO sucursales VALUES(1,'Central');
      INSERT INTO sectores VALUES(1,'Almacen');''')
    view=(Path(__file__).parents[1]/'migrations/20260920_03_asistencia_reportes.sql').read_text(encoding='utf-8').replace('CREATE OR REPLACE VIEW','CREATE VIEW')
    db.executescript(view)
    failure={'audit':False}
    class Cursor:
        def __init__(self,dictionary=False): self.dictionary=dictionary
        def execute(self,sql,args=()):
            if failure['audit'] and 'INSERT INTO asistencia_correcciones' in sql: raise RuntimeError('audit failed')
            sql=sql.replace('%s','?').replace(' FOR UPDATE','')
            self.c=db.execute(sql,args);self.lastrowid=self.c.lastrowid;self.rowcount=self.c.rowcount
        def fetchone(self):
            r=self.c.fetchone();return (dict(r) if self.dictionary else tuple(r)) if r else None
        def fetchall(self):return [dict(r) if self.dictionary else tuple(r) for r in self.c.fetchall()]
        def close(self):pass
    class Connection:
        def cursor(self,**kw):return Cursor(**kw)
        def commit(self):db.commit()
        def rollback(self):db.rollback()
        def close(self):pass
    for module in [service,summaries,marks]:monkeypatch.setattr(module,'get_db',Connection)
    monkeypatch.setattr(rules,'get_horario_esperado',lambda *a:{'bloques':[{'entrada':'08:00','salida':'17:00'}],'tolerancia':5})
    yield db,failure
    db.close()


def payload(**kw):
    return {'empresa_id':1,'empleado_id':10,'fecha':'2026-09-18','hora_entrada':'08:00','hora_salida':'17:00',**kw}


def test_manual_create_and_report_consistency(attendance_db):
    db,_=attendance_db
    aid=service.save_manual(payload(),actor=99)
    assert summaries.get_by_id(aid)['estado']=='ok'
    rows=marks.get_for_export_admin(empleado_id=10)
    assert len(rows)==2
    assert all(r['metodo']=='manual' for r in rows)
    assert len(marks.get_page_by_empleado(10,1,20)[0])==2
    assert db.execute('SELECT COUNT(*) FROM asistencia_correcciones').fetchone()[0]==1


def test_manual_edit_recalculates_state_and_keeps_mark_id(attendance_db):
    db,_=attendance_db
    aid=service.save_manual(payload(hora_entrada='09:00'))
    row=marks.get_for_export_admin(accion='ingreso')[0]
    assert summaries.get_by_id(aid)['estado']=='tarde'
    service.change_mark(marca_id=row['id'],hora='08:00',accion='ingreso',actor=99)
    assert summaries.get_by_id(aid)['estado']=='ok'
    now=marks.get_for_export_admin(accion='ingreso')[0]
    assert now['id']==row['id'] and now['corregida_manualmente']==1
    audit=json.loads(db.execute('SELECT antes FROM asistencia_correcciones ORDER BY id DESC LIMIT 1').fetchone()[0])
    assert audit['resumen']['hora_entrada']=='09:00'


def test_summary_edit_synchronizes_and_complex_rejected(attendance_db):
    db,_=attendance_db
    aid=service.save_manual(payload())
    service.save_manual(payload(hora_entrada='09:00'),asistencia_id=aid)
    assert marks.get_for_export_admin(accion='ingreso')[0]['hora']=='09:00'
    service.change_mark(asistencia_id=aid,action='crear',accion='ingreso',hora='10:00')
    with pytest.raises(ValueError,match='varias marcas'):
        service.save_manual(payload(hora_entrada='08:00'),asistencia_id=aid)
    assert summaries.get_by_id(aid)['hora_entrada']=='09:00'


def test_failure_rolls_back_summary_marks_and_audit(attendance_db):
    db,fail=attendance_db
    aid=service.save_manual(payload())
    fail['audit']=True
    with pytest.raises(RuntimeError):service.save_manual(payload(hora_entrada='09:00'),asistencia_id=aid)
    assert summaries.get_by_id(aid)['hora_entrada']=='08:00'
    assert marks.get_for_export_admin(accion='ingreso')[0]['hora']=='08:00'
    with pytest.raises(RuntimeError):service.delete_manual(aid)
    assert summaries.get_by_id(aid)
    assert len(marks.get_for_export_admin())==2


def test_legacy_summary_is_visible_without_writes_or_duplicates(attendance_db):
    db,_=attendance_db
    aid=summaries.create(payload(estado='ok'))
    rows=marks.get_for_export_admin()
    assert len(rows)==2 and all(r['es_resumen']==1 and r['id'] is None for r in rows)
    assert db.execute('SELECT COUNT(*) FROM asistencia_marcas').fetchone()[0]==0
    service.save_manual(payload(),asistencia_id=aid)
    rows=marks.get_for_export_admin()
    assert len(rows)==2 and all(r['es_resumen']==0 for r in rows)


def test_add_to_legacy_absence_and_delete_recalculate(attendance_db):
    db,_=attendance_db
    aid=summaries.create(payload(hora_entrada=None,hora_salida=None,estado='ausente'))
    mid=service.change_mark(asistencia_id=aid,action='crear',accion='ingreso',hora='08:00')
    assert summaries.get_by_id(aid)['estado']=='ok'
    service.change_mark(marca_id=mid,action='eliminar')
    assert summaries.get_by_id(aid)['estado']=='ausente'
    service.delete_manual(aid)
    assert summaries.get_by_id(aid) is None
    assert not marks.get_for_export_admin()


def test_add_to_legacy_preserves_other_endpoint(attendance_db):
    db,_=attendance_db
    aid=summaries.create(payload(hora_salida=None,estado='ok'))
    service.change_mark(asistencia_id=aid,action='crear',accion='egreso',hora='17:00')
    assert summaries.get_by_id(aid)['hora_entrada']=='08:00'
    assert len(marks.get_for_export_admin())==2

def test_duplicate_manual_day_is_rejected(attendance_db):
    db,_=attendance_db
    service.save_manual(payload())
    with pytest.raises(ValueError):service.save_manual(payload())
    assert db.execute('SELECT COUNT(*) FROM asistencias').fetchone()[0]==1


def test_report_has_no_implicit_20000_row_cutoff(attendance_db):
    db,_=attendance_db
    db.executemany("INSERT INTO asistencia_marcas(empresa_id,empleado_id,fecha,hora,accion,metodo,tipo_marca) VALUES(1,10,'2026-09-18','08:00','ingreso','manual','jornada')",[()]*20001)
    db.commit()
    assert len(marks.get_for_export_admin())==20001
    assert len(marks.get_for_export_admin(limit=10))==10


def test_monthly_report_reflects_manual_hours(attendance_db):
    from services.asistencia_monthly_report_service import build_monthly_attendance_report
    db,_=attendance_db
    aid=service.save_manual(payload())
    employees=[{'id':10,'activo':1,'nombre':'Ana','apellido':'Perez'}]
    before=build_monthly_attendance_report(year=2026,month=9,empleados=employees,marcas=marks.get_for_export_admin(),justificaciones=[])
    service.save_manual(payload(hora_salida='16:00'),asistencia_id=aid)
    after=build_monthly_attendance_report(year=2026,month=9,empleados=employees,marcas=marks.get_for_export_admin(),justificaciones=[])
    assert before['kpis']['horas_trabajadas']==9
    assert after['kpis']['horas_trabajadas']==8
    assert summaries.get_by_id(aid)['estado']=='salida_anticipada'
    assert marks.get_for_export_admin(accion='egreso')[0]['hora']=='16:00'
