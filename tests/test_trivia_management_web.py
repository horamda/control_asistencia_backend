from flask import Flask
from flask_wtf.csrf import CSRFProtect
from jinja2 import ChoiceLoader, DictLoader, FileSystemLoader
from pathlib import Path
import pytest
from web.trivias import trivia_admin_routes as routes
from web.auth import decorators as auth

@pytest.fixture
def management_client(monkeypatch):
    app=Flask(__name__)
    app.config.update(SECRET_KEY='test-only', TESTING=True, WTF_CSRF_ENABLED=False)
    CSRFProtect(app)
    app.jinja_loader=ChoiceLoader([DictLoader({'base.html':'{% block content %}{% endblock %}'}),FileSystemLoader(str(Path(__file__).parents[1]/'templates'))])
    app.register_blueprint(routes.trivia_admin_bp)
    monkeypatch.setattr(auth,'has_role',lambda *a: True)
    monkeypatch.setattr(auth,'_cached_web_user',lambda *a: {'id':99,'rol':'admin','activo':1})
    monkeypatch.setattr(routes.repo,'get_trivia_by_id',lambda tid: {'id':tid,'titulo':'Trivia prueba','anio':2026,'estado':'activa'})
    monkeypatch.setattr(routes.repo,'get_impacto_eliminar_trivia',lambda tid: dict.fromkeys(routes.repo._TRIVIA_CHILDREN,2))
    monkeypatch.setattr(routes.repo,'get_exclusiones_ranking_trivia',lambda tid: [])
    monkeypatch.setattr(routes,'get_empleados',lambda **kw: [])
    client=app.test_client()
    with client.session_transaction() as session: session['user_id']=99
    return client

def test_delete_confirmation_and_post(management_client,monkeypatch):
    calls=[]
    monkeypatch.setattr(routes.repo,'delete_trivia_completa',lambda tid,**kw:calls.append(tid))
    assert management_client.get('/admin/trivias/3/eliminar').status_code==200
    assert not calls
    assert management_client.post('/admin/trivias/3/eliminar',data={'confirmacion':'4'}).status_code==400
    assert not calls
    assert management_client.post('/admin/trivias/3/eliminar',data={'confirmacion':'3'}).status_code==302
    assert calls==[3]

@pytest.mark.parametrize('path',['eliminar','fuera-ranking'])
def test_management_requires_actual_active_manager(management_client,monkeypatch,path):
    monkeypatch.setattr(auth,'_cached_web_user',lambda *a: {'id':99,'rol':'empleado','activo':1})
    assert management_client.post('/admin/trivias/3/'+path).status_code==403

def test_per_trivia_mode_and_restore(management_client,monkeypatch):
    calls=[]
    monkeypatch.setattr(routes.repo,'set_exclusion_ranking_trivia',lambda tid,eid,**kw:calls.append((tid,eid,kw)))
    assert management_client.get('/admin/trivias/3/fuera-ranking').status_code==200
    assert management_client.post('/admin/trivias/3/fuera-ranking',data={'empleado_id':'10','operacion':'invalid'}).status_code==400
    assert not calls
    for operation in ['excluir','incluir']:
        assert management_client.post('/admin/trivias/3/fuera-ranking',data={'empleado_id':'10','operacion':operation}).status_code==302
    assert [c[2]['excluir'] for c in calls]==[True,False]
    assert all(c[:2]==(3,10) for c in calls)

@pytest.mark.parametrize('path',['eliminar','fuera-ranking'])
def test_management_csrf_required(management_client,path):
    management_client.application.config['WTF_CSRF_ENABLED']=True
    assert management_client.post('/admin/trivias/3/'+path).status_code==400
