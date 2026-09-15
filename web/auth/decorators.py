from functools import wraps
from flask import request, session, redirect, url_for, abort, g, has_request_context

from repositories.roles_repository import has_any_role
from repositories.usuarios_app_repository import get_by_id as get_web_user_by_id
from repositories.web_permission_repository import get_user_permissions
from services.web_permissions_service import PERMISSION_ACTIONS, role_default_module_codes


def _current_web_user_id():
    return session.get("user_id")


def current_empleado_id():
    """Empleado vinculado al usuario del panel actualmente logueado (o None si no tiene)."""
    empleado_id = session.get("empleado_id")
    try:
        return int(empleado_id) if empleado_id else None
    except (TypeError, ValueError):
        return None


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not _current_web_user_id():
            return redirect(url_for("web_auth.login"))
        return view(*args, **kwargs)
    return wrapped


def has_role(user_id, role):
    user = _cached_web_user(user_id)
    if user:
        if not user.get("activo"):
            return False
        user_role = str(user.get("rol") or "").strip().lower()
        expected = str(role or "").strip().lower()
        return user_role == "admin" or (bool(expected) and user_role == expected)
    return has_any_role(user_id, [role])


def _cached_web_user(user_id):
    if not user_id:
        return None
    user_id = int(user_id)
    if has_request_context():
        cached = getattr(g, "_current_web_user", None)
        if cached and int(cached.get("id") or 0) == user_id:
            return cached
    user = get_web_user_by_id(user_id)
    if has_request_context():
        g._current_web_user = user
    return user


def _cached_user_permissions(user_id):
    if not user_id:
        return {}
    user_id = int(user_id)
    if has_request_context():
        cache = getattr(g, "_web_permissions_by_user", None)
        if cache is None:
            cache = {}
            g._web_permissions_by_user = cache
        if user_id not in cache:
            cache[user_id] = get_user_permissions(user_id)
        return cache[user_id]
    return get_user_permissions(user_id)


def can_access_module(user_id, module, action="ver"):
    if not user_id:
        return False
    user = _cached_web_user(int(user_id))
    if not user or not user.get("activo"):
        return False
    role_norm = str(user.get("rol") or "").strip().lower()
    if role_norm == "admin":
        return True

    action_norm = str(action or "ver").strip().lower()
    if action_norm not in PERMISSION_ACTIONS:
        action_norm = "ver"
    module_norm = str(module or "").strip()
    if not module_norm:
        return False

    permissions = _cached_user_permissions(int(user_id))
    if permissions:
        return bool(permissions.get(module_norm, {}).get(action_norm))

    return module_norm in role_default_module_codes(role_norm)


_PATH_MODULES = [
    ("/organigrama/", "organizacion"),
    ("/empresas/", "empresas"),
    ("/sucursales/", "sucursales"),
    ("/sectores/", "sectores"),
    ("/puestos/", "puestos"),
    ("/localidades/", "localidades"),
    ("/empleados/", "empleados"),
    ("/legajos/", "legajos"),
    ("/usuarios/", "usuarios"),
    ("/roles/", "roles_empleados"),
    ("/empleado-roles/", "roles_empleados"),
    ("/horarios/", "horarios"),
    ("/empleado-horarios/", "horarios"),
    ("/empleado-excepciones/", "horarios"),
    ("/asistencias/", "asistencias"),
    ("/justificaciones/", "justificaciones"),
    ("/qr-puerta/", "qr_puerta"),
    ("/francos/", "francos"),
    ("/vacaciones/", "vacaciones"),
    ("/adelantos/", "pedidos_empleados"),
    ("/pedidos-mercaderia/", "pedidos_empleados"),
    ("/feedback/", "feedback"),
    ("/skap/", "skap"),
    ("/kpis-sectoriales/", "kpis"),
    ("/premios-concursos/", "premios"),
    ("/admin/trivias/", "trivias"),
    ("/configuracion-empresa/", "configuracion"),
    ("/auditoria/", "auditoria"),
    ("/app-version/", "app_version"),
    ("/mobile-stats/", "mobile_stats"),
    ("/calificaciones-app/", "calificaciones_app"),
]


def _module_for_current_path():
    path = request.path or ""
    for prefix, module in _PATH_MODULES:
        if path.startswith(prefix):
            return module
    return None


def _action_for_current_request():
    if request.method == "GET":
        return "ver"
    path = request.path or ""
    if any(part in path for part in ("/aprobar", "/rechazar", "/revertir", "/activar", "/desactivar")):
        return "aprobar"
    if any(part in path for part in ("/eliminar", "/delete")) or request.method == "DELETE":
        return "eliminar"
    if any(part in path for part in ("/nuevo", "/importar", "/backfill")):
        return "crear"
    return "editar"


def role_required(*roles):
    def decorator(view):
        @wraps(view)
        def wrapped(*args, **kwargs):
            user_id = _current_web_user_id()
            if not user_id:
                return redirect(url_for("web_auth.login"))

            allowed = any(has_role(user_id, role) for role in roles) if roles else True
            if not allowed:
                module = _module_for_current_path()
                if module and can_access_module(user_id, module, _action_for_current_request()):
                    allowed = True
            if not allowed:
                abort(403)

            return view(*args, **kwargs)
        return wrapped
    return decorator


def permission_required(module, action="ver", *fallback_roles):
    def decorator(view):
        @wraps(view)
        def wrapped(*args, **kwargs):
            user_id = _current_web_user_id()
            if not user_id:
                return redirect(url_for("web_auth.login"))

            if can_access_module(user_id, module, action):
                return view(*args, **kwargs)

            if fallback_roles:
                allowed = any(has_role(user_id, role) for role in fallback_roles)
                if allowed:
                    return view(*args, **kwargs)

            abort(403)

        return wrapped
    return decorator
