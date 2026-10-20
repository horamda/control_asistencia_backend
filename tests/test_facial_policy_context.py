import pytest
from services import facial_policy_context as context


def test_legacy_config_does_not_query_branch(monkeypatch):
    monkeypatch.setattr(context, "get_branch", lambda _: pytest.fail("unexpected query"))
    result = context.mobile_policy({"id": 3, "empresa_id": 1, "sucursal_id": 2}, {})
    assert result["effective_mode"] == "disabled"
    assert result["capture_enabled"] is False


def test_stored_hierarchy_and_versions(monkeypatch):
    monkeypatch.setattr(context, "get_branch", lambda _: {
        "empresa_id": 1, "facial_policy_draft": '{"mode":"trial"}', "facial_policy_revision": 4,
    })
    result = context.employee_policy(
        {"id": 3, "empresa_id": 1, "sucursal_id": 2, "facial_policy_draft": "{}"},
        {"facial_policy_draft": '{"mode":"required"}', "facial_policy_revision": 1},
    )
    assert result["requested"]["mode"] == "trial"
    assert result["origins"]["mode"] == "branch"
    assert result["revisions"]["branch"] == 4
    assert result["effective_mode"] == "disabled"


@pytest.mark.parametrize("branch", [None, {"empresa_id": 9, "facial_policy_draft": '{"mode":"required"}'}])
def test_invalid_branch_does_not_leak_policy(monkeypatch, branch):
    monkeypatch.setattr(context, "get_branch", lambda _: branch)
    result = context.mobile_policy(
        {"id": 3, "empresa_id": 1, "sucursal_id": 2}, {"facial_policy_revision": 0})
    assert result["configuration_status"] == "invalid"
    assert "requested" not in result
    assert result["capture_enabled"] is False


@pytest.mark.parametrize("raw", ['{', '[]', '{"capture_enabled":true}', '{"mode":"unknown"}'])
def test_corrupt_draft_is_explicitly_invalid(raw):
    result = context.mobile_policy(
        {"id": 3, "empresa_id": 1}, {"facial_policy_draft": raw})
    assert result["configuration_status"] == "invalid"
    assert result["effective_mode"] == "disabled"


def test_preview_explicit_disable_overrides_company(monkeypatch):
    monkeypatch.setattr(context, "get_by_empresa_id", lambda _: {"facial_policy_draft": '{"mode":"required"}'})
    result = context.form_preview(
        {"empresa_id": 1, "facial_policy_draft": '{"mode":"disabled"}'}, "branch")
    assert result["requested"]["mode"] == "disabled"
    assert result["origins"]["mode"] == "branch"
