from functools import wraps
from flask import session, redirect, url_for, abort

from repositories.roles_repository import has_role


def _current_actor_id():
    # Compatibilidad temporal: prioriza user_id y cae a admin_id legacy.
    return session.get("user_id") or session.get("admin_id")


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not _current_actor_id():
            return redirect(url_for("web_auth.login"))
        return view(*args, **kwargs)
    return wrapped


def role_required(role):
    def decorator(view):
        @wraps(view)
        def wrapped(*args, **kwargs):
            actor_id = _current_actor_id()
            if not actor_id:
                return redirect(url_for("web_auth.login"))

            if not has_role(actor_id, role):
                abort(403)

            return view(*args, **kwargs)
        return wrapped
    return decorator
