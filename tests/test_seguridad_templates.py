"""Render report screens without connecting to the application database."""
from html.parser import HTMLParser
from pathlib import Path
from types import SimpleNamespace

import pytest
from jinja2 import ChoiceLoader, DictLoader, Environment, FileSystemLoader, StrictUndefined


class Markup(HTMLParser):
    def __init__(self, html):
        super().__init__()
        self.stack = []
        self.forms = []
        self.current = None
        self.feed(html)
        assert not self.stack

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag in {'div', 'section', 'aside', 'form', 'details', 'label', 'nav', 'header'}:
            self.stack.append(tag)
        if tag == 'form':
            assert self.current is None, 'Nested forms break submissions'
            self.current = dict(attrs, fields=[])
            self.forms.append(self.current)
        if self.current is not None and tag in {'input', 'select', 'textarea', 'button'}:
            self.current['fields'].append(attrs)

    def handle_endtag(self, tag):
        if tag in {'div', 'section', 'aside', 'form', 'details', 'label', 'nav', 'header'}:
            assert self.stack.pop() == tag
        if tag == 'form':
            self.current = None


def render(name, *, allowed=True, endpoint='detail', **values):
    env = Environment(loader=ChoiceLoader([
        DictLoader({'base.html': '{% block extra_head %}{% endblock %}{% block content %}{% endblock %}{% block extra_scripts %}{% endblock %}'}),
        FileSystemLoader(Path(__file__).resolve().parents[1] / 'templates'),
    ]), autoescape=True, undefined=StrictUndefined)
    env.globals.update(
        url_for=lambda endpoint, **kwargs: '/' + endpoint,
        csrf_token=lambda: 'csrf-test',
        can_web=lambda *args: allowed,
        request=SimpleNamespace(endpoint='seguridad_web.' + endpoint),
    )
    return env.get_template('seguridad/' + name + '.html').render(
        empresa_id=1, tipos={'seguro': 'Comportamiento seguro'}, empleados=[], **values)


def report(**changes):
    return dict(dict(id=318, tipo='seguro', estado='pendiente', revision=4,
                     fecha_evento='2026-10-07', hora_evento=None, categoria_nombre='Uso de EPP',
                     origen='mobile', reportante=None, usuario_id=99, descripcion='<script>no</script>',
                     involucrados=[], externos=[], detalles={}, fotos=[], acciones=[],
                     importacion=None, auditoria=[]), **changes)


@pytest.mark.parametrize('state', ['pendiente', 'aprobado', 'rechazado', 'anulado'])
@pytest.mark.parametrize('allowed', [True, False])
def test_detail_preserves_permission_and_review_forms(state, allowed):
    html = render('detalle', allowed=allowed, row=report(estado=state))
    dom = Markup(html)
    actions = {form['action'] for form in dom.forms}
    assert ('/seguridad_web.review' in actions) == (allowed and state == 'pendiente')
    assert ('/seguridad_web.annul' in actions) == (allowed and state != 'anulado')
    assert '&lt;script&gt;no&lt;/script&gt;' in html
    assert 'aria-current="page"' in html
    for form in dom.forms:
        fields = {f.get('name'): f for f in form['fields']}
        assert fields['csrf_token']['value'] == 'csrf-test'
        assert fields['empresa_id']['value'] == '1'
        if form['action'] in {'/seguridad_web.review', '/seguridad_web.annul'}:
            assert fields['revision']['value'] == '4'
            assert 'motivo' in fields


@pytest.mark.parametrize('editing', [True, False])
def test_form_keeps_single_multipart_submission_and_draft(editing):
    html = render('form', endpoint='edit' if editing else 'create', row=report() if editing else None,
                  error=None, import_row=None, catalogos=[], externos=[], fecha_actual='2026-10-13',
                  data={'tipo': 'seguro', 'descripcion': 'Texto conservado', 'revision': 4,
                        'envio_id': 'submission-id'})
    dom = Markup(html)
    assert len(dom.forms) == 1
    form = dom.forms[0]
    assert form['enctype'] == 'multipart/form-data'
    fields = {f.get('name'): f for f in form['fields']}
    assert fields['envio_id']['value'] == 'submission-id'
    assert fields['revision']['value'] == '4'
    assert 'multiple' in fields['involucrados']
    assert 'multiple' in fields['fotos']
    assert 'Texto conservado' in html
    assert 'value="seguro" selected' in html


def test_existing_action_retains_identity_and_state():
    action = dict(id=17, descripcion='Reponer EPP', responsable_id=9,
                  vencimiento='2026-10-20', estado='en_curso', evidencia='')
    html = render('detalle', row=report(acciones=[action]))
    forms = Markup(html).forms
    existing = next(f for f in forms if any(x.get('name') == 'id' for x in f['fields']))
    assert any(x.get('value') == '17' for x in existing['fields'])
    assert 'value="en_curso" selected' in html


def test_listing_filters_stay_in_one_get_form():
    html = render('listado', endpoint='index', empresas=[], filters={}, externos=[],
                  total=0, page=1, items=[])
    forms = Markup(html).forms
    assert len(forms) == 1 and forms[0]['method'] == 'get'
    assert any(f.get('formaction') == '/seguridad_web.export' for f in forms[0]['fields'])
