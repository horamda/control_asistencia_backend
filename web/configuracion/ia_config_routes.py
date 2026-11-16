"""Configuración de IA: proveedor, modelo, activación del generador de trivias, límites y uso.

Prefix: /configuracion-ia   Auth: administrador (módulo "configuracion").
Las claves de API no se cargan ni se muestran acá: viven en variables de entorno del servidor.
"""

from flask import Blueprint, flash, jsonify, redirect, render_template, request, session, url_for

from services import ia_config_service as ia_config
from services import ia_proveedores as prov
from utils.audit import log_audit
from utils.limiter import limiter
from web.auth.decorators import role_required

ia_config_bp = Blueprint("ia_config", __name__, url_prefix="/configuracion-ia")


@ia_config_bp.get("/")
@role_required("admin")
def index():
    return render_template("configuracion_ia/index.html", errors=[], **ia_config.panel())


@ia_config_bp.post("/guardar")
@role_required("admin")
def guardar():
    errors = ia_config.guardar(request.form)
    if errors:
        return render_template("configuracion_ia/index.html", errors=errors, **ia_config.panel()), 400
    log_audit(session, "update", "system_config", None)
    flash("Configuración de IA guardada.", "success")
    return redirect(url_for("ia_config.index"))


def _proveedor_modelo():
    proveedor = (request.form.get("proveedor") or "").strip()
    modelo = (request.form.get("modelo") or "").strip()[:120]
    return (proveedor if proveedor in prov.PROVEEDORES else None), modelo


@ia_config_bp.post("/probar")
@role_required("admin")
@limiter.limit("10 per minute")
def probar():
    proveedor, modelo = _proveedor_modelo()
    if not proveedor:
        return jsonify({"ok": False, "tipo": "config", "mensaje": "Proveedor inválido."}), 400
    cfg = ia_config.cargar()
    modelo = modelo or cfg["modelos"][proveedor]
    return jsonify(ia_config.probar_conexion(cfg, proveedor, modelo, session.get("user_id")))


@ia_config_bp.post("/modelos")
@role_required("admin")
@limiter.limit("10 per minute")
def modelos():
    proveedor, _ = _proveedor_modelo()
    if not proveedor:
        return jsonify({"ok": False, "mensaje": "Proveedor inválido."}), 400
    try:
        return jsonify({"ok": True, "modelos": prov.listar_modelos(proveedor)})
    except prov.IAError as exc:
        return jsonify({"ok": False, "tipo": exc.tipo, "mensaje": str(exc)})
