from services.web_permissions_service import default_permission_payload_for_role, role_default_module_codes


def test_admin_role_gets_all_modules():
    modules = role_default_module_codes("admin")

    assert "usuarios" in modules
    assert "asistencias" in modules
    assert "configuracion" in modules


def test_rrhh_role_keeps_historical_modules_without_admin_only():
    modules = role_default_module_codes("rrhh")

    assert "asistencias" in modules
    assert "vacaciones" in modules
    assert "usuarios" not in modules
    assert "configuracion" not in modules


def test_default_permission_payload_enables_all_actions_for_allowed_modules():
    payload = default_permission_payload_for_role("supervisor")

    assert payload["asistencias"]["ver"] is True
    assert payload["asistencias"]["editar"] is True
    assert payload["vacaciones"]["ver"] is False
