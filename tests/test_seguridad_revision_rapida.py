"""Seguridad e Higiene: aprobar o rechazar desde el listado, sin entrar al detalle, y aprobar varios de una vez."""
import web.auth.decorators as auth

from services import seguridad_service as s
from tests.test_seguridad import client, database, employee, payload  # noqa: F401  (fixtures)

LISTADO = '/seguridad-higiene/?empresa_id=1&estado=pendiente'


def _estado(eid):
    with s.db.transaction() as c:
        return s.db.one(c, 'SELECT estado, motivo, revision FROM sh_eventos WHERE id=%s', (eid,))


def test_listado_muestra_revision_rapida_solo_en_pendientes(client):  # noqa: F811
    pendiente, _ = s.create(1, payload(), reporter=employee())
    aprobado, _ = s.create(1, payload(), reporter=employee())
    s.review(1, aprobado, 99, 'aprobado', 1, '')
    html = client.get('/seguridad-higiene/?empresa_id=1').get_data(as_text=True)
    assert '1</strong> reporte esperando revisión' in html and 'estado=pendiente' in html
    assert f'value="{pendiente}:1" form="sh-aprobar-varios"' in html
    assert f'value="{aprobado}:' not in html  # el aprobado no se puede marcar
    assert html.count('value="aprobado" class="btn">Aprobar</button>') == 1
    assert html.count('Confirmar rechazo') == 1
    assert 'name="volver" value="/seguridad-higiene/?empresa_id=1"' in html


def test_aprobar_y_rechazar_desde_el_listado_vuelve_al_listado(client):  # noqa: F811
    a, _ = s.create(1, payload(), reporter=employee())
    b, _ = s.create(1, payload(), reporter=employee())
    r = client.post(f'/seguridad-higiene/eventos/{a}/revisar', data=dict(estado='aprobado', revision=1, volver=LISTADO))
    assert r.status_code == 302 and r.headers['Location'].endswith(LISTADO)
    assert _estado(a)['estado'] == 'aprobado'
    r = client.post(f'/seguridad-higiene/eventos/{b}/revisar',
                    data=dict(estado='rechazado', revision=1, motivo='Falta la foto', volver=LISTADO))
    assert r.headers['Location'].endswith(LISTADO)
    assert _estado(b)['estado'] == 'rechazado' and _estado(b)['motivo'] == 'Falta la foto'
    with client.session_transaction() as sess:
        mensajes = [m for _, m in sess.get('_flashes', [])]
    assert f'Reporte #{a} aprobado.' in mensajes and f'Reporte #{b} rechazado.' in mensajes


def test_conflicto_desde_el_listado_avisa_sin_pantalla_de_error(client):  # noqa: F811
    a, _ = s.create(1, payload(), reporter=employee())
    s.review(1, a, 99, 'aprobado', 1, '')
    r = client.post(f'/seguridad-higiene/eventos/{a}/revisar', data=dict(estado='rechazado', revision=1, motivo='x',
                                                                         volver=LISTADO))
    assert r.status_code == 302 and r.headers['Location'].endswith(LISTADO)
    # Rechazar sin motivo tampoco cambia nada.
    b, _ = s.create(1, payload(), reporter=employee())
    client.post(f'/seguridad-higiene/eventos/{b}/revisar', data=dict(estado='rechazado', revision=1, volver=LISTADO))
    assert _estado(b)['estado'] == 'pendiente'


def test_volver_solo_acepta_el_listado(client):  # noqa: F811
    a, _ = s.create(1, payload(), reporter=employee())
    r = client.post(f'/seguridad-higiene/eventos/{a}/revisar',
                    data=dict(estado='aprobado', revision=1, volver='https://otro.sitio/'))
    assert r.headers['Location'].startswith(f'/seguridad-higiene/eventos/{a}')  # al detalle, como siempre


def test_aprobar_varios(client):  # noqa: F811
    a, _ = s.create(1, payload(), reporter=employee())
    b, _ = s.create(1, payload(), reporter=employee())
    c, _ = s.create(1, payload(), reporter=employee())
    s.review(1, c, 99, 'aprobado', 1, '')  # ya revisado: no se vuelve a aprobar
    r = client.post('/seguridad-higiene/eventos/aprobar-varios',
                    data=dict(eventos=[f'{a}:1', f'{b}:1', f'{c}:1', 'basura'], volver=LISTADO))
    assert r.status_code == 302 and r.headers['Location'].endswith(LISTADO)
    assert _estado(a)['estado'] == _estado(b)['estado'] == 'aprobado'
    with client.session_transaction() as sess:
        mensajes = [m for _, m in sess.get('_flashes', [])]
    assert '2 reportes aprobados.' in mensajes
    assert any(f'#{c}' in m and '#basura' in m for m in mensajes)


def test_aprobar_varios_requiere_permiso(client, monkeypatch):  # noqa: F811
    a, _ = s.create(1, payload(), reporter=employee())
    monkeypatch.setattr(auth, 'can_access_module', lambda uid, module, action='ver': action == 'ver')
    assert client.post('/seguridad-higiene/eventos/aprobar-varios', data=dict(eventos=[f'{a}:1'])).status_code == 403
    assert _estado(a)['estado'] == 'pendiente'
