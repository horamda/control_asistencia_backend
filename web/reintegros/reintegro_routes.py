import csv
import io
from uuid import uuid4
from werkzeug.datastructures import MultiDict
from flask import (
    Blueprint,
    abort,
    flash,
    redirect,
    render_template,
    request,
    session,
    url_for,
    Response,
)
from mysql.connector import IntegrityError, ProgrammingError
from services import reintegro_service as service
from web.auth.decorators import permission_required, can_access_module, _cached_web_user
from routes.carga_routes import private_photo
from web.carga.carga_routes import csv_safe

reintegros_web_bp = Blueprint("reintegros_web", __name__, url_prefix="/reintegros")


def actor():
    user = _cached_web_user(session.get("user_id"))
    if not user or not user.get("activo"):
        abort(403)
    role = str(user.get("rol") or "").lower()
    pay = can_access_module(user["id"], "reintegros_pagos", "editar")
    return dict(
        empresa_id=user["empresa_id"],
        empleado_id=user.get("empleado_id"),
        user_id=user["id"],
        mode="web",
        **{"global": role in ("admin", "rrhh") or pay},
        review_global=role in ("admin", "rrhh"),
        review=can_access_module(user["id"], "reintegros", "aprobar"),
        manage_create=can_access_module(user["id"], "reintegros", "crear"),
        manage_edit=can_access_module(user["id"], "reintegros", "editar"),
        manage_delete=can_access_module(user["id"], "reintegros", "eliminar"),
        pay=pay
    )


@reintegros_web_bp.errorhandler(service.Error)
def invalid(error):
    return render_template("reintegros/error.html", message=str(error)), error.status


@reintegros_web_bp.errorhandler(ProgrammingError)
def schema_unavailable(error):
    if error.errno != 1146:
        raise error
    return (
        render_template(
            "reintegros/error.html",
            message="El módulo de reintegros está pendiente de instalación en la base de datos. Contacte al administrador.",
        ),
        503,
    )


@reintegros_web_bp.errorhandler(IntegrityError)
def conflict(error):
    return (
        render_template(
            "reintegros/error.html",
            message="Ya existe una categoría con ese nombre o los datos entraron en conflicto.",
        ),
        409,
    )


@reintegros_web_bp.get("/")
@permission_required("reintegros", "ver")
def index():
    who = actor()
    return render_template(
        "reintegros/index.html",
        result=service.history(who, request.args),
        states=service.STATES,
        who=who,
    )


def form_data():
    keys = request.form.getlist("linea")
    if (
        not 0 <= len(keys) <= 50
        or len(set(keys)) != len(keys)
        or any(not k.isascii() or not k.isdigit() or len(k) > 6 for k in keys)
    ):
        raise service.Error("Máximo 50 gastos por período.")
    items = []
    files = MultiDict()
    for i, key in enumerate(keys):
        items.append(
            dict(
                fecha=request.form.get("fecha_" + key),
                concepto=request.form.get("concepto_" + key),
                importe=request.form.get("importe_" + key),
                categoria_id=request.form.get("categoria_" + key),
                fotos_existentes=request.form.getlist("conservar_" + key),
                numero_comprobante=request.form.get("numero_" + key),
                emisor=request.form.get("emisor_" + key),
            )
        )
        for photo in request.files.getlist("fotos_" + key):
            if photo.filename:
                files.add("fotos_" + str(i), photo)
    for photo in request.files.getlist("odometro"):
        if photo.filename:
            files.add("odometro", photo)
    return (
        dict(
            envio_id=request.form.get("envio_id"),
            revision=request.form.get("revision"),
            accion=request.form.get("accion", "enviar"),
            periodo=request.form.get("periodo"),
            kilometros=request.form.get("kilometros"),
            quitar_odometro=request.form.get("quitar_odometro", "0"),
            observaciones=request.form.get("observaciones"),
            gastos=items,
        ),
        files,
    )


def edit_form(rid=None):
    who = actor()
    row = service.detail(who, rid) if rid else None
    if row and row["estado"] not in ("borrador", "pendiente", "devuelta"):
        raise service.Error(
            "Solo se editan borradores, solicitudes pendientes o devueltas.", 409
        )
    with service.db.transaction(read_only=True) as c:
        where = "empresa_id=%s AND activo=1 AND EXISTS(SELECT 1 FROM reintegro_sectores h JOIN sectores s ON s.id=h.sector_id AND s.activo=1 WHERE h.empresa_id=empleados.empresa_id AND h.sector_id=empleados.sector_id)"
        args = [who["empresa_id"]]
        if not who.get("global"):
            where += " AND reporta_a_empleado_id=%s AND id<>%s"
            args.extend([who.get("empleado_id") or 0, who.get("empleado_id") or 0])
        employees = service.db.all_rows(
            c,
            "SELECT id,legajo,nombre,apellido FROM empleados WHERE "
            + where
            + " ORDER BY apellido,nombre",
            tuple(args),
        )
    data = dict(
        envio_id=str(uuid4()),
        revision=row["revision"] if row else "",
        empleado_id=row["empleado_id"] if row else request.args.get("empleado_id", ""),
        observaciones=row["observaciones"] if row else "",
        periodo=(
            row["periodo"].strftime("%Y-%m")
            if row and row.get("periodo")
            else (
                ""
                if row
                else request.args.get("periodo", service.now_local().strftime("%Y-%m"))
            )
        ),
        kilometros=row.get("kilometros") if row else "",
        gastos=(
            row["gastos"]
            if row
            else [
                dict(
                    fecha=str(service.now_local().date()),
                    concepto="",
                    importe="",
                    fotos=[],
                )
            ]
        ),
    )
    error = None
    status = 200
    if request.method == "POST":
        try:
            submitted, files = form_data()
            eid = (
                row["empleado_id"]
                if row
                else service.positive_int(request.form.get("empleado_id"), "Empleado")
            )
            data.update(submitted, empleado_id=eid)
            # Only display existing photos from this authorized request after validation errors.
            allowed = {
                f["id"]: f for g in (row["gastos"] if row else []) for f in g["fotos"]
            }
            for item in data["gastos"]:
                item["fotos"] = [
                    allowed[int(fid)]
                    for fid in item.get("fotos_existentes", [])
                    if str(fid).isdigit() and int(fid) in allowed
                ]
            saved, created = service.store(
                dict(id=eid, empresa_id=who["empresa_id"]),
                submitted,
                files,
                rid,
                web_actor=who,
            )
            flash(
                (
                    "Borrador guardado."
                    if submitted["accion"] == "borrador"
                    else "Solicitud guardada y pendiente de aprobación."
                ),
                "success",
            )
            return redirect(url_for("reintegros_web.detail", rid=saved))
        except service.Error as exc:
            error = str(exc)
            status = exc.status
    return (
        render_template(
            "reintegros/form.html",
            row=row,
            data=data,
            employees=employees,
            categories=service.categories(who["empresa_id"]),
            error=error,
            today=service.now_local().date(),
        ),
        status,
    )


@reintegros_web_bp.route("/nuevo", methods=["GET", "POST"])
@permission_required("reintegros", "ver")
@permission_required("reintegros", "crear")
def create():
    return edit_form()


@reintegros_web_bp.route("/solicitudes/<int:rid>/editar", methods=["GET", "POST"])
@permission_required("reintegros", "ver")
@permission_required("reintegros", "editar")
def edit(rid):
    return edit_form(rid)


@reintegros_web_bp.route("/configuracion", methods=["GET", "POST"])
@permission_required("reintegros", "ver")
@permission_required("reintegros", "editar")
def settings():
    who = actor()
    if not who["review_global"]:
        abort(403)
    if request.method == "POST":
        service.monthly.save_settings(
            who["empresa_id"],
            who["user_id"],
            request.form.getlist("sectores"),
            request.form.get("revision"),
        )
        flash("Sectores habilitados actualizados.", "success")
        return redirect(url_for("reintegros_web.settings"))
    return render_template(
        "reintegros/settings.html", config=service.monthly.settings(who["empresa_id"])
    )


@reintegros_web_bp.get("/mensual")
@permission_required("reintegros", "ver")
def monthly_report():
    who = actor()
    report = service.monthly.report(
        who, request.args.get("periodo", service.now_local().strftime("%Y-%m"))
    )
    return render_template("reintegros/monthly.html", report=report, who=who)


@reintegros_web_bp.get("/mensual.csv")
@permission_required("reintegros", "ver")
@permission_required("reintegros", "exportar")
def monthly_export():
    report = service.monthly.report(
        actor(), request.args.get("periodo", service.now_local().strftime("%Y-%m"))
    )
    output = io.StringIO()
    writer = csv.writer(output, delimiter=";")
    writer.writerow(
        [
            "Periodo",
            "Legajo",
            "Empleado",
            "Sector",
            "Kilometros",
            "Total gastos ARS",
            "Total aprobado ARS",
            "Estado",
        ]
    )
    for r in report["items"]:
        writer.writerow(
            [
                csv_safe(v)
                for v in [
                    report["periodo"].strftime("%Y-%m"),
                    r["legajo"],
                    r["empleado_nombre"],
                    r["sector_nombre"],
                    r["kilometros"],
                    r["total_solicitado"],
                    r["total_aprobado"],
                    r["estado"] or "sin_cargar",
                ]
            ]
        )
    return Response(
        "\ufeff" + output.getvalue(),
        content_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": "attachment; filename=viaticos_mensuales.csv",
            "Cache-Control": "private, no-store",
        },
    )


@reintegros_web_bp.get("/odometro/<int:fid>")
@permission_required("reintegros", "ver")
def odometer(fid):
    return private_photo(service.odometer_photo(actor(), fid))


@reintegros_web_bp.get("/solicitudes/<int:rid>")
@permission_required("reintegros", "ver")
def detail(rid):
    who = actor()
    row = service.detail(who, rid)
    with service.db.transaction(read_only=True) as c:
        boss = service.db.one(
            c,
            "SELECT reporta_a_empleado_id FROM empleados WHERE id=%s AND empresa_id=%s",
            (row["empleado_id"], who["empresa_id"]),
        )
    may_review = (
        who["review"]
        and (
            who["review_global"]
            or (
                who["empleado_id"]
                and boss["reporta_a_empleado_id"] == who["empleado_id"]
            )
        )
        and row["empleado_id"] != who["empleado_id"]
    )
    return render_template(
        "reintegros/detail.html",
        row=row,
        who=who,
        may_review=may_review,
        today=service.now_local().date(),
    )


@reintegros_web_bp.post("/solicitudes/<int:rid>/acciones")
@permission_required("reintegros", "ver")
def action(rid):
    who = actor()
    data = request.form.to_dict()
    if data.get("accion") == "resolver":
        row = service.detail(who, rid)
        data["decisiones"] = [
            dict(
                id=g["id"],
                decision=request.form.get("decision_" + str(g["id"])),
                motivo=request.form.get("motivo_" + str(g["id"]), ""),
            )
            for g in row["gastos"]
        ]
    service.transition(who, rid, data)
    flash("Solicitud actualizada.", "success")
    return redirect(url_for("reintegros_web.detail", rid=rid))


@reintegros_web_bp.get("/fotos/<int:fid>")
@permission_required("reintegros", "ver")
def photo(fid):
    return private_photo(service.photo(actor(), fid))


@reintegros_web_bp.route("/categorias", methods=["GET", "POST"])
@permission_required("reintegros", "ver")
def categories():
    who = actor()
    if not who["review_global"] or not can_access_module(
        who["user_id"], "reintegros", "editar"
    ):
        abort(403)
    error = None
    status = 200
    if request.method == "POST":
        try:
            service.save_category(who["empresa_id"], who["user_id"], request.form)
            flash("Concepto guardado.", "success")
            return redirect(url_for("reintegros_web.categories"))
        except service.Error as exc:
            error = str(exc)
            status = exc.status
        except IntegrityError as exc:
            if exc.errno != 1062:
                raise
            error = "Ya existe un concepto con ese nombre. Usá otro nombre o editá el existente."
            status = 409
    return render_template(
        "reintegros/categories.html",
        items=service.categories(who["empresa_id"]),
        error=error,
        values=request.form if request.method == "POST" else {},
    ), status


@reintegros_web_bp.get("/exportar.csv")
@permission_required("reintegros", "ver")
@permission_required("reintegros", "exportar")
def export():
    who = actor()
    filters = request.args.to_dict()
    filters["page"] = 1
    result = service.history(who, filters, per_page=10001)
    if result["total"] > 10000:
        raise service.Error(
            "Acote las fechas: máximo 10.000 solicitudes por exportación."
        )
    output = io.StringIO()
    writer = csv.writer(output, delimiter=";")
    writer.writerow(
        [
            "Solicitud",
            "Legajo",
            "Empleado",
            "Estado",
            "Fecha solicitud",
            "Moneda",
            "Solicitado",
            "Aprobado",
        ]
    )
    for r in result["items"]:
        writer.writerow(
            [
                csv_safe(r[k])
                for k in (
                    "id",
                    "legajo",
                    "empleado_nombre",
                    "estado",
                    "creado_at",
                    "moneda",
                    "total_solicitado",
                    "total_aprobado",
                )
            ]
        )
    return Response(
        "\ufeff" + output.getvalue(),
        content_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": "attachment; filename=reintegros.csv",
            "Cache-Control": "private, no-store",
        },
    )
