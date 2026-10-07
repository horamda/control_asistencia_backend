from services import seguridad_service as s
from tests.test_seguridad import database,client,payload


def test_search_people_legajo_description_and_tenant(client):
    eid,_=s.create(1,payload(),user=99)
    s.create(2,payload(involucrados=[20],categoria_id=3,descripcion='Texto ajeno'),user=99)
    for query in ('0010','Perez','protecci','EPP'):
        assert s.history(1,{'q':query})['total']==1
    assert s.history(1,{'q':'Texto ajeno'})['total']==0
    response=client.get('/seguridad-higiene/?q=0010').get_data(as_text=True)
    assert 'Perez Ana' in response and 'Legajo 0010' in response
    assert f'/eventos/{eid}/editar' in response


def test_external_filter_edit_validation_and_history(client):
    pid=s.save_external(1,99,dict(nombre='Visitante Azul',empresa='Proveedor'))
    s.save_external(2,99,dict(nombre='Persona de otra empresa'))
    s.create(1,payload(involucrados=[],externos=[{'id':pid}]),user=99)
    response=client.get('/seguridad-higiene/externos?q=Proveedor').get_data(as_text=True)
    assert 'Visitante Azul' in response and 'Persona de otra empresa' not in response
    invalid=client.post('/seguridad-higiene/externos',data={'id':pid,'nombre':'','empresa':'Dato conservado','activo':'1'})
    assert 'Dato conservado' in invalid.get_data(as_text=True)
    assert 'role="alert"' in invalid.get_data(as_text=True)
    response=client.post('/seguridad-higiene/externos',data={'id':pid,'nombre':'Visitante Azul','empresa':'Proveedor','activo':'0'})
    assert response.status_code==302
    assert 'Visitante Azul' not in client.get('/seguridad-higiene/externos?estado=1').get_data(as_text=True)
    assert 'Visitante Azul' in client.get('/seguridad-higiene/externos?estado=0').get_data(as_text=True)
    assert s.history(1,{'externo_id':pid})['total']==1


def test_catalog_filters_and_create_type(client):
    text=client.get('/seguridad-higiene/catalogos?tipo=inseguro&q=Falta').get_data(as_text=True)
    assert 'Falta EPP' in text and 'EPP correcto' not in text
    text=client.get('/seguridad-higiene/nuevo?tipo=accidente').get_data(as_text=True)
    assert 'value="accidente" selected' in text
    assert client.get('/seguridad-higiene/externos?estado=invalid').status_code==400


def test_csv_batches_participants_instead_of_querying_each_event(client,monkeypatch):
    for _ in range(5): s.create(1,payload(externos=[{'nombre':'Invitado'}]),user=99)
    original=s.db.all_rows;queries=[]
    def tracked(c,sql,params=()):
        queries.append(sql)
        return original(c,sql,params)
    monkeypatch.setattr(s.db,'all_rows',tracked)
    response=client.get('/seguridad-higiene/exportar')
    assert response.status_code==200
    assert len([q for q in queries if 'FROM sh_involucrados' in q or 'FROM sh_evento_externos' in q])==2
    assert response.get_data(as_text=True).count('Invitado')==5
