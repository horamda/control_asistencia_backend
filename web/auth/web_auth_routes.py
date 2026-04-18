from flask import Blueprint, current_app, redirect, render_template, request, session, url_for

from utils.limiter import limiter
from web.auth.web_auth_service import authenticate_admin

web_auth_bp = Blueprint("web_auth", __name__)


@web_auth_bp.route("/login", methods=["GET", "POST"])
@limiter.limit("10 per minute", methods=["POST"])
def login():
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "").strip()

        user = authenticate_admin(username, password)
        if user:
            session.clear()
            session.permanent = True
            session["user_id"] = user["id"]
            session["web_user"] = user["usuario"]
            session["user_role"] = user.get("rol")
            return redirect(url_for("web.dashboard"))

        current_app.logger.info(
            "web_login_failed",
            extra={"extra": {"username": username, "ip": request.remote_addr}},
        )
        return render_template("login.html", error="Credenciales invalidas")

    return render_template("login.html")


@web_auth_bp.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("web_auth.login"))
