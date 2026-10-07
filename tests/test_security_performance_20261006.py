import io
import pytest
from flask import Flask, session
from werkzeug.datastructures import FileStorage
import app as app_module
import routes.media_routes as media
import web.auth.decorators as auth
from services import profile_photo_service as photos
from scripts.migrate_20261006_01_panel_performance import covering_index


def test_missing_web_account_denied_and_cached_only_for_request(monkeypatch):
    app=Flask(__name__)
    calls=[]
    monkeypatch.setattr(auth,'get_web_user_by_id',lambda uid:calls.append(uid))
    with app.test_request_context('/'):
        assert not auth.has_role(8,'admin')
        assert not auth.has_role(8,'rrhh')
    with app.test_request_context('/'):
        assert not auth.has_role(8,'admin')
    assert calls==[8,8]


@pytest.mark.parametrize('endpoint,loader',[
    ('/media/legajos/adjunto/10','get_adjunto_by_id'),
    ('/media/feedback/evidencias/10','get_feedback_by_id'),
])
def test_private_media_rejects_other_company_before_loading_bytes(monkeypatch,endpoint,loader):
    app=Flask(__name__);app.secret_key='test';app.register_blueprint(media.media_bp)
    monkeypatch.setattr(media,'can_access_module',lambda *args:True)
    monkeypatch.setattr(media,'_cached_web_user',lambda uid:dict(id=uid,activo=1,rol='rrhh',empresa_id=1))
    monkeypatch.setattr(media,loader,lambda rid:dict(empresa_id=2,evento_empresa_id=2,evidencia_path='private',estado='activo',evento_estado='vigente'))
    def fail(*args): raise AssertionError('Must authorize before reading files')
    monkeypatch.setattr(media,'get_adjunto_data_by_id',fail)
    monkeypatch.setattr(media,'resolve_feedback_evidencia_path',fail)
    client=app.test_client()
    with client.session_transaction() as sess:sess['user_id']=8
    assert client.get(endpoint).status_code==404
    monkeypatch.setattr(media,'can_access_module',lambda *args:False)
    assert client.get(endpoint).status_code==403


def test_headers_limits_and_api_errors(monkeypatch):
    monkeypatch.setattr(app_module,'init_db',lambda:None)
    monkeypatch.setattr(app_module,'_check_jwt_secret_integrity',lambda app:None)
    monkeypatch.setenv('MAX_REQUEST_BYTES','1024')
    app=app_module.create_app();app.config['WTF_CSRF_ENABLED']=False
    @app.route('/test-private',methods=['GET','POST'])
    def private():
        if app_module.request.method=='POST': app_module.request.get_data()
        return 'ok'
    client=app.test_client()
    with client.session_transaction() as sess:sess['user_id']=8
    response=client.get('/test-private')
    assert response.headers['Cache-Control']=='private, no-store'
    assert "object-src 'none'" in response.headers['Content-Security-Policy']
    assert client.post('/test-private',data=b'x'*1025).status_code==413
    response=client.post('/api/v1/mobile/seguridad/eventos',data=b'x'* (27*1024*1024+1))
    # Authentication can reject before the body is parsed, but errors stay JSON.
    assert response.status_code in (401,413)
    assert response.is_json


def test_profile_upload_reads_only_limit_plus_one(monkeypatch):
    monkeypatch.setenv('FOTO_MAX_BYTES','65536')
    monkeypatch.setenv('FOTO_INPUT_MAX_BYTES','65536')
    stream=io.BytesIO(b'x'*100000)
    sizes=[]
    class Upload:
        def read(self,size):
            sizes.append(size)
            return stream.read(size)
    with pytest.raises(ValueError,match='maximo permitido'):
        photos.upload_profile_photo(Upload(),'123')
    assert sizes==[65537]


def test_covering_index_rejects_prefix_and_invisible_indexes():
    row=dict(Key_name='ix',Seq_in_index=1,Column_name='empresa_id',Sub_part=None)
    assert covering_index([row],('empresa_id',))=='ix'
    assert covering_index([{**row,'Visible':'NO'}],('empresa_id',)) is None
    assert covering_index([{**row,'Sub_part':4}],('empresa_id',)) is None


def test_tokens_require_expiration_and_mobile_rejects_qr_or_invalid_id(monkeypatch):
    import jwt
    from utils import jwt as tokens, jwt_guard
    with pytest.raises(tokens.TokenValidationError):
        tokens.verificar_token(jwt.encode({'user_id':8},tokens._get_secret(),algorithm='HS256'))
    app=Flask(__name__)
    @app.get('/private')
    @jwt_guard.mobile_auth_required
    def private():return 'ok'
    client=app.test_client()
    for payload in ({'user_id':'bad'},{'user_id':-1},{'user_id':True},{'user_id':8,'type':'asistencia_qr'}):
        monkeypatch.setattr(jwt_guard,'verificar_token',lambda token,p=payload:p)
        assert client.get('/private',headers={'Authorization':'Bearer signed'}).status_code==401


@pytest.mark.parametrize('read_only,commits',[(True,0),(False,1)])
def test_read_transactions_avoid_commit_and_return_connection(monkeypatch,read_only,commits):
    from repositories import carga_repository as repo
    calls=[]
    class Cursor:
        def close(self):calls.append('cursor_close')
    class Connection:
        def cursor(self,**kwargs):return Cursor()
        def commit(self):calls.append('commit')
        def rollback(self):calls.append('rollback')
        def close(self):calls.append('pool_reset')
    monkeypatch.setattr(repo,'get_db',Connection)
    with repo.transaction(read_only=read_only):pass
    assert calls.count('commit')==commits
    assert calls[-2:]==['cursor_close','pool_reset']
