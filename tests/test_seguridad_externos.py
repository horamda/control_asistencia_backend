import io
import json
from uuid import uuid4
import pytest
from werkzeug.datastructures import FileStorage
from openpyxl import load_workbook
from services import seguridad_service as s
from services import seguridad_import_service as imp
from services import seguridad_excel_service as excel
from tests.test_seguridad import database, client, employee, payload
from tests.test_seguridad_excel import upload, complete


def test_external_name_only_retry_privacy_history_and_ranking(database):
    data=payload(involucrados=[],externos=[{'nombre':'Visitante'}])
    eid,created=s.create(1,data,reporter=employee())
    assert created and s.create(1,data,reporter=employee())==(eid,False)
    detail=s.detail(1,eid,10)
    assert detail['involucrados']==[] and detail['externos'][0]['nombre']=='Visitante'
    external=detail['externos'][0]['id']
    assert detail['externos'][0]['empresa']==''
    assert s.history(1,employee_id=10,mode='enviados')['total']==1
    assert s.history(1,employee_id=10)['total']==0
    with pytest.raises(s.Error): s.detail(1,eid,11)
    assert s.rankings(1,2026)['rankings_externos']['seguro']==[]
    s.review(1,eid,99,'aprobado',1,'')
    ranks=s.rankings(1,2026)
    assert ranks['rankings']['seguro']==[]
    assert ranks['rankings_externos']['seguro'][0]['cantidad']==1
    assert ranks['eventos']==[{'tipo':'seguro','cantidad':1}]
    assert s.history(1,{'externo_id':external})['total']==1
    with s.db.transaction() as c: assert len(s.external_people(c,1))==1
    next_id,_=s.create(1,payload(involucrados=[11],externos=[{'id':external}]),reporter=employee())
    s.review(1,next_id,99,'aprobado',1,'')
    assert s.detail(1,next_id,11)['externos']==[]
    ranks=s.rankings(1,2026)
    assert ranks['rankings_externos']['seguro'][0]['cantidad']==2
    assert ranks['rankings']['seguro'][0]['cantidad']==1
    assert ranks['eventos']==[{'tipo':'seguro','cantidad':2}]


@pytest.mark.parametrize('externals',[[{'nombre':' '}],[{'nombre':'x'*181}],[{'nombre':'Nombre','empresa':'x'*181}],
    [{'id':999}], [{'nombre':'Ana'},{'nombre':'Ana'}], [{'nombre':'Ana'}]*101,{},'not-json'])
def test_rejects_invalid_external_without_creating_partial_event(database,externals):
    with pytest.raises(s.Error): s.create(1,payload(involucrados=[],externos=externals),reporter=employee())
    assert s.history(1)['total']==0
    with s.db.transaction() as c: assert s.external_people(c,1)==[]


def test_external_tenant_scope_inactive_and_edit(database):
    other=s.save_external(2,99,dict(nombre='Otra empresa'))
    with pytest.raises(s.Error): s.create(1,payload(involucrados=[],externos=[{'id':other}]),reporter=employee())
    person=s.save_external(1,99,dict(nombre='Invitado'))
    eid,_=s.create(1,payload(involucrados=[],externos=[{'id':person}]),reporter=employee())
    s.save_external(1,99,dict(nombre='Invitado',activo='0'),person)
    with pytest.raises(s.Error): s.create(1,payload(involucrados=[],externos=[{'id':person}]),reporter=employee())
    s.edit(1,eid,99,payload(involucrados=[],externos=[{'id':person}],revision=1))
    assert s.detail(1,eid)['externos'][0]['id']==person
    s.edit(1,eid,99,payload(involucrados=[10],revision=2))
    assert s.detail(1,eid)['externos']==[]
    with pytest.raises(s.Error): s.save_external(2,99,dict(nombre='No'),person)


def test_external_only_mobile_and_admin_permissions(client,monkeypatch):
    import web.auth.decorators as auth
    data=payload(involucrados=[],externos=[{'nombre':'Contratista'}])
    response=client.post('/api/v1/mobile/seguridad/eventos',json=data,headers={'Authorization':'Bearer 10'})
    assert response.status_code==201,response.data
    eid=response.json['id']
    assert client.get(f'/seguridad-higiene/eventos/{eid}').status_code==200
    assert client.get(f'/seguridad-higiene/eventos/{eid}/editar').status_code==200
    assert client.get('/seguridad-higiene/externos').status_code==200
    assert client.get('/seguridad-higiene/ranking').status_code==200
    exported=client.get('/seguridad-higiene/exportar').get_data(as_text=True)
    assert 'nombres_externos' in exported and 'Contratista' in exported
    rank=client.get('/api/v1/mobile/seguridad/ranking',headers={'Authorization':'Bearer 10'}).json
    assert set(rank['rankings_externos'])=={'seguro','inseguro'}
    config=client.get('/api/v1/mobile/seguridad/config',headers={'Authorization':'Bearer 10'}).json
    assert config['externos'][0]['nombre']=='Contratista'
    monkeypatch.setattr(auth,'can_access_module',lambda uid,module,action='ver':action=='ver')
    assert client.post('/seguridad-higiene/externos',data={'nombre':'No permitido'}).status_code==403


def test_excel_external_unknown_requires_explicit_classification(database):
    row=complete(Legajos='',**{'Tipo persona':'pendiente','Persona de referencia':'Nombre antiguo'})
    with pytest.raises(imp.ValidationError): imp.stage(1,99,upload([row]))
    row.update({'Tipo persona':'externo','Nombre externo':'Nombre antiguo'})
    bid=imp.stage(1,99,upload([row]))
    assert imp.import_ready(1,bid,99)==(1,0)
    info=s.detail(1,s.history(1)['items'][0]['id'])
    assert info['externos'][0]['nombre']=='Nombre antiguo'
    assert info['involucrados']==[]
    # Re-exporting the historical source retains the original request fingerprint.
    raw=excel.export(1,bid)
    second=imp.stage(1,99,FileStorage(stream=io.BytesIO(raw),filename='corregido.xlsx'))
    assert imp.import_ready(1,second,99)==(0,0)
    assert s.history(1)['total']==1
    with s.db.transaction() as c: assert len(s.external_people(c,1))==1


def test_excel_existing_external_and_mixed_event(database):
    person=s.save_external(1,99,dict(nombre='Registrado'))
    row=complete(**{'Tipo persona':'mixto','IDs externos existentes':str(person)})
    bid=imp.stage(1,99,upload([row]))
    assert imp.import_ready(1,bid,99)==(1,0)
    row=complete(**{'Tipo persona':'externo','Legajos':'','Nombre externo':'','Empresa externa':'Empresa sin nombre'})
    with pytest.raises(imp.ValidationError): imp.stage(1,99,upload([row]))
