import re

from flask import Blueprint, abort, redirect, render_template, request, session, url_for

from repositories.legajo_evento_repository import (
    count_eventos_vigentes_by_tipo,
    create_tipo_evento,
    get_tipo_evento_by_codigo,
    get_tipo_evento_by_id,
    get_tipos_evento_page,
    set_tipo_evento_activo,
    update_tipo_evento,
)
from utils.audit import log_audit
from web.auth.decorators import role_required

legajo_tipos_evento_bp = Blueprint(
    "legajo_tipos_evento",
    __name__,
    url_prefix="/legajos/tipos-evento",
)

_CODIGO_REGEX = re.compile(r"^[a-z0-9_]{2,40}$")


def _normalize_codigo(raw: str | None):
    value = (raw or "").strip().lower()
    value = re.sub(r"\s+", "_", value)
    value = re.sub(r"[^a-z0-9_]", "", value)
    value = re.sub(r"_+", "_", value)
    return value.strip("_")


def _extract(form):
    return {
        "codigo": _normalize_codigo(form.get("codigo")),
        "nombre": (form.get("nombre") or "").strip(),
        "requiere_rango_fechas": form.get("requiere_rango_fechas") == "1",
        "permite_adjuntos": form.get("permite_adjuntos") == "1",
        "activo": form.get("activo") == "1",
    }


def _validate(data: dict, tipo_id: int | None = None):
    errors = []
    codigo = data.get("codigo") or ""
    nombre = data.get("nombre") or ""

    if not codigo:
        errors.append("Codigo es requerido.")
    elif not _CODIGO_REGEX.match(codigo):
        errors.append("Codigo invalido. Use solo letras, numeros y guion bajo (2-40).")

    if not nombre:
        errors.append("Nombre es requerido.")
    elif len(nombre) > 80:
        errors.append("Nombre supera el maximo de 80 caracteres.")

    if codigo:
        existing = get_tipo_evento_by_codigo(codigo)
        if existing and int(existing["id"]) != int(tipo_id or 0):
            errors.append("Codigo ya existe.")

    return errors


@legajo_tipos_evento_bp.route("/")
@role_required("admin", "rrhh")
def listado():
    page = request.args.get("page", 1, type=int)
    per_page = request.args.get("per", 20, type=int)
    if per_page not in {10, 20, 50, 100}:
        per_page = 20

    activo = request.args.get("activo", default=None, type=int)
    if activo not in {None, 0, 1}:
        activo = None
    search = (request.args.get("q") or "").strip() or None

    tipos, total = get_tipos_evento_page(
        page=page,
        per_page=per_page,
        search=search,
        activo=activo,
    )
    return render_template(
        "legajos_tipos_evento/listado.html",
        tipos=tipos,
        total=total,
        page=page,
        per_page=per_page,
        activo=activo,
        q=search,
    )


@legajo_tipos_evento_bp.route("/nuevo", methods=["GET", "POST"])
@role_required("admin", "rrhh")
def nuevo():
    if request.method == "POST":
        data = _extract(request.form)
        errors = _validate(data)
        if errors:
            return render_template("legajos_tipos_evento/form.html", mode="new", data=data, errors=errors)
        tipo_id = create_tipo_evento(data)
        log_audit(session, "create", "legajo_tipos_evento", tipo_id)
        return redirect(url_for("legajo_tipos_evento.listado"))

    return render_template(
        "legajos_tipos_evento/form.html",
        mode="new",
        data={"requiere_rango_fechas": False, "permite_adjuntos": True, "activo": True},
    )


@legajo_tipos_evento_bp.route("/editar/<int:tipo_id>", methods=["GET", "POST"])
@role_required("admin", "rrhh")
def editar(tipo_id):
    tipo = get_tipo_evento_by_id(tipo_id)
    if not tipo:
        abort(404)

    if request.method == "POST":
        data = _extract(request.form)
        errors = _validate(data, tipo_id=tipo_id)
        if errors:
            merged = dict(tipo)
            merged.update(data)
            return render_template("legajos_tipos_evento/form.html", mode="edit", data=merged, errors=errors)
        update_tipo_evento(tipo_id, data)
        log_audit(session, "update", "legajo_tipos_evento", tipo_id)
        return redirect(url_for("legajo_tipos_evento.listado"))

    return render_template("legajos_tipos_evento/form.html", mode="edit", data=tipo)


@legajo_tipos_evento_bp.route("/activar/<int:tipo_id>")
@role_required("admin", "rrhh")
def activar(tipo_id):
    tipo = get_tipo_evento_by_id(tipo_id)
    if not tipo:
        abort(404)
    set_tipo_evento_activo(tipo_id, 1)
    log_audit(session, "activate", "legajo_tipos_evento", tipo_id)
    return redirect(url_for("legajo_tipos_evento.listado"))


@legajo_tipos_evento_bp.route("/desactivar/<int:tipo_id>")
@role_required("admin", "rrhh")
def desactivar(tipo_id):
    tipo = get_tipo_evento_by_id(tipo_id)
    if not tipo:
        abort(404)
    vigentes = count_eventos_vigentes_by_tipo(tipo_id)
    if vigentes > 0:
        abort(400, description="No se puede desactivar: el tipo tiene eventos vigentes asociados.")
    set_tipo_evento_activo(tipo_id, 0)
    log_audit(session, "deactivate", "legajo_tipos_evento", tipo_id)
    return redirect(url_for("legajo_tipos_evento.listado"))
