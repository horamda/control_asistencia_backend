from datetime import date
from pathlib import Path
import pytest
from services import seguridad_service as s,seguridad_dashboard_service as dashboard
from tests.test_seguridad import database,client,payload


@pytest.fixture(autouse=True)
def config_table(database):
    with s.db.transaction() as c:
        sql=(Path(__file__).resolve().parents[1]/'migrations/20261005_02_seguridad_dashboard.sql').read_text()
        c.execute(sql)


def approved(**kwargs):
    eid,_=s.create(1,payload(**kwargs),user=99)
    s.review(1,eid,99,'aprobado',1,'')
    return eid


def test_events_not_multiplied_and_external_separate(client):
    approved(externos=[{'nombre':'Visitante'}])
    s.create(1,payload(),user=99)
    result=dashboard.build(1,dict(desde='2026-09-01',hasta='2026-09-30',vista='seguro'))
    assert result['total']==1 and result['counts']['seguro']==1
    assert sum(n for _,n in result['categories'])==1
    assert result['job_total']==2
    assert len(result['ranking'])==2 and len(result['external_ranking'])==1
    assert result['streak']['actual'] is None
    assert result['months']['2026-09']['seguro']==1
    for view in ('seguro','inseguro','indicadores','resumen'):
        response=client.get('/seguridad-higiene/dashboard?vista='+view)
        assert response.status_code==200,response.data[:1000]
    assert client.get('/seguridad-higiene/dashboard?desde=2026-10-02&hasta=2026-01-01').status_code==400


def test_scoped_snapshot_and_empty_months(database):
    approved(involucrados=[10,12])
    approved(involucrados=[],externos=[{'nombre':'Otra persona'}])
    result=dashboard.build(1,dict(desde='2026-08-01',hasta='2026-10-02',vista='seguro',sucursal_id='1'))
    assert result['total']==1 and result['job_total']==1
    assert result['external_ranking']==[] and len(result['ranking'])==1
    assert result['months']['2026-08']['seguro']==0
    assert result['months']['2026-10']['seguro']==0
    assert dashboard.build(2,dict(desde='2026-08-01',hasta='2026-10-02'))['total']==0


def test_streaks_reconcile_and_ignore_incidents(database):
    dashboard.save_configuration(1,99,'2026-09-01')
    for day in ['2026-09-05','2026-09-10']:
        approved(tipo='accidente',fecha_evento=day,hora_evento='10:00',lugar='Deposito',categoria_id=None)
    approved(tipo='incidente',fecha_evento='2026-09-14',hora_evento='10:00',lugar='Deposito',categoria_id=None)
    result=dashboard.build(1,dict(desde='2026-09-12',hasta='2026-09-15',vista='indicadores'))
    assert result['counts']['accidente']==0 and result['counts']['incidente']==1
    assert result['streak']==dict(actual=5,record=5,ultimo=date(2026,9,10))
    assert dashboard.streaks([date(2026,9,5),date(2026,9,10)],date(2026,9,1),date(2026,9,10))['record']==4
    assert dashboard.streaks([],date(2026,9,1),date(2026,9,15))['actual']==14


def test_configuration_permissions_and_future(client,monkeypatch):
    import web.auth.decorators as auth
    assert client.post('/seguridad-higiene/dashboard/configuracion',data={'inicio':'2026-10-03'}).status_code==400
    assert dashboard.configuration(1) is None
    monkeypatch.setattr(auth,'can_access_module',lambda uid,module,action='ver':action=='ver')
    assert client.post('/seguridad-higiene/dashboard/configuracion',data={'inicio':'2024-01-01'}).status_code==403


def test_combined_filters_and_export_match_one_participant(client):
    with s.db.transaction() as c:
        c.execute("INSERT INTO sectores VALUES(2,'Internos')")
        c.execute('UPDATE empleados SET sector_id=2 WHERE id=12')
    approved(involucrados=[10,12],descripcion='Evento con dos sucursales')
    filters=dict(desde='2026-09-01',hasta='2026-09-30',sucursal_id='1',sector_id='2')
    assert dashboard.build(1,filters)['total']==0
    assert s.history(1,filters)['total']==0
    response=client.get('/seguridad-higiene/exportar',query_string=filters)
    assert 'Evento con dos sucursales' not in response.get_data(as_text=True)


def test_annual_series_full_months_scopes_cutoff_and_grain(client):
    approved(fecha_evento='2024-02-15',involucrados=[10,11])
    approved(fecha_evento='2026-02-15',involucrados=[10])
    approved(fecha_evento='2026-09-15',involucrados=[10])
    approved(fecha_evento='2025-03-01',involucrados=[12])
    result=dashboard.build(1,dict(desde='2026-09-01',hasta='2026-09-10',vista='seguro',sucursal_id='1'))
    assert result['total']==0
    assert result['years']==[2024,2025,2026]
    assert result['annual']['seguro'][2024][1]==1
    assert result['annual']['seguro'][2025]==[0]*12
    assert result['annual']['seguro'][2026]==[0,1,0,0,0,0,0,0,0,None,None,None]
    assert all(len(values)==12 for series in result['annual'].values() for values in series.values())
    text=client.get('/seguridad-higiene/dashboard?vista=seguro').get_data(as_text=True)
    assert 'Enero' in text and 'Diciembre' in text and '2024' in text


def test_page_details_are_bounded_and_totals_keep_all_events(database,monkeypatch):
    ids=[approved(descripcion=f'Reporte {n}') for n in range(32)]
    reads=[]
    original=s.db.all_rows
    def capture(c,sql,args=()):
        rows=original(c,sql,args)
        if 'e.descripcion' in sql: reads.append(len(rows))
        return rows
    monkeypatch.setattr(s.db,'all_rows',capture)
    filters=dict(desde='2026-09-01',hasta='2026-09-30',vista='seguro',page='2')
    result=dashboard.build(1,filters)
    assert result['visible_total']==32 and result['counts']['seguro']==32
    assert [r['id'] for r in result['items']]==list(reversed(ids[:2]))
    assert all('descripcion' in r and r['fotos']==0 and len(r['personas'])==2 for r in result['items'])
    assert reads==[2]
