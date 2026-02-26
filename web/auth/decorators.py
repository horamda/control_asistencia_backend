from functools import wraps
from flask import session, redirect, url_for, abort

from repositories.roles_repository import has_any_role


def _current_web_user_id():
    return session.get("user_id")


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not _current_web_user_id():
            return redirect(url_for("web_auth.login"))
        return view(*args, **kwargs)
    return wrapped


def has_role(user_id, role):
    return has_any_role(user_id, [role])


def role_required(*roles):
    def decorator(view):
        @wraps(view)
        def wrapped(*args, **kwargs):
            user_id = _current_web_user_id()
            if not user_id:
                return redirect(url_for("web_auth.login"))

            allowed = any(has_role(user_id, role) for role in roles) if roles else True
            if not allowed:
                abort(403)

            return view(*args, **kwargs)
        return wrapped
    return decorator
