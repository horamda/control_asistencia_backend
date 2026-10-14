from pathlib import Path
from contextlib import contextmanager
import pytest
from jinja2 import Environment, FileSystemLoader, ChoiceLoader, DictLoader
from services import epp_service as s


def test_concept_selection_checks_tenant_and_active(monkeypatch):
    calls = []
    def one(c, sql, args):
        calls.append((sql, args))
        return {"nombre": "Desgaste"} if args == (3, 7) else None
    monkeypatch.setattr(s.db, "one", one)
    result = s.order_concept(None, {"empresa_id": 7}, {"concepto_reposicion_id": 3})
    assert result == {"concepto_reposicion_id": 3, "concepto_reposicion": "Desgaste"}
    assert "empresa_id=%s AND activo=1" in calls[0][0]
    with pytest.raises(s.Error):
        s.order_concept(None, {"empresa_id": 8}, {"concepto_reposicion_id": 3})


def test_legacy_edit_preserves_snapshot_and_null_clears(monkeypatch):
    previous = dict(concepto_reposicion_id=3, concepto_reposicion="Original")
    monkeypatch.setattr(s.db, "one", lambda *args: pytest.fail("Must preserve historical snapshot"))
    assert s.order_concept(None, {}, {}, previous) == previous
    assert s.order_concept(None, {}, {"concepto_reposicion_id": 3}, previous) == previous
    assert s.order_concept(None, {}, {"concepto_reposicion_id": None}, previous) == dict(concepto_reposicion_id=None, concepto_reposicion=None)
    assert s.order_concept(None, {}, {}) == dict(concepto_reposicion_id=None, concepto_reposicion=None)


@pytest.mark.parametrize("operation", [lambda: s.save_replacement_concept({}, {"nombre": "Test"}), lambda: s.delete_replacement_concept({}, 1)])
def test_employee_cannot_manage_concepts(operation):
    with pytest.raises(s.Error) as exc:
        operation()
    assert exc.value.status == 403


def test_concept_templates_escape_names_and_keep_inactive_selection():
    root = Path(__file__).resolve().parents[1]
    env = Environment(loader=ChoiceLoader([DictLoader({"epp/layout.html": "{% block epp_content %}{% endblock %}"}), FileSystemLoader(root / "templates")]), autoescape=True)
    env.globals.update(csrf_token=lambda: "token", url_for=lambda *a, **kw: "/test")
    for file in ["layout", "form", "detail", "replacement_concepts"]:
        env.parse((root / "templates/epp" / (file + ".html")).read_text(encoding="utf-8"))
    html = env.get_template("epp/replacement_concepts.html").render(items=[dict(id=1, nombre="<script>", activo=1)])
    assert "&lt;script&gt;" in html and "<script>" not in html
    assert 'name="csrf_token"' in html and 'value="eliminar"' in html
    html = env.get_template("epp/form.html").render(editing=dict(id=1, revision=1, items=[], motivo="Test", concepto_reposicion_id=3, concepto_reposicion="Original"), eid=10, items=[], sizes=[], concepts=[], token="token")
    assert 'value="3" selected' in html and 'Original (inactivo)' in html
