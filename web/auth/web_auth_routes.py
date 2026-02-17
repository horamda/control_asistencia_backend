from flask import Blueprint, redirect, render_template, request, session, url_for

from web.auth.web_auth_service import authenticate_admin

web_auth_bp = Blueprint("web_auth", __name__)


@web_auth_bp.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "").strip()

        user = authenticate_admin(username, password)
        if user:
            session.clear()
            session["user_id"] = user["id"]
            session["admin_user"] = user["usuario"]
            session["user_role"] = user.get("rol")
            return redirect(url_for("web.dashboard"))

        return render_template("login.html", error="Credenciales invalidas")

    return render_template("login.html")


@web_auth_bp.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("web_auth.login"))
