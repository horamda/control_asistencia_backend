"""
Trivia Operativa – panel de administración web.
Prefix: /admin/trivias
Auth:   @role_required("admin", "rrhh")
"""

import csv
import datetime
import io

from flask import (
    Blueprint, Response, flash, jsonify, redirect, render_template,
    request, session, url_for,
)

import repositories.trivia_repository as repo
from repositories.empleado_repository import get_all as get_empleados
from repositories.sector_repository import get_page as get_sectores_page
from services.trivia_service import (
    TriviaError,
    TriviaNoEncontradaError,
    calcular_ranking,
    calcular_ranking_anual,
    finalizar_trivia,
    recalcular_resultados_trivia,
)
from utils.audit import log_audit
from web.auth.decorators import role_required

trivia_admin_bp = Blueprint(
    "trivia_admin",
    __name__,
    url_prefix="/admin/trivias",
)

_ESTADOS = ["programada", "activa", "finalizada", "inactiva"]
_OPCIONES_RESP = ["A", "B", "C", "D"]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _current_year_options():
    anio = datetime.date.today().year
    return list(range(anio + 1, anio - 4, -1))


def _get_sectores():
    rows, _ = get_sectores_page(1, 500, activo=1)
    return rows


def _parse_dt(value: str) -> datetime.datetime | None:
    if not value:
        return None
    for fmt in ("%Y-%m-%dT%H:%M", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            return datetime.datetime.strptime(value.strip(), fmt)
        except ValueError:
            continue
    return None


def _trivia_from_form(form) -> dict:
    return {
        "titulo": (form.get("titulo") or "").strip(),
        "descripcion": (form.get("descripcion") or "").strip() or None,
        "fecha_inicio": _parse_dt(form.get("fecha_inicio")),
        "fecha_fin": _parse_dt(form.get("fecha_fin")),
        "estado": form.get("estado", "programada"),
        "premio": (form.get("premio") or "").strip() or None,
        "mensaje_ganador": (form.get("mensaje_ganador") or "").strip() or None,
        "sector_ids": [int(x) for x in form.getlist("sector_ids") if str(x).isdigit()],
        "anio": int(form.get("anio") or datetime.date.today().year),
    }


def _validate_trivia(data: dict) -> list[str]:
    errors = []
    if not data.get("titulo"):
        errors.append("El título es obligatorio.")
    if not data.get("fecha_inicio"):
        errors.append("La fecha de inicio es obligatoria.")
    if not data.get("fecha_fin"):
        errors.append("La fecha de fin es obligatoria.")
    if data.get("fecha_inicio") and data.get("fecha_fin"):
        if data["fecha_fin"] <= data["fecha_inicio"]:
            errors.append("La fecha de fin debe ser posterior a la de inicio.")
    return errors


def _build_resultados_summary(rows: list[dict]) -> dict:
    summary = {
        "habilitados": 0,
        "resultados": 0,
        "completados": 0,
        "en_progreso": 0,
        "pendientes": 0,
        "excluidos": 0,
    }
    for row in rows:
        excluido = bool(row.get("exclusion_id"))
        habilitado = bool(row.get("habilitado_por_alcance"))
        estado = row.get("estado_resultado")
        if excluido:
            summary["excluidos"] += 1
            row["estado_admin"] = "excluido"
        elif estado:
            summary["resultados"] += 1
            row["estado_admin"] = estado
            if estado == "completado":
                summary["completados"] += 1
            elif estado == "en_progreso":
                summary["en_progreso"] += 1
        elif habilitado:
            summary["pendientes"] += 1
            row["estado_admin"] = "pendiente"
        else:
            row["estado_admin"] = "fuera_alcance"
        if habilitado and not excluido:
            summary["habilitados"] += 1
    return summary


def _enrich_resultados_with_ranking(rows: list[dict], ranking: list[dict]):
    ranking_by_emp = {int(r["empleado_id"]): r for r in ranking}
    for row in rows:
        rank = ranking_by_emp.get(int(row["empleado_id"]))
        row["posicion_calculada"] = rank["posicion"] if rank else None
        row["es_ganador_calculado"] = bool(rank["es_ganador"]) if rank else False


def _fmt_dt(value):
    if not value:
        return ""
    return value.strftime("%d/%m/%Y %H:%M") if hasattr(value, "strftime") else str(value)


# ---------------------------------------------------------------------------
# Listado
# ---------------------------------------------------------------------------

@trivia_admin_bp.get("/")
@role_required("admin", "rrhh")
def listado():
    page = max(1, int(request.args.get("page", 1)))
    per_page = 20
    estado = request.args.get("estado") or None
    anio_raw = request.args.get("anio")
    anio = int(anio_raw) if anio_raw and anio_raw.isdigit() else None

    rows, total = repo.get_trivias_page(page, per_page, estado=estado, anio=anio)
    pages = max(1, (total + per_page - 1) // per_page)

    return render_template(
        "trivias/listado.html",
        trivias=rows,
        total=total,
        page=page,
        pages=pages,
        estados=_ESTADOS,
        anios=_current_year_options(),
        filtro_estado=estado,
        filtro_anio=anio,
    )


# ---------------------------------------------------------------------------
# Crear trivia
# ---------------------------------------------------------------------------

@trivia_admin_bp.route("/nueva", methods=["GET", "POST"])
@role_required("admin", "rrhh")
def nueva():
    sectores = _get_sectores()
    errors = []
    sector_ids = []

    if request.method == "POST":
        data = _trivia_from_form(request.form)
        sector_ids = data.get("sector_ids", [])
        errors = _validate_trivia(data)
        if not errors:
            try:
                trivia_id = repo.create_trivia(data)
                log_audit(session, "create", "trivias", trivia_id)
                flash("Trivia creada correctamente.", "success")
                return redirect(url_for("trivia_admin.detalle", trivia_id=trivia_id))
            except Exception as exc:
                errors.append(f"Error al guardar: {exc}")

    return render_template(
        "trivias/form.html",
        trivia=None,
        sectores=sectores,
        sector_ids=sector_ids,
        estados=_ESTADOS,
        anios=_current_year_options(),
        errors=errors,
        action=url_for("trivia_admin.nueva"),
    )


# ---------------------------------------------------------------------------
# Detalle / editar trivia
# ---------------------------------------------------------------------------

@trivia_admin_bp.get("/<int:trivia_id>")
@role_required("admin", "rrhh")
def detalle(trivia_id: int):
    trivia = repo.get_trivia_by_id(trivia_id)
    if not trivia:
        flash("Trivia no encontrada.", "danger")
        return redirect(url_for("trivia_admin.listado"))

    preguntas = repo.get_preguntas_admin(trivia_id)
    ganador = repo.get_ganador_trivia(trivia_id)
    ranking = calcular_ranking(trivia_id) if trivia["estado"] in ("activa", "finalizada") else []
    sectores = _get_sectores()
    trivia_sectores = repo.get_sectores_trivia(trivia_id)

    return render_template(
        "trivias/detalle.html",
        trivia=trivia,
        preguntas=preguntas,
        ganador=ganador,
        ranking=ranking,
        sectores=sectores,
        trivia_sectores=trivia_sectores,
        estados=_ESTADOS,
        opciones_resp=_OPCIONES_RESP,
    )


@trivia_admin_bp.get("/<int:trivia_id>/resultados")
@role_required("admin", "rrhh")
def resultados(trivia_id: int):
    trivia = repo.get_trivia_by_id(trivia_id)
    if not trivia:
        flash("Trivia no encontrada.", "danger")
        return redirect(url_for("trivia_admin.listado"))

    rows = repo.get_resultados_admin_trivia(trivia_id)
    ranking = calcular_ranking(trivia_id)
    _enrich_resultados_with_ranking(rows, ranking)
    summary = _build_resultados_summary(rows)
    exclusiones = repo.get_exclusiones_trivia(trivia_id)
    excluidos_ids = {int(e["empleado_id"]) for e in exclusiones}
    empleados = [
        e for e in get_empleados(include_inactive=False)
        if int(e["id"]) not in excluidos_ids
    ]
    respuestas = repo.get_respuestas_admin_trivia(trivia_id)

    return render_template(
        "trivias/resultados.html",
        trivia=trivia,
        resultados=rows,
        respuestas=respuestas,
        summary=summary,
        ranking=ranking,
        exclusiones=exclusiones,
        empleados=empleados,
    )


@trivia_admin_bp.get("/<int:trivia_id>/resultados/export.csv")
@role_required("admin", "rrhh")
def resultados_export_csv(trivia_id: int):
    trivia = repo.get_trivia_by_id(trivia_id)
    if not trivia:
        flash("Trivia no encontrada.", "danger")
        return redirect(url_for("trivia_admin.listado"))

    rows = repo.get_resultados_admin_trivia(trivia_id)
    ranking = calcular_ranking(trivia_id)
    _enrich_resultados_with_ranking(rows, ranking)
    _build_resultados_summary(rows)

    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow([
        "trivia_id", "trivia", "estado_trivia", "empleado_id", "legajo", "dni",
        "apellido", "nombre", "sector", "estado", "posicion", "puntos",
        "correctas", "incorrectas", "tiempo_segundos", "inicio_participacion",
        "fin_participacion", "motivo_exclusion",
    ])
    for row in rows:
        writer.writerow([
            trivia["id"],
            trivia["titulo"],
            trivia["estado"],
            row.get("empleado_id"),
            row.get("empleado_legajo") or "",
            row.get("empleado_dni") or "",
            row.get("empleado_apellido") or "",
            row.get("empleado_nombre") or "",
            row.get("sector_nombre") or "",
            row.get("estado_admin") or "",
            row.get("posicion_calculada") or "",
            row.get("puntos_total") if row.get("resultado_id") else "",
            row.get("correctas") if row.get("resultado_id") else "",
            row.get("incorrectas") if row.get("resultado_id") else "",
            row.get("tiempo_total_segundos") if row.get("resultado_id") else "",
            _fmt_dt(row.get("fecha_inicio_participacion")),
            _fmt_dt(row.get("fecha_finalizacion")),
            row.get("exclusion_motivo") or "",
        ])

    csv_content = "\ufeff" + out.getvalue()
    filename = f"trivia_{trivia_id}_resultados.csv"
    return Response(
        csv_content,
        mimetype="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@trivia_admin_bp.route("/<int:trivia_id>/exclusiones", methods=["POST"])
@role_required("admin", "rrhh")
def agregar_exclusion(trivia_id: int):
    trivia = repo.get_trivia_by_id(trivia_id)
    if not trivia:
        flash("Trivia no encontrada.", "danger")
        return redirect(url_for("trivia_admin.listado"))

    empleado_id = request.form.get("empleado_id", type=int)
    motivo = (request.form.get("motivo") or "").strip() or None
    if not empleado_id:
        flash("Selecciona un empleado para excluir.", "danger")
        return redirect(url_for("trivia_admin.resultados", trivia_id=trivia_id))

    repo.add_exclusion_trivia(
        trivia_id,
        empleado_id,
        motivo=motivo,
        creado_por=session.get("user_id"),
    )
    recalcular_resultados_trivia(trivia_id)
    log_audit(session, "exclude", "trivia_exclusiones", trivia_id)
    flash("Empleado excluido de la trivia.", "success")
    return redirect(url_for("trivia_admin.resultados", trivia_id=trivia_id))


@trivia_admin_bp.route("/<int:trivia_id>/exclusiones/<int:empleado_id>/eliminar", methods=["POST"])
@role_required("admin", "rrhh")
def eliminar_exclusion(trivia_id: int, empleado_id: int):
    trivia = repo.get_trivia_by_id(trivia_id)
    if not trivia:
        flash("Trivia no encontrada.", "danger")
        return redirect(url_for("trivia_admin.listado"))

    repo.remove_exclusion_trivia(trivia_id, empleado_id)
    recalcular_resultados_trivia(trivia_id)
    log_audit(session, "delete", "trivia_exclusiones", trivia_id)
    flash("Exclusion quitada.", "success")
    return redirect(url_for("trivia_admin.resultados", trivia_id=trivia_id))


@trivia_admin_bp.route("/<int:trivia_id>/editar", methods=["GET", "POST"])
@role_required("admin", "rrhh")
def editar(trivia_id: int):
    trivia = repo.get_trivia_by_id(trivia_id)
    if not trivia:
        flash("Trivia no encontrada.", "danger")
        return redirect(url_for("trivia_admin.listado"))

    sectores = _get_sectores()
    errors = []
    sector_ids = [s["id"] for s in repo.get_sectores_trivia(trivia_id)]

    if request.method == "POST":
        data = _trivia_from_form(request.form)
        sector_ids = data.get("sector_ids", [])
        errors = _validate_trivia(data)
        if not errors:
            try:
                repo.update_trivia(trivia_id, data)
                log_audit(session, "update", "trivias", trivia_id)
                flash("Trivia actualizada.", "success")
                return redirect(url_for("trivia_admin.detalle", trivia_id=trivia_id))
            except Exception as exc:
                errors.append(f"Error al guardar: {exc}")

    return render_template(
        "trivias/form.html",
        trivia=trivia,
        sectores=sectores,
        sector_ids=sector_ids,
        estados=_ESTADOS,
        anios=_current_year_options(),
        errors=errors,
        action=url_for("trivia_admin.editar", trivia_id=trivia_id),
    )


# ---------------------------------------------------------------------------
# Preguntas – agregar
# ---------------------------------------------------------------------------

@trivia_admin_bp.route("/<int:trivia_id>/preguntas", methods=["POST"])
@role_required("admin", "rrhh")
def agregar_pregunta(trivia_id: int):
    trivia = repo.get_trivia_by_id(trivia_id)
    if not trivia:
        flash("Trivia no encontrada.", "danger")
        return redirect(url_for("trivia_admin.listado"))

    form = request.form
    errors = []
    texto = (form.get("texto") or "").strip()
    opciones = {
        "opcion_a": (form.get("opcion_a") or "").strip(),
        "opcion_b": (form.get("opcion_b") or "").strip(),
        "opcion_c": (form.get("opcion_c") or "").strip(),
        "opcion_d": (form.get("opcion_d") or "").strip(),
    }
    resp_correcta = (form.get("respuesta_correcta") or "").upper()

    if not texto:
        errors.append("El texto de la pregunta es obligatorio.")
    if not all(opciones.values()):
        errors.append("Todas las opciones (A, B, C, D) son obligatorias.")
    if resp_correcta not in _OPCIONES_RESP:
        errors.append("La respuesta correcta debe ser A, B, C o D.")

    if errors:
        for e in errors:
            flash(e, "danger")
        return redirect(url_for("trivia_admin.detalle", trivia_id=trivia_id))

    data = {
        "texto": texto,
        **opciones,
        "respuesta_correcta": resp_correcta,
        "puntos": int(form.get("puntos") or 10),
        "activa": 1,
        "orden": int(form.get("orden") or 0),
    }
    repo.create_pregunta(trivia_id, data)
    log_audit(session, "create", "trivia_preguntas", trivia_id)
    flash("Pregunta agregada.", "success")
    return redirect(url_for("trivia_admin.detalle", trivia_id=trivia_id))


# ---------------------------------------------------------------------------
# Preguntas – editar
# ---------------------------------------------------------------------------

@trivia_admin_bp.route("/<int:trivia_id>/preguntas/<int:pregunta_id>/editar", methods=["POST"])
@role_required("admin", "rrhh")
def editar_pregunta(trivia_id: int, pregunta_id: int):
    pregunta = repo.get_pregunta_by_id(pregunta_id)
    if not pregunta or int(pregunta["trivia_id"]) != trivia_id:
        flash("Pregunta no encontrada.", "danger")
        return redirect(url_for("trivia_admin.detalle", trivia_id=trivia_id))

    form = request.form
    errors = []
    texto = (form.get("texto") or "").strip()
    opciones = {
        "opcion_a": (form.get("opcion_a") or "").strip(),
        "opcion_b": (form.get("opcion_b") or "").strip(),
        "opcion_c": (form.get("opcion_c") or "").strip(),
        "opcion_d": (form.get("opcion_d") or "").strip(),
    }
    resp_correcta = (form.get("respuesta_correcta") or "").upper()

    if not texto:
        errors.append("El texto de la pregunta es obligatorio.")
    if not all(opciones.values()):
        errors.append("Todas las opciones (A, B, C, D) son obligatorias.")
    if resp_correcta not in _OPCIONES_RESP:
        errors.append("La respuesta correcta debe ser A, B, C o D.")

    if errors:
        for e in errors:
            flash(e, "danger")
        return redirect(url_for("trivia_admin.detalle", trivia_id=trivia_id))

    data = {
        "texto": texto,
        **opciones,
        "respuesta_correcta": resp_correcta,
        "puntos": int(form.get("puntos") or 10),
        "activa": int(form.get("activa", 1)),
        "orden": int(form.get("orden") or 0),
    }
    repo.update_pregunta(pregunta_id, data)
    log_audit(session, "update", "trivia_preguntas", pregunta_id)
    flash("Pregunta actualizada.", "success")
    return redirect(url_for("trivia_admin.detalle", trivia_id=trivia_id))


# ---------------------------------------------------------------------------
# Preguntas – eliminar
# ---------------------------------------------------------------------------

@trivia_admin_bp.route("/<int:trivia_id>/preguntas/<int:pregunta_id>/eliminar", methods=["POST"])
@role_required("admin", "rrhh")
def eliminar_pregunta(trivia_id: int, pregunta_id: int):
    pregunta = repo.get_pregunta_by_id(pregunta_id)
    if not pregunta or int(pregunta["trivia_id"]) != trivia_id:
        flash("Pregunta no encontrada.", "danger")
        return redirect(url_for("trivia_admin.detalle", trivia_id=trivia_id))

    repo.delete_pregunta(pregunta_id)
    log_audit(session, "delete", "trivia_preguntas", pregunta_id)
    flash("Pregunta eliminada.", "success")
    return redirect(url_for("trivia_admin.detalle", trivia_id=trivia_id))


# ---------------------------------------------------------------------------
# Finalizar trivia manualmente
# ---------------------------------------------------------------------------

@trivia_admin_bp.route("/<int:trivia_id>/finalizar", methods=["POST"])
@role_required("admin", "rrhh")
def finalizar_manual(trivia_id: int):
    try:
        finalizar_trivia(trivia_id)
        log_audit(session, "finalize", "trivias", trivia_id)
        flash("Trivia finalizada y ranking calculado.", "success")
    except TriviaNoEncontradaError as exc:
        flash(str(exc), "danger")
    except TriviaError as exc:
        flash(str(exc), "danger")
    return redirect(url_for("trivia_admin.detalle", trivia_id=trivia_id))


# ---------------------------------------------------------------------------
# Ranking anual (vista web)
# ---------------------------------------------------------------------------

@trivia_admin_bp.get("/ranking-anual")
@role_required("admin", "rrhh")
def ranking_anual_view():
    anio = int(request.args.get("anio") or datetime.date.today().year)
    ranking = calcular_ranking_anual(anio)
    exclusiones = repo.get_exclusiones_ranking_anual(anio)
    excluidos_ids = {int(e["empleado_id"]) for e in exclusiones}
    empleados = [
        e for e in get_empleados(include_inactive=False)
        if int(e["id"]) not in excluidos_ids
    ]
    return render_template(
        "trivias/ranking_anual.html",
        ranking=ranking,
        exclusiones=exclusiones,
        empleados=empleados,
        anio=anio,
        anios=_current_year_options(),
    )


@trivia_admin_bp.route("/ranking-anual/exclusiones", methods=["POST"])
@role_required("admin", "rrhh")
def agregar_exclusion_ranking_anual():
    anio = request.form.get("anio", type=int) or datetime.date.today().year
    empleado_id = request.form.get("empleado_id", type=int)
    motivo = (request.form.get("motivo") or "").strip() or None
    if not empleado_id:
        flash("Selecciona un empleado para excluir del ranking anual.", "danger")
        return redirect(url_for("trivia_admin.ranking_anual_view", anio=anio))

    repo.add_exclusion_ranking_anual(
        anio,
        empleado_id,
        motivo=motivo,
        creado_por=session.get("user_id"),
    )
    repo.recalcular_ranking_anual(anio)
    log_audit(session, "exclude_anual", "trivia_ranking_anual_exclusiones", empleado_id)
    flash("Empleado excluido del ranking anual.", "success")
    return redirect(url_for("trivia_admin.ranking_anual_view", anio=anio))


@trivia_admin_bp.route("/ranking-anual/exclusiones/<int:empleado_id>/eliminar", methods=["POST"])
@role_required("admin", "rrhh")
def eliminar_exclusion_ranking_anual(empleado_id: int):
    anio = request.form.get("anio", type=int) or datetime.date.today().year
    repo.remove_exclusion_ranking_anual(anio, empleado_id)
    repo.recalcular_ranking_anual(anio)
    log_audit(session, "delete_exclusion_anual", "trivia_ranking_anual_exclusiones", empleado_id)
    flash("Exclusion anual quitada.", "success")
    return redirect(url_for("trivia_admin.ranking_anual_view", anio=anio))


# ---------------------------------------------------------------------------
# API JSON – endpoints para llamadas AJAX desde el panel
# ---------------------------------------------------------------------------

@trivia_admin_bp.get("/api/<int:trivia_id>/ranking")
@role_required("admin", "rrhh")
def api_ranking(trivia_id: int):
    ranking = calcular_ranking(trivia_id)
    return jsonify({"success": True, "data": ranking})


@trivia_admin_bp.get("/api/ranking-anual/<int:anio>")
@role_required("admin", "rrhh")
def api_ranking_anual(anio: int):
    rows = repo.get_ranking_anual(anio)
    return jsonify({"success": True, "data": rows, "anio": anio})
