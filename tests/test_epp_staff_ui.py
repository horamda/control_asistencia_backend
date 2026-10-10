from contextlib import contextmanager
from pathlib import Path

import pytest
from jinja2 import Environment, FileSystemLoader
from services import epp_service as service


@pytest.mark.parametrize('actor,scope,value', [
    ({'mode': 'web', 'global': True}, None, None),
    ({'mode': 'web', 'global': False, 'empleado_id': 11}, 'e.reporta_a_empleado_id=%s', 11),
    ({'mode': 'web', 'global': False}, 'e.reporta_a_empleado_id=%s', -1),
    ({'mode': 'empleado', 'empleado_id': 10}, 'e.id=%s', 10),
])
def test_staff_sizes_scope_and_grouping(monkeypatch, actor, scope, value):
    calls = []
    @contextmanager
    def transaction(**kwargs):
        assert kwargs['read_only']
        yield object()
    def rows(cursor, sql, args):
        calls.append((sql, args))
        base = dict(id=10, legajo='10', nombre='Ana', apellido='Perez', articulo_id=1, articulo='Buzo', talle='M', medidas='')
        return [base, dict(base, articulo_id=2, articulo='Botas', talle='38'), dict(base, id=11, articulo_id=None, articulo=None, talle=None)]
    monkeypatch.setattr(service.db, 'transaction', transaction)
    monkeypatch.setattr(service.db, 'all_rows', rows)
    result = service.staff_sizes(dict(actor, empresa_id=7), "O'Connor")
    sql, args = calls[0]
    assert 'e.empresa_id=%s' in sql and args[0] == 7
    assert 't.empresa_id=e.empresa_id' in sql and 'a.empresa_id=e.empresa_id' in sql
    assert "O'Connor" not in sql and args[-1] == "%O'Connor%"
    if scope:
        assert scope in sql and args[1] == value
    else:
        assert 'e.reporta_a_empleado_id=%s' not in sql
    assert len(result) == 2 and len(result[0]['talles']) == 2
    assert result[1]['talles'] == []


@pytest.mark.parametrize('modules', [set(), {'epp'}, {'seguridad_higiene'}, {'epp', 'seguridad_higiene'}])
def test_grouped_safety_navigation_permissions(modules):
    root = Path(__file__).resolve().parents[1]
    source = (root / 'templates/base.html').read_text(encoding='utf-8')
    start = source.index("{% if can_web('seguridad_higiene') or can_web('epp') %}")
    end = source.index('</nav>', start)
    env = Environment()
    html = env.from_string(source[start:end]).render(can_web=lambda module, *args: module in modules, url_for=lambda endpoint: '/' + endpoint)
    assert ('Seguridad e Higiene' in html) == bool(modules)
    assert ('href="/epp/"' in html) == ('epp' in modules)
    assert ('seguridad_web.index' in html) == ('seguridad_higiene' in modules)
    assert 'nav-submenu-epp' not in html


def test_sizes_list_empty_and_individual_views():
    root = Path(__file__).resolve().parents[1]
    env = Environment(loader=FileSystemLoader(root / 'templates'))
    for name in ['base.html', 'epp/sizes.html']:
        env.parse((root / 'templates' / name).read_text(encoding='utf-8'))
    from jinja2 import DictLoader, ChoiceLoader
    env.loader = ChoiceLoader([DictLoader({'epp/layout.html': '{% block epp_content %}{% endblock %}'}), env.loader])
    env.globals.update(url_for=lambda endpoint, **kwargs: '/sizes', csrf_token=lambda: 'csrf')
    template = env.get_template('epp/sizes.html')
    context = dict(search='', items=[], sizes=[], options={'empleados': []})
    html = template.render(eid=None, staff=[dict(id=1, nombre='Ana', apellido='Perez', legajo='1', talles=[])], **context)
    assert 'Ana' in html and 'Sin talles registrados' in html and 'Cargar talles' in html
    assert 'No hay empleados activos' in template.render(eid=None, staff=[], **context)
    assert 'Ver todos los empleados' in template.render(eid=1, staff=[], **context)
