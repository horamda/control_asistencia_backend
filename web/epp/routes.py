"""EPP web and employee API. All authorization is checked again by the service."""

from utils.export_safety import SafeCsvWriter
import csv
import io
import json
from uuid import uuid4
from flask import (
    Blueprint,
    request,
    session,
    jsonify,
    render_template,
    redirect,
    url_for,
    flash,
    abort,
    send_file,
    Response,
)
from mysql.connector import IntegrityError, ProgrammingError
from web.auth.decorators import permission_required, can_access_module, _cached_web_user
from utils.jwt_guard import mobile_auth_required
from routes.carga_routes import employee, serialize, private_photo
from services import avisos_push, epp_service as s
from web.carga.carga_routes import csv_safe

web = Blueprint("epp_web", __name__, url_prefix="/epp")
mobile = Blueprint("epp_mobile", __name__, url_prefix="/api/v1/mobile/epp")


def actor():
    if request.blueprint == "epp_mobile":
        emp = employee()
        return dict(
            mode="empleado", empresa_id=emp["empresa_id"], empleado_id=emp["id"]
        )
    user = _cached_web_user(session.get("user_id"))
    if not user or not user.get("activo"):
        abort(403)
    uid = user["id"]
    return dict(
        mode="web",
        empresa_id=user["empresa_id"],
        empleado_id=user.get("empleado_id"),
        user_id=uid,
        **{"global": can_access_module(uid, "epp_responsables", "ver")},
        approve=can_access_module(uid, "epp", "aprobar"),
        deliver=can_access_module(uid, "epp_responsables", "crear"),
    )


def data():
    if request.is_json:
        value = request.get_json(silent=True)
    elif request.form.get("payload"):
        try:
            value = json.loads(request.form["payload"])
        except ValueError:
            raise s.Error("Datos JSON inválidos.")
    else:
        value = request.form.to_dict()
    if not isinstance(value, dict):
        raise s.Error("Envíe un objeto JSON.")
    return value


def eligibility(who, selected=None):
    """Sectores con sus puestos reales (segun los empleados activos, incluidos
    puestos adicionales) para el formulario de disponibilidad del catalogo."""
    with s.db.transaction(read_only=True) as c:
        sectores = s.db.all_rows(c, "SELECT id,nombre FROM sectores WHERE empresa_id=%s ORDER BY nombre", (who["empresa_id"],))
        puestos = {r["id"]: r["nombre"] for r in s.db.all_rows(
            c, "SELECT id,nombre FROM puestos WHERE empresa_id=%s", (who["empresa_id"],))}
        pares = s.db.all_rows(
            c,
            "SELECT id empleado_id,sector_id,puesto_id FROM empleados WHERE empresa_id=%s AND activo=1"
            " UNION SELECT ep.empleado_id,ep.sector_id,ep.puesto_id FROM empleado_puestos ep"
            " JOIN empleados e ON e.id=ep.empleado_id WHERE e.empresa_id=%s AND e.activo=1 AND ep.activo=1",
            (who["empresa_id"], who["empresa_id"]),
        )
    por_empleado, por_par, por_sector = {}, {}, {}
    for r in pares:
        por_empleado.setdefault(r["empleado_id"], set()).add((r["sector_id"], r["puesto_id"]))
    for empleado_id, combos in por_empleado.items():
        for sec, pue in combos:
            por_par.setdefault((sec, pue), set()).add(empleado_id)
        for sec in {sec for sec, _ in combos}:
            por_sector[sec] = por_sector.get(sec, 0) + 1
    marcadas = {(r.get("s"), r.get("p")) for r in (selected or {}).get("habilitaciones") or []}
    grupos = []
    for sector in sectores:
        ids = {pue for sec, pue in por_par if sec == sector["id"]}
        ids |= {pue for sec, pue in marcadas if sec == sector["id"] and pue}  # reglas sin empleados hoy
        grupos.append(dict(
            id=sector["id"], nombre=sector["nombre"], empleados=por_sector.get(sector["id"], 0),
            todo=(sector["id"], None) in marcadas,
            puestos=sorted(
                (dict(id=pue, nombre=puestos.get(pue, f"#{pue}"), empleados=len(por_par.get((sector["id"], pue), ())),
                      marcado=(sector["id"], pue) in marcadas) for pue in ids if pue),
                key=lambda x: x["nombre"],
            ),
        ))
    cualquier = [dict(id=pue, nombre=puestos.get(pue, f"#{pue}")) for sec, pue in sorted(marcadas, key=str) if sec is None and pue]
    return dict(
        sectores=[g for g in grupos if g["empleados"] or g["todo"] or g["puestos"]],
        cualquier_sector=cualquier,
        # Combinaciones de cada empleado (sin datos personales) para la cobertura en vivo.
        empleados=[sorted(f"{sec}:{pue}" for sec, pue in combos) for combos in por_empleado.values()],
    )


def options(who):
    with s.db.transaction(read_only=True) as c:
        scope = "" if who["global"] else " AND reporta_a_empleado_id=%s"
        args = (
            (who["empresa_id"],)
            if who["global"]
            else (who["empresa_id"], who.get("empleado_id") or -1)
        )
        return dict(
            empleados=s.db.all_rows(
                c,
                "SELECT id,legajo,nombre,apellido FROM empleados WHERE empresa_id=%s AND activo=1"
                + scope
                + " ORDER BY apellido,nombre",
                args,
            ),
            sectores=s.db.all_rows(
                c,
                "SELECT id,nombre FROM sectores WHERE empresa_id=%s ORDER BY nombre",
                (who["empresa_id"],),
            ),
            puestos=s.db.all_rows(
                c,
                "SELECT id,nombre FROM puestos WHERE empresa_id=%s ORDER BY nombre",
                (who["empresa_id"],),
            ),
            sucursales=s.db.all_rows(
                c,
                "SELECT id,nombre FROM sucursales WHERE empresa_id=%s ORDER BY nombre",
                (who["empresa_id"],),
            ),
        )


def render(name, **context):
    return render_template("epp/" + name + ".html", who=actor(), **context)


@web.errorhandler(s.Error)
@mobile.errorhandler(s.Error)
def invalid(error):
    if request.blueprint == "epp_mobile":
        return jsonify(error=str(error)), error.status
    return render("error", message=str(error)), error.status


@web.errorhandler(ProgrammingError)
@mobile.errorhandler(ProgrammingError)
def missing(error):
    if error.errno not in (1146, 1054):
        raise error
    return invalid(s.Error("EPP requiere instalar la migración 20261008_02_epp y 20261013_01_epp_conceptos.", 503))


@web.errorhandler(IntegrityError)
@mobile.errorhandler(IntegrityError)
def conflict(error):
    return invalid(
        s.Error(
            "El nombre o identificador ya existe. Actualice antes de reintentar.", 409
        )
    )


@web.after_request
@mobile.after_request
def private(response):
    response.headers["Cache-Control"] = "private, no-store"
    return response


@web.get("/")
@permission_required("epp", "ver")
def index():
    return render(
        "index", result=s.history(actor(), request.args), options=options(actor())
    )


@web.route("/catalogo", methods=["GET", "POST"])
@permission_required("epp_responsables", "editar")
def catalog():
    who = actor()
    if request.method == "POST":
        values = request.form.to_dict()
        values["talles"] = [
            v.strip() for v in request.form.get("talles", "").split(",") if v.strip()
        ]
        values["habilitaciones"] = request.form.getlist("habilitacion")
        s.save_article(who, values, request.files.get("imagen"))
        flash(
            "Artículo guardado. El historial conserva los talles anteriores.", "success"
        )
        return redirect(url_for("epp_web.catalog"))
    rows = s.catalogs(who)
    selected = next(
        (r for r in rows if str(r["id"]) == request.args.get("editar")), None
    )
    return render(
        "catalog",
        items=rows,
        selected=selected,
        options=options(who),
        eligibility=eligibility(who, selected),
        categories=s.categories(who),
    )


@web.route("/talles", methods=["GET", "POST"])
@permission_required("epp", "editar")
def sizes():
    who = actor()
    eid = request.values.get("empleado_id", type=int)
    if request.method == "POST":
        d = data()
        d["eliminar"] = d.get("accion") == "eliminar"
        s.save_size(who, eid, d)
        flash("Talles actualizados.", "success")
        return redirect(url_for("epp_web.sizes", empleado_id=eid))
    search = request.args.get("q", "").strip()[:120]
    return render(
        "sizes",
        staff=s.staff_sizes(who, search) if not eid else [],
        search=search,
        options=options(who),
        eid=eid,
        items=s.catalogs(who, eid) if eid else [],
        sizes=s.sizes(who, eid) if eid else [],
    )


@web.route("/nuevo", methods=["GET", "POST"])
@permission_required("epp", "crear")
def create():
    who = actor()
    eid = request.values.get("empleado_id", type=int)
    if request.method == "POST":
        values = data()
        pid, _ = s.create(who, eid, values)
        flash("Pedido registrado para aprobación.", "success")
        return redirect(url_for("epp_web.detail", pid=pid))
    return render(
        "form",
        options=options(who),
        eid=eid,
        items=s.catalogs(who, eid) if eid else [],
        sizes=s.sizes(who, eid) if eid else [],
        token=str(uuid4()),
        concepts=s.replacement_concepts(who, active_only=True),
    )


HISTORIAL_ACCIONES = {
    "crear": "Pedido creado",
    "editar_pedido": "Pedido editado",
    "enviar": "Enviado a aprobación",
    "resolver": "Pedido resuelto",
    "cancelar": "Pedido cancelado",
    "entregar": "Entrega registrada",
    "anular_entrega": "Entrega anulada",
    "planilla_firmada": "Planilla firmada",
}


def _detalle_web(pid):
    """Detalle con nombres legibles (sucursal, usuarios) e historial sin JSON crudo."""
    row = s.detail(actor(), pid)
    with s.db.transaction(read_only=True) as c:
        sucursal = s.db.one(c, "SELECT nombre FROM sucursales WHERE id=%s", (row.get("sucursal_id"),))             if row.get("sucursal_id") else None
        ids = sorted({h["usuario_id"] for h in row["historial"] if h.get("usuario_id")})
        usuarios = {u["id"]: u["usuario"] for u in s.db.all_rows(
            c, f"SELECT id, usuario FROM usuarios WHERE id IN ({', '.join(['%s'] * len(ids))})", tuple(ids))} if ids else {}
    row["sucursal_nombre"] = sucursal["nombre"] if sucursal else None
    for h in row["historial"]:
        try:
            datos = json.loads(h.get("datos") or "{}")
        except ValueError:
            datos = {}
        h["accion_label"] = HISTORIAL_ACCIONES.get(h["accion"], h["accion"].replace("_", " ").capitalize())
        h["quien"] = usuarios.get(h.get("usuario_id")) or ("App del empleado" if not h.get("usuario_id") else f"Usuario #{h['usuario_id']}")
        h["detalle"] = datos.get("motivo") if isinstance(datos, dict) else None
    for i in row["items"]:
        i["pendiente_entrega"] = max(0, int(i["aprobada"] or 0) - int(i["entregada"] or 0))
    row["pendiente_total"] = sum(i["pendiente_entrega"] for i in row["items"])
    return row


@web.get("/pedidos/<int:pid>")
@permission_required("epp", "ver")
def detail(pid):
    return render(
        "detail",
        row=_detalle_web(pid),
        token=str(uuid4()),
        today=s.now_local().date(),
    )


def _mensaje_resolucion(cantidades, items):
    pedidas = {str(i["id"]): int(i["cantidad"]) for i in items}
    aprobadas = {k: int(v) for k, v in cantidades.items() if str(v).isdigit()}
    if aprobadas and all(v == 0 for v in aprobadas.values()):
        return "Pedido rechazado."
    if all(aprobadas.get(k) == v for k, v in pedidas.items()):
        return "Pedido aprobado. Ya se puede registrar la entrega."
    return "Pedido aprobado con cambios. El solicitante puede ver el motivo."


@web.post("/pedidos/<int:pid>/acciones")
@permission_required("epp", "editar")
def action(pid):
    values = data()
    if values.get("accion") == "resolver" and not actor()["approve"]:
        abort(403)
    mensaje = {"cancelar": "Pedido cancelado.", "enviar": "Pedido enviado a aprobación."}.get(
        values.get("accion"), "Pedido actualizado.")
    if values.get("accion") == "resolver":
        values["cantidades"] = {
            k[9:]: v for k, v in request.form.items() if k.startswith("cantidad_")
        }
        mensaje = _mensaje_resolucion(values["cantidades"], s.detail(actor(), pid)["items"])
    s.action(actor(), pid, values)
    flash(mensaje, "success")
    return redirect(url_for("epp_web.detail", pid=pid))


@web.post("/pedidos/<int:pid>/entregas")
@permission_required("epp_responsables", "crear")
def deliver(pid):
    values = data()
    values["cantidades"] = {
        k[9:]: v for k, v in request.form.items() if k.startswith("cantidad_")
    }
    did, _ = s.deliver(actor(), pid, values)
    flash("Entrega registrada. Descargá la planilla para firmar.", "success")
    return redirect(url_for("epp_web.receipt_view", did=did))


@web.route("/entregas/<int:did>", methods=["GET", "POST"])
@permission_required("epp", "ver")
def receipt_view(did):
    if request.method == "POST":
        if not actor()["deliver"]:
            abort(403)
        s.delivery_update(actor(), did, data(), request.files.get("firma"))
        flash("Entrega actualizada.", "success")
        return redirect(url_for("epp_web.receipt_view", did=did))
    return render("receipt", row=s.receipt(actor(), did))


def pdf(who, did):
    from reportlab.lib import colors
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.platypus import (
        SimpleDocTemplate,
        Paragraph,
        Spacer,
        Table,
        TableStyle,
    )
    from xml.sax.saxutils import escape

    row = s.receipt(who, did)
    p = row["pedido"]
    company = row.get("empresa") or {}
    buffer = io.BytesIO()
    styles = getSampleStyleSheet()
    para = lambda text: Paragraph(escape(str(text)), styles["BodyText"])
    blocks = [
        Paragraph("Constancia de entrega de EPP y vestimenta", styles["Title"]),
        Spacer(1, 16),
        para(
            f"Entrega #{did} | Fecha: {row['fecha']} | Empresa: {company.get('razon_social') or p['empresa_id']} | Sucursal: {row['sucursal']}"
        ),
        para(
            f"Empleado: {p['empleado_nombre']} | Legajo: {p['legajo']} | Responsable ID: {row['responsable_id']}"
        ),
        Spacer(1, 16),
    ]
    if row["anulada"]:
        blocks.append(Paragraph("ENTREGA ANULADA", styles["Heading1"]))
    cells = [[para(t) for t in ["Artículo", "Talle / medida", "Cantidad"]]]
    cells.extend(
        [
            [
                para(i["nombre"]),
                para(i["talle"] + " " + i["medidas"]),
                para(i["cantidad"]),
            ]
            for i in row["items"]
        ]
    )
    table = Table(cells, colWidths=[240, 180, 60], repeatRows=1)
    table.setStyle(
        TableStyle(
            [
                ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#e8eef5")),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 10),
            ]
        )
    )
    blocks.extend(
        [
            table,
            Spacer(1, 16),
            para("Observaciones: " + row["observaciones"]),
            Spacer(1, 50),
            para(
                "Firma del empleado: ____________________   Aclaración: ____________________"
            ),
            Spacer(1, 30),
            para("Firma de quien entrega: ____________________"),
            Spacer(1, 20),
            para(
                "Constancia interna de recepción de los artículos detallados. No sustituye registros específicos que correspondan a la empresa."
            ),
        ]
    )
    SimpleDocTemplate(buffer, title=f"Entrega EPP {did}").build(blocks)
    buffer.seek(0)
    return send_file(
        buffer,
        mimetype="application/pdf",
        as_attachment=True,
        download_name=f"entrega_epp_{did}.pdf",
        max_age=0,
    )


@web.get("/entregas/<int:did>/pdf")
@permission_required("epp", "ver")
def receipt_pdf(did):
    return pdf(actor(), did)


@web.get("/imagenes/<kind>/<int:rid>")
@permission_required("epp", "ver")
def image(kind, rid):
    if kind not in ("articulos", "firmas"):
        abort(404)
    return private_photo(s.image(actor(), kind, rid))


@web.get("/reporte")
@permission_required("epp", "ver")
def report():
    result = s.report(actor(), request.args)
    if request.args.get("formato") == "csv":
        if not can_access_module(actor()["user_id"], "epp", "exportar"):
            abort(403)
        stream = io.StringIO()
        writer = SafeCsvWriter(stream, delimiter=";")
        keys = [
            "legajo",
            "empleado_nombre",
            "sucursal_id",
            "nombre",
            "categoria",
            "talle",
            "medidas",
            "cantidad",
        ]
        writer.writerow(keys)
        for row in result["items"]:
            writer.writerow([csv_safe(row[k]) for k in keys])
        return Response(
            "\ufeff" + stream.getvalue(),
            mimetype="text/csv",
            headers={"Content-Disposition": "attachment; filename=epp_anual.csv"},
        )
    return render("report", result=result, options=options(actor()))


@mobile.get("/config")
@mobile_auth_required
def config_mobile():
    who = actor()
    return jsonify(
        serialize(
            dict(
                version_contrato="1.37.0",
                conceptos_reposicion=s.replacement_concepts(who, active_only=True),
                articulos=s.catalogs(who, who["empleado_id"]),
                talles=s.sizes(who, who["empleado_id"]),
                max_items=50,
            )
        )
    )


@mobile.route("/talles", methods=["GET", "PUT"])
@mobile_auth_required
def sizes_mobile():
    who = actor()
    if request.method == "PUT":
        s.save_size(who, who["empleado_id"], data())
    return jsonify(serialize(dict(items=s.sizes(who, who["empleado_id"]))))


@mobile.route("/pedidos", methods=["GET", "POST"])
@mobile_auth_required
def orders_mobile():
    who = actor()
    if request.method == "GET":
        return jsonify(serialize(s.history(who, request.args)))
    pid, created = s.create(who, who["empleado_id"], data())
    if created:
        avisos_push.revision_epp(pid)  # solo si quedo pendiente (no borrador)
    return jsonify(serialize(dict(pedido=s.detail(who, pid), repetido=not created))), (
        201 if created else 200
    )


@mobile.get("/pedidos/<int:pid>")
@mobile_auth_required
def detail_mobile(pid):
    return jsonify(serialize(s.detail(actor(), pid)))


@mobile.post("/pedidos/<int:pid>/acciones")
@mobile_auth_required
def action_mobile(pid):
    s.action(actor(), pid, data())
    avisos_push.revision_epp(pid)  # un borrador enviado pasa a pendiente
    return jsonify(serialize(s.detail(actor(), pid)))


@mobile.get("/entregas/<int:did>/pdf")
@mobile_auth_required
def pdf_mobile(did):
    return pdf(actor(), did)


@mobile.get("/imagenes/<kind>/<int:rid>")
@mobile_auth_required
def image_mobile(kind, rid):
    if kind not in ("articulos", "firmas"):
        abort(404)
    return private_photo(s.image(actor(), kind, rid))


@mobile.get("/resumen")
@mobile_auth_required
def summary_mobile():
    return jsonify(serialize(s.report(actor(), request.args)))


@web.route("/pedidos/<int:pid>/editar", methods=["GET", "POST"])
@permission_required("epp", "editar")
def edit(pid):
    who = actor()
    row = s.detail(who, pid)
    if row["estado"] not in ("borrador", "pendiente"):
        raise s.Error("Solo se editan borradores o pedidos pendientes.", 409)
    if request.method == "POST":
        s.edit_order(who, pid, data())
        flash("Pedido actualizado.", "success")
        return redirect(url_for("epp_web.detail", pid=pid))
    return render(
        "form",
        options=options(who),
        eid=row["empleado_id"],
        items=s.catalogs(who, row["empleado_id"]),
        sizes=s.sizes(who, row["empleado_id"]),
        token=str(uuid4()),
        editing=row,
        concepts=s.replacement_concepts(who, active_only=True),
    )


@mobile.put("/pedidos/<int:pid>")
@mobile_auth_required
def edit_mobile(pid):
    s.edit_order(actor(), pid, data())
    avisos_push.revision_epp(pid)
    return jsonify(serialize(s.detail(actor(), pid)))


@web.route("/categorias", methods=["GET", "POST"])
@permission_required("epp_responsables", "editar")
def categories():
    if request.method == "POST":
        values = data()
        try:
            s.save_category(actor(), values)
        except s.Error as error:
            return render("categories", items=s.categories(actor()), error=str(error), values=values), error.status
        flash("Categoría actualizada." if values.get("id") else "Categoría creada.", "success")
        return redirect(url_for("epp_web.categories"))
    return render("categories", items=s.categories(actor()))


@mobile.errorhandler(404)
def mobile_not_found(error):
    return jsonify(error="Recurso no encontrado."), 404


@web.errorhandler(413)
@mobile.errorhandler(413)
def too_large(error):
    return invalid(
        s.Error("Envío demasiado grande. Cada imagen admite hasta 5 MB.", 413)
    )


@web.route("/conceptos-reposicion", methods=["GET", "POST"])
@permission_required("epp_responsables", "editar")
def replacement_concepts():
    who = actor()
    if request.method == "POST":
        values = data()
        try:
            if values.get("accion") == "eliminar":
                s.delete_replacement_concept(who, values.get("id"))
            else:
                s.save_replacement_concept(who, values)
        except s.Error as error:
            # Como en Conceptos de viaticos: el dialogo se reabre con el error y lo cargado.
            return render("replacement_concepts", items=s.replacement_concepts(who), error=str(error),
                          values=values), error.status
        nuevo = not values.get("id")
        flash("Concepto creado." if nuevo else "Concepto actualizado.", "success")
        return redirect(url_for("epp_web.replacement_concepts"))
    return render("replacement_concepts", items=s.replacement_concepts(who))


@mobile.get("/conceptos-reposicion")
@mobile_auth_required
def replacement_concepts_mobile():
    return jsonify(items=s.replacement_concepts(actor(), active_only=True))
