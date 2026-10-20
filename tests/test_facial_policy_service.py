import pytest

from services.facial_policy_service import (
    FacialPolicyError,
    PolicyScope,
    require_activation_available,
    resolve_policy,
    validate_override,
)

SUBJECT = PolicyScope(1, 2, 3)


def test_default_does_not_enable_capture():
    policy = resolve_policy(subject=SUBJECT)
    assert policy["requested"]["mode"] == "disabled"
    assert policy["effective_mode"] == "disabled"
    assert policy["capture_enabled"] is False
    assert set(policy["origins"].values()) == {"default"}


def test_field_inheritance_and_explicit_disable():
    policy = resolve_policy(
        subject=SUBJECT,
        company=(PolicyScope(1), {"mode": "required", "max_attempts": 4}),
        branch=(PolicyScope(1, 2), {"mode": "trial", "timeout_seconds": 40}),
        employee=(SUBJECT, {"mode": "disabled", "max_attempts": None}),
    )
    assert policy["requested"]["mode"] == "disabled"
    assert policy["requested"]["max_attempts"] == 4
    assert policy["requested"]["timeout_seconds"] == 40
    assert policy["origins"]["mode"] == "employee"
    assert policy["origins"]["max_attempts"] == "company"


@pytest.mark.parametrize("mode", ["trial", "required", "risk"])
def test_draft_never_activates_even_at_employee_level(mode):
    policy = resolve_policy(subject=SUBJECT, employee=(SUBJECT, {"mode": mode}))
    assert policy["requested"]["mode"] == mode
    assert policy["effective_mode"] == "disabled"
    assert policy["activation_available"] is False
    with pytest.raises(FacialPolicyError):
        require_activation_available(mode)


@pytest.mark.parametrize("level,scope", [
    ("company", PolicyScope(9)),
    ("company", PolicyScope(1, 2)),
    ("branch", PolicyScope(9, 2)),
    ("branch", PolicyScope(1, 8)),
    ("employee", PolicyScope(1, 2, 4)),
    ("employee", PolicyScope(9, 2, 3)),
])
def test_wrong_scope_is_rejected(level, scope):
    with pytest.raises(FacialPolicyError):
        resolve_policy(subject=SUBJECT, **{level: (scope, {"mode": "disabled"})})


@pytest.mark.parametrize("values", [
    {"mode": "yes"}, {"mode": []}, {"max_attempts": True},
    {"max_attempts": 0}, {"max_attempts": 6}, {"max_attempts": "3"},
    {"timeout_seconds": 9}, {"timeout_seconds": 121},
    {"on_entry": 1}, {"on_exit": "false"}, {"provider_validated": True},
    {"capture_enabled": True}, [],
])
def test_invalid_values_cannot_relax_safety(values):
    with pytest.raises(FacialPolicyError):
        validate_override(values)


def test_no_branch_and_no_shared_mutation():
    subject = PolicyScope(1, None, 3)
    first = resolve_policy(subject=subject)
    first["requested"]["mode"] = "required"
    assert resolve_policy(subject=subject)["requested"]["mode"] == "disabled"
    with pytest.raises(FacialPolicyError):
        resolve_policy(subject=subject, branch=(PolicyScope(1), {}))
    require_activation_available("disabled")


@pytest.mark.parametrize("subject", [PolicyScope(True, 2, 3), PolicyScope(1, 0, 3), PolicyScope(1)])
def test_invalid_subject(subject):
    with pytest.raises(FacialPolicyError):
        resolve_policy(subject=subject)
