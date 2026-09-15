WEB_MODULES = [
    {"code": "organizacion", "label": "Organizacion", "group": "General", "roles": {"admin", "rrhh", "supervisor"}},
    {"code": "empresas", "label": "Empresas", "group": "Organizacion", "roles": {"admin"}},
    {"code": "sucursales", "label": "Sucursales", "group": "Organizacion", "roles": {"admin"}},
    {"code": "sectores", "label": "Sectores", "group": "Organizacion", "roles": {"admin"}},
    {"code": "puestos", "label": "Puestos", "group": "Organizacion", "roles": {"admin"}},
    {"code": "localidades", "label": "Localidades", "group": "Organizacion", "roles": {"admin"}},
    {"code": "empleados", "label": "Directorio de empleados", "group": "Capital Humano", "roles": {"admin", "rrhh", "supervisor"}},
    {"code": "legajos", "label": "Legajos", "group": "Capital Humano", "roles": {"admin", "rrhh", "supervisor", "jefe"}},
    {"code": "usuarios", "label": "Usuarios panel", "group": "Seguridad", "roles": {"admin"}},
    {"code": "roles_empleados", "label": "Roles empleados", "group": "Seguridad", "roles": {"admin"}},
    {"code": "horarios", "label": "Horarios", "group": "Horarios", "roles": {"admin", "rrhh"}},
    {"code": "asistencias", "label": "Asistencias", "group": "Asistencia", "roles": {"admin", "rrhh", "supervisor"}},
    {"code": "justificaciones", "label": "Justificaciones", "group": "Asistencia", "roles": {"admin", "rrhh", "supervisor"}},
    {"code": "qr_puerta", "label": "QR puerta", "group": "Asistencia", "roles": {"admin", "rrhh"}},
    {"code": "francos", "label": "Francos", "group": "Asistencia", "roles": {"admin", "rrhh"}},
    {"code": "vacaciones", "label": "Vacaciones", "group": "Asistencia", "roles": {"admin", "rrhh"}},
    {"code": "pedidos_empleados", "label": "Pedidos empleados", "group": "Operaciones", "roles": {"admin", "rrhh"}},
    {"code": "feedback", "label": "Feedback", "group": "Gestion", "roles": {"admin", "rrhh"}},
    {"code": "skap", "label": "SKAP", "group": "Gestion", "roles": {"admin", "rrhh", "supervisor"}},
    {"code": "kpis", "label": "KPIs", "group": "Gestion", "roles": {"admin", "rrhh"}},
    {"code": "premios", "label": "Premios", "group": "Gestion", "roles": {"admin", "rrhh"}},
    {"code": "trivias", "label": "Trivias", "group": "Gestion", "roles": {"admin", "rrhh"}},
    {"code": "configuracion", "label": "Configuracion", "group": "Sistema", "roles": {"admin"}},
    {"code": "auditoria", "label": "Auditoria", "group": "Sistema", "roles": {"admin"}},
    {"code": "app_version", "label": "Versiones App", "group": "Sistema", "roles": {"admin"}},
    {"code": "mobile_stats", "label": "Uso de la app", "group": "Sistema", "roles": {"admin"}},
    {"code": "calificaciones_app", "label": "Calificaciones app", "group": "Sistema", "roles": {"admin"}},
]

WEB_MODULES_BY_CODE = {module["code"]: module for module in WEB_MODULES}
PERMISSION_ACTIONS = ("ver", "crear", "editar", "eliminar", "aprobar", "exportar")


def role_default_module_codes(role: str | None) -> set[str]:
    role_norm = str(role or "").strip().lower()
    if role_norm == "admin":
        return set(WEB_MODULES_BY_CODE)
    return {
        module["code"]
        for module in WEB_MODULES
        if role_norm in module["roles"]
    }


def default_permission_payload_for_role(role: str | None) -> dict[str, dict[str, bool]]:
    role_norm = str(role or "").strip().lower()
    allowed_modules = role_default_module_codes(role_norm)
    payload = {}
    for module in WEB_MODULES:
        enabled = module["code"] in allowed_modules
        payload[module["code"]] = {
            action: enabled
            for action in PERMISSION_ACTIONS
        }
    return payload
