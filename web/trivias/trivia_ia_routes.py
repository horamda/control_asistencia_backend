"""
Trivia Operativa – generador de preguntas con IA (panel de administración).
Prefix: /admin/trivias/ia
Auth:   mismos permisos que el alta manual de trivias.

El borrador vive en el navegador hasta que el administrador lo aprueba; recién entonces se
guarda con las mismas validaciones y tablas que una trivia creada a mano.
"""

import json
import logging
import secrets

from flask import Blueprint, flash, jsonify, redirect, render_template, request, session, url_for

import repositories.trivia_repository as repo
import web.trivias.trivia_admin_routes as admin
from services import ia_config_service as ia_config
from services import ia_extraccion as extraccion
from services import trivia_ia_service as generador
from services.ia_proveedores import IAError
from utils.audit import log_audit
from utils.limiter import limiter
from web.auth.decorators import role_required

logger = logging.getLogger(__name__)

trivia_ia_bp = Blueprint("trivia_ia", __name__, url_prefix="/admin/trivias/ia")

_TOKEN = "trivia_ia_token"


def _render(*, cfg=None, errors=None, trivia_form=None, sector_ids=None, borrador=None, status=200):
    cfg = cfg or ia_config.cargar()
    session[_TOKEN] = secrets.token_urlsafe(16)
    return render_template(
        "trivias/generar_ia.html",
        cfg=cfg,
        dificultades=[("facil", "Fácil"), ("medio", "Medio"), ("dificil", "Difícil")],
        min_caracteres=extraccion.MIN_CARACTERES,
        trivia_form=trivia_form,
        sectores=admin._get_sectores(),
        sector_ids=sector_ids or [],
        estados=admin._ESTADOS,
        anios=admin._current_year_options(),
        opciones_resp=admin._OPCIONES_RESP,
        errors=errors or [],
        borrador=borrador or [],
        token=session[_TOKEN],
    ), status


@trivia_ia_bp.get("/")
@role_required("admin", "rrhh")
def pagina():
    return _render()


def _error(mensaje: str, status: int = 400, tipo: str = "validacion"):
    return jsonify({"success": False, "error": mensaje, "tipo": tipo}), status


@trivia_ia_bp.post("/generar")
@role_required("admin", "rrhh")
@limiter.limit("10 per minute")
def generar():
    cfg = ia_config.cargar()
    form = request.form
    try:
        if form.get("modo") == "archivo":
            archivo = request.files.get("archivo")
            if not archivo or not archivo.filename:
                return _error("Seleccioná un archivo.")
            max_bytes = cfg["max_archivo_mb"] * 1024 * 1024
            contenido = extraccion.desde_archivo(
                archivo.filename, archivo.stream.read(max_bytes + 1),
                max_caracteres=cfg["max_caracteres"], max_bytes=max_bytes)
        else:
            contenido = extraccion.desde_texto(form.get("texto") or "", cfg["max_caracteres"])
    except extraccion.DocumentoError as exc:
        return _error(str(exc))

    try:
        cantidad = int(form.get("cantidad") or 0)
    except ValueError:
        cantidad = 0
    if not 1 <= cantidad <= cfg["max_preguntas"]:
        return _error(f"La cantidad de preguntas debe estar entre 1 y {cfg['max_preguntas']}.")
    try:
        evitar = json.loads(form.get("evitar") or "[]")
        evitar = [str(t)[:600] for t in evitar][:100] if isinstance(evitar, list) else []
    except ValueError:
        evitar = []

    try:
        resultado = generador.generar(
            cfg, contenido,
            cantidad=cantidad,
            dificultad=form.get("dificultad") or "medio",
            titulo=form.get("titulo") or "",
            instrucciones=form.get("instrucciones") or "",
            evitar=evitar,
            usuario_id=session.get("user_id"),
            operacion="regenerar" if form.get("operacion") == "regenerar" else "generar",
        )
    except ia_config.LimiteIAError as exc:
        return _error(str(exc), 409, "limite")
    except generador.GeneracionEnCursoError as exc:
        return _error(str(exc), 409, "duplicada")
    except IAError as exc:
        return _error(str(exc), 502, exc.tipo)
    except Exception:
        logger.exception("[trivia_ia] error inesperado al generar")
        return _error("No se pudo generar la trivia. Podés seguir creando trivias manualmente.", 500, "interno")
    return jsonify({"success": True, **resultado})


@trivia_ia_bp.post("/guardar")
@role_required("admin", "rrhh")
def guardar():
    token = session.pop(_TOKEN, None)
    if not token or not secrets.compare_digest(token, request.form.get("token") or ""):
        flash("Esta trivia ya fue enviada o el formulario venció. Revisá el listado antes de volver a generarla.", "danger")
        return redirect(url_for("trivia_admin.listado"))

    try:
        items = json.loads(request.form.get("preguntas_json") or "[]")
    except ValueError:
        items = []
    try:
        data = admin._trivia_from_form(request.form)
        errors = admin._validate_trivia(data)
    except ValueError:
        data, errors = {"titulo": (request.form.get("titulo") or "").strip()}, ["Revisá los datos de la trivia."]
    preguntas, errores_preguntas = generador.preparar_para_guardar(items)
    errors += errores_preguntas

    if not errors:
        try:
            trivia_id = repo.create_trivia_con_preguntas(data, preguntas)
        except Exception as exc:
            logger.exception("[trivia_ia] error al guardar")
            errors.append(f"Error al guardar: {exc}")
        else:
            try:
                log_audit(session, "create_ia", "trivias", trivia_id)
            except Exception:
                logger.exception("[trivia_ia] no se pudo registrar la auditoria")
            flash(f"Trivia creada con {len(preguntas)} pregunta{'s' if len(preguntas) != 1 else ''}.", "success")
            return redirect(url_for("trivia_admin.detalle", trivia_id=trivia_id))

    return _render(errors=errors, trivia_form=data, sector_ids=data.get("sector_ids"),
                   borrador=items if isinstance(items, list) else [], status=400)
