import pytest
from pathlib import Path
from services import seguridad_campeon_service as champion,seguridad_service as s
from tests.test_seguridad import database,client,payload

@pytest.fixture(autouse=True)
def schema(database):
    sql=(Path(__file__).resolve().parents[1]/'migrations/20261007_01_seguridad_campeon.sql').read_text()
    with s.db.transaction() as c:
        for statement in sql.split(';'):
            if statement.strip():c.execute(statement)

def report(day,ids,**kwargs):
    eid,_=s.create(1,payload(fecha_evento=day,involucrados=ids,**kwargs),user=99)
    s.review(1,eid,99,'aprobado',1,'')
    return eid

def candidates():
    for day in ('2026-09-01','2026-09-02','2026-09-03'):report(day,[10,11])

def test_defaults_ties_dates_and_all_personnel(client):
    candidates()
    report('2026-09-03',[12]);report('2026-09-03',[12]);report('2026-09-03',[12])
    report('2026-09-04',[],externos=[{'nombre':'Externo'}])
    result=champion.build(1,2026,9)
    first=result['grupos'][0]
    assert {p['id'] for p in first['ganadores']}=={10,11}
    assert all(p['puntaje']==3 for p in first['ganadores'])
    assert any(p['id']==13 and not p['elegible'] for p in first['personas'])
    assert not result['grupos'][1]['ganadores']
    assert all(p['id']!=20 for g in result['grupos'] for p in g['personas'])
    response=client.get('/seguridad-higiene/campeon?anio=2026&mes=9')
    assert response.status_code==200
    assert 'Editar reglas' in response.get_data(as_text=True)

def test_unsafe_exclusion_editable_points_and_revision(database):
    candidates();report('2026-09-04',[10],tipo='inseguro',categoria_id=2,advertido='si')
    assert [p['id'] for p in champion.build(1,2026,9)['grupos'][0]['ganadores']]==[11]
    data={**champion.DEFAULTS,'revision':0,'solo_activos':'1','max_inseguros':1,'puntos_seguro':5,'puntos_inseguro':-2}
    champion.save_rules(1,99,data)
    scores={p['id']:p for p in champion.build(1,2026,9)['grupos'][0]['personas']}
    assert scores[10]['puntaje']==13 and scores[10]['elegible']
    with pytest.raises(s.Error):champion.save_rules(1,99,data)
    with pytest.raises(s.Error):champion.save_rules(1,99,{**data,'revision':1,'puntos_inseguro':2})

def test_confirmation_frozen_snapshot_stale_and_open_period(database):
    candidates();result=champion.build(1,2026,9);g=result['grupos'][0]
    data=dict(anio=2026,mes=9,grupo=g['key'],firma=g['firma'])
    champion.confirm(1,99,data)
    with pytest.raises(s.Error):champion.confirm(1,99,data)
    champion.save_rules(1,99,{**champion.DEFAULTS,'revision':0,'puntos_seguro':10,'solo_activos':'1'})
    updated=champion.build(1,2026,9)
    assert updated['premios'][0]['resultado']['reglas']['puntos_seguro']==1
    assert updated['premios'][0]['resultado']['ganadores'][0]['puntaje']==3
    assert updated['grupos'][0]['ganadores'][0]['puntaje']==30
    with pytest.raises(s.Error):champion.confirm(1,99,{**data,'mes':10})
    with pytest.raises(s.Error):champion.confirm(2,99,data)

def test_permissions_and_stale_result(client,monkeypatch):
    candidates();g=champion.build(1,2026,9)['grupos'][0]
    report('2026-09-04',[10])
    with pytest.raises(s.Error,match='cambió'):champion.confirm(1,99,dict(anio=2026,mes=9,grupo=g['key'],firma=g['firma']))
    import web.auth.decorators as auth
    monkeypatch.setattr(auth,'can_access_module',lambda uid,module,action='ver':action=='ver')
    assert client.post('/seguridad-higiene/campeon/reglas',data={}).status_code==403
    assert client.post('/seguridad-higiene/campeon/confirmar',data={}).status_code==403
