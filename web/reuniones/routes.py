"""Reuniones: panel administrativo (CRUD, QR, asistencia, estadisticas) y API del empleado."""

import csv
import datetime as dt
import io

from flask import (Blueprint, current_app, Response, abort, flash, jsonify, redirect, render_template, request, session,
                   url_for)
from mysql.connector import ProgrammingError

from repositories import carga_repository as db
from routes.carga_routes import employee, serialize
from services import reunion_service as s
from services.carga_service import now_local
from services.svg_chart_service import line_chart
from utils.audit import log_audit
from utils.jwt_guard import mobile_auth_required
from utils.qr import build_qr_png_base64
from web.auth.decorators import _cached_web_user, permission_required
from web.carga.carga_routes import csv_safe
from web.epp.routes import eligibility

web = Blueprint("reuniones", __name__, url_prefix="/reuniones")
mobile = Blueprint("reuniones_mobile", __name__, url_prefix="/api/v1/mobile/reuniones")

ESTADO_LABEL = {"presente": "Presente", "tarde": "Tarde", "ausente": "Ausente", "justificado": "Justificado",
                "pendiente": "Pendiente", "cancelada": "Cancelada"}


def who():
    user = _cached_web_user(session.get("user_id"))
    if not user or not user.get("activo"):
        abort(403)
    return dict(empresa_id=user["empresa_id"], user_id=user["id"])


def _fecha(raw, default=None):
    try:
        return dt.date.fromisoformat(str(raw)) if raw else default
    except ValueError:
        return default


def _periodo(dias_default):
    hasta = _fecha(request.args.get("hasta"), now_local().date())
    desde = _fecha(request.args.get("desde"), hasta - dt.timedelta(days=dias_default - 1))
    if desde > hasta:
        desde, hasta = hasta, desde
    return desde, hasta


@web.app_template_filter("estado_reunion")
def estado_reunion(value):
    return ESTADO_LABEL.get(value, value or "")


@web.app_template_filter("hora")
def hora(value):
    return s._hhmm(s._time(value)) if value not in (None, "") else ""


@web.app_template_filter("dia_semana")
def dia_semana(value):
    return s.DIAS[value.weekday()] if value else ""


@web.errorhandler(s.Error)
@mobile.errorhandler(s.Error)
def invalid(error):
    if request.blueprint == "reuniones_mobile":
        return jsonify(error=str(error)), error.status
    flash(str(error), "error")
    if request.method == "POST" and request.endpoint not in ("reuniones.nueva", "reuniones.editar"):
        return redirect(request.referrer or url_for("reuniones.index"))
    return render_template("reuniones/error.html", message=str(error)), error.status


@web.errorhandler(ProgrammingError)
@mobile.errorhandler(ProgrammingError)
def missing(error):
    if error.errno not in (1146, 1054):
        raise error
    return invalid(s.Error("Reuniones requiere la migración 20261016_01_reuniones (se aplica al reiniciar).", 503))


@web.after_request
@mobile.after_request
def private(response):
    response.headers["Cache-Control"] = "private, no-store"
    return response


# --- Panel: listado y CRUD -------------------------------------------------------------

@web.get("/")
@permission_required("reuniones", "ver")
def index():
    q = (request.args.get("q") or "").strip() or None
    estado = request.args.get("estado") or None
    sucursal = request.args.get("sucursal", type=int)
    actor = who()
    data = s.listado(actor, q=q, estado=estado, sucursal_id=sucursal)
    return render_template("reuniones/index.html", **data, sucursales=s.sucursales(actor),
                           superpuestas=s.reuniones_con_superposicion(actor),
                           filtros=dict(q=q or "", estado=estado or "", sucursal=sucursal))


def _form_data():
    form = request.form
    sedes = [dict(sucursal_id=sid, lugar=form.get(f"sede_lugar_{sid}"), hora_inicio=form.get(f"sede_hora_{sid}"))
             for sid in form.getlist("sede")]
    return dict(form.to_dict(), dias_semana=form.getlist("dias_semana"), reglas=form.getlist("regla"),
                empleados=form.getlist("empleado"), sedes=sedes)


def _form_context(actor, reunion=None, data=None):
    reglas = reunion.get("reglas", []) if reunion else []
    seleccion = {"habilitaciones": [{"s": r["sector_id"], "p": r["puesto_id"]} for r in reglas
                                    if r["empleado_id"] is None and (r["sector_id"] or r["puesto_id"])]}
    if data:  # reintento tras un error: se conserva lo elegido
        seleccion = {"habilitaciones": []}
        for regla in data.get("reglas") or []:
            sector, _, puesto = str(regla).partition(":")
            if regla != "todos":
                seleccion["habilitaciones"].append({"s": int(sector) if sector.isdigit() else None,
                                                    "p": int(puesto) if puesto.isdigit() else None})
    with db.transaction(read_only=True) as c:
        empleados = db.all_rows(c, "SELECT e.id, e.legajo, e.apellido, e.nombre, e.sucursal_id, s.nombre AS sector_nombre,"
                                   " su.nombre AS sucursal_nombre FROM empleados e"
                                   " LEFT JOIN sectores s ON s.id=e.sector_id LEFT JOIN sucursales su ON su.id=e.sucursal_id"
                                   " WHERE e.empresa_id=%s AND e.activo=1"
                                   " ORDER BY e.apellido, e.nombre", (actor["empresa_id"],))
        por_sucursal = {row["sucursal_id"]: int(row["n"]) for row in db.all_rows(
            c, "SELECT sucursal_id, COUNT(*) AS n FROM empleados WHERE empresa_id=%s AND activo=1 GROUP BY sucursal_id",
            (actor["empresa_id"],))}
        pares = db.all_rows(c, "SELECT id empleado_id, sector_id, puesto_id FROM empleados WHERE empresa_id=%s AND activo=1"
                               " UNION SELECT ep.empleado_id, ep.sector_id, ep.puesto_id FROM empleado_puestos ep"
                               " JOIN empleados e ON e.id=ep.empleado_id WHERE e.empresa_id=%s AND e.activo=1 AND ep.activo=1",
                            (actor["empresa_id"], actor["empresa_id"]))
    combos = {}
    for par in pares:
        combos.setdefault(par["empleado_id"], set()).add(f"{par['sector_id']}:{par['puesto_id']}")
    # Combinaciones sector:puesto por empleado (sin datos personales) para la cobertura en vivo.
    sucursal_de = {e["id"]: e["sucursal_id"] for e in empleados}
    cobertura = [{"id": eid, "c": sorted(valores), "s": sucursal_de.get(eid)} for eid, valores in combos.items()]
    if data:
        sedes = {int(x["sucursal_id"]): x for x in data.get("sedes") or [] if str(x.get("sucursal_id", "")).isdigit()}
    else:
        sedes = {x["sucursal_id"]: dict(x, hora_inicio=s._hhmm(s._time(x["hora_inicio"])) if x.get("hora_inicio") else "")
                 for x in (reunion.get("sedes") or [] if reunion else [])}
    sucursales = [dict(x, empleados=por_sucursal.get(x["id"], 0), sede=sedes.get(x["id"])) for x in s.sucursales(actor)]
    if data:
        marcados = {int(x) for x in data.get("empleados") or [] if str(x).isdigit()}
        todos = "todos" in (data.get("reglas") or [])
    else:
        marcados = {r["empleado_id"] for r in reglas if r["empleado_id"]}
        todos = any(r["empleado_id"] is None and r["sector_id"] is None and r["puesto_id"] is None for r in reglas)
    return dict(eligibility=eligibility(actor, seleccion), empleados=empleados, marcados=marcados, todos=todos,
                cobertura=cobertura, sucursales=sucursales, dias=s.DIAS, semanas=s.SEMANAS)


def _valores(reunion=None, data=None):
    if data:
        v = dict(data)
        v["dias_semana"] = [int(d) for d in data.get("dias_semana") or [] if str(d).isdigit()]
        return v
    if not reunion:
        return dict(frecuencia="semanal", dias_semana=[0], hora_inicio="09:00", duracion_min=60, tolerancia_antes_min=15,
                    tarde_despues_min=10, cierre_despues_min="", qr_modo="fijo", feriado_accion="posponer", activa=1,
                    mensual_tipo="dia", dia_mes=1,
                    semana_mes=1, dia_semana_mes=0, fecha_inicio=now_local().date().isoformat())
    dias = s._dias(reunion.get("dias_semana"))
    return dict(reunion, hora_inicio=s._hhmm(s._time(reunion["hora_inicio"])), dias_semana=dias,
                dia_semana_mes=dias[0] if dias else 0, cierre_despues_min=reunion.get("cierre_despues_min") or "",
                mensual_tipo=reunion.get("mensual_tipo") or "dia", dia_mes=reunion.get("dia_mes") or 1,
                semana_mes=reunion.get("semana_mes") or 1, fecha_inicio=s._iso(s._date(reunion["fecha_inicio"])),
                fecha_fin=s._iso(s._date(reunion["fecha_fin"])) if reunion.get("fecha_fin") else "")


def _avisar_superposiciones(actor, reunion_id):
    """No bloquea (a veces es intencional), pero avisa con quien se pisa y a cuanta gente afecta."""
    try:
        lista = s.conflictos(actor, reunion_id)
    except Exception:
        current_app.logger.warning("reunion_superposiciones_error", exc_info=True)
        return
    for g in lista[:3]:
        fechas = "1 fecha" if g["fechas"] == 1 else f"{g['fechas']} fechas"
        gente = "1 convocado" if g["empleados"] == 1 else f"{g['empleados']} convocados"
        flash(f"Atención: se superpone con «{g['nombre']}» ({g['horario']}) en {fechas} de los próximos "
              f"{s.DIAS_SUPERPOSICION} días, para {gente} en común. Quien asista a una tendrá justificada la otra.",
              "warning")


@web.route("/nueva", methods=["GET", "POST"])
@permission_required("reuniones", "crear")
def nueva():
    actor = who()
    if request.method == "POST":
        data = _form_data()
        try:
            rid = s.guardar(actor, data)
        except s.Error as error:
            flash(str(error), "error")
            return render_template("reuniones/form.html", reunion=None, v=_valores(data=data),
                                   **_form_context(actor, data=data)), 400
        log_audit(session, "reunion_crear", "reuniones", rid)
        flash("Reunión creada. Ya podés imprimir su QR.", "success")
        _avisar_superposiciones(actor, rid)
        return redirect(url_for("reuniones.detalle", reunion_id=rid))
    return render_template("reuniones/form.html", reunion=None, v=_valores(), **_form_context(actor))


@web.route("/<int:reunion_id>/editar", methods=["GET", "POST"])
@permission_required("reuniones", "editar")
def editar(reunion_id):
    actor = who()
    with db.transaction(read_only=True) as c:
        reunion = s.obtener(c, actor, reunion_id)
        reunion["reglas"] = s.reglas(c, reunion_id)
        reunion["sedes"] = s.sedes(c, reunion_id)
    if request.method == "POST":
        data = _form_data()
        try:
            s.guardar(actor, data, reunion_id)
        except s.Error as error:
            flash(str(error), "error")
            return render_template("reuniones/form.html", reunion=reunion, v=_valores(data=data),
                                   **_form_context(actor, reunion, data)), 400
        log_audit(session, "reunion_editar", "reuniones", reunion_id)
        flash("Reunión actualizada.", "success")
        _avisar_superposiciones(actor, reunion_id)
        return redirect(url_for("reuniones.detalle", reunion_id=reunion_id))
    return render_template("reuniones/form.html", reunion=reunion, v=_valores(reunion), **_form_context(actor, reunion))


@web.post("/<int:reunion_id>/eliminar")
@permission_required("reuniones", "eliminar")
def eliminar(reunion_id):
    s.eliminar(who(), reunion_id)
    log_audit(session, "reunion_eliminar", "reuniones", reunion_id)
    flash("Reunión eliminada.", "success")
    return redirect(url_for("reuniones.index"))


# --- Panel: detalle, ocurrencias y QR ------------------------------------------------------

def _grafico(ocurrencias):
    # Una fecha puede tener varias sedes: se suman para un solo punto por fecha.
    por_fecha = {}
    for o in ocurrencias:
        if o["estado"] == "cancelada" or not o["convocatorias"]:
            continue
        acumulado = por_fecha.setdefault(o["fecha"], dict.fromkeys(s._CONTEOS, 0))
        for k in s._CONTEOS:
            acumulado[k] += o[k]
    puntos = [dict(s._tasas(v), fecha=f) for f, v in sorted(por_fecha.items())][-30:]
    salto = max(1, len(puntos) // 8)
    labels = [{"label": f"{o['fecha']:%d/%m}" if i % salto == 0 or i == len(puntos) - 1 else "", "sub": ""}
              for i, o in enumerate(puntos)]
    chart = line_chart(labels, [{"key": "asistencia", "name": "Asistencia",
                                 "values": [o["asistencia_pct"] for o in puntos]}], y_max=100)
    tips = [{"title": f"{o['fecha']:%d/%m/%Y}",
             "rows": [{"key": "asistencia", "name": "Asistencia",
                       "value": "s/d" if o["asistencia_pct"] is None else f"{o['asistencia_pct']:g}%"}],
             "note": f"{o['asistidas']} de {o['convocatorias'] - o['justificados']} · {o['tarde']} tarde",
             "aria": f"{o['fecha']:%d/%m}: asistencia {o['asistencia_pct']}%"} for o in puntos]
    return chart, tips


@web.get("/<int:reunion_id>")
@permission_required("reuniones", "ver")
def detalle(reunion_id):
    desde, hasta = _periodo(90)
    actor = who()
    data = s.detalle(actor, reunion_id, desde=desde, hasta=hasta, sucursal_id=request.args.get("sucursal", type=int))
    chart, tips = _grafico(data["ocurrencias"])
    return render_template("reuniones/detalle.html", **data, chart=chart, tips=tips, hoy=now_local().date(),
                           superposiciones=s.conflictos(actor, reunion_id), dias_superposicion=s.DIAS_SUPERPOSICION)


@web.get("/<int:reunion_id>/exportar.csv")
@permission_required("reuniones", "exportar")
def exportar(reunion_id):
    desde, hasta = _periodo(90)
    data = s.detalle(who(), reunion_id, desde=desde, hasta=hasta, sucursal_id=request.args.get("sucursal", type=int))
    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow(["Apellido", "Nombre", "Legajo", "Sector", "Sucursal", "Convocatorias", "Presentes", "Tarde", "Ausentes",
                     "Justificados", "Asistencia %", "Puntualidad %"])
    for row in data["ranking"]:
        writer.writerow([csv_safe(row[k]) for k in ("apellido", "nombre", "legajo", "sector_nombre", "sucursal_nombre",
                                                    "convocatorias",
                                                    "presentes", "tarde", "ausentes", "justificados", "asistencia_pct",
                                                    "puntualidad_pct")])
    nombre = f"reunion_{reunion_id}_{desde:%Y%m%d}_{hasta:%Y%m%d}.csv"
    return Response("﻿" + out.getvalue(), mimetype="text/csv",
                    headers={"Content-Disposition": f"attachment; filename={nombre}"})


@web.get("/<int:reunion_id>/fecha/<fecha>")
@permission_required("reuniones", "ver")
def ocurrencia(reunion_id, fecha):
    dia = _fecha(fecha)
    if not dia:
        abort(404)
    return render_template("reuniones/ocurrencia.html",
                           **s.ocurrencia_detalle(who(), reunion_id, dia, request.args.get("sucursal", 0, type=int)),
                           estados=s.ESTADOS)


@web.post("/<int:reunion_id>/fecha/<fecha>/marcar")
@permission_required("reuniones", "editar")
def marcar(reunion_id, fecha):
    sucursal = request.form.get("sucursal_id", 0, type=int)
    s.marcar_manual(who(), reunion_id, fecha, request.form.get("empleado_id", type=int), request.form.get("estado"),
                    request.form.get("observaciones"), sucursal_id=sucursal)
    log_audit(session, "reunion_marcar_asistencia", "reuniones", reunion_id)
    flash("Asistencia actualizada.", "success")
    return redirect(url_for("reuniones.ocurrencia", reunion_id=reunion_id, fecha=fecha, sucursal=sucursal or None))


@web.post("/<int:reunion_id>/fecha/<fecha>/horario")
@permission_required("reuniones", "editar")
def reprogramar(reunion_id, fecha):
    sucursal = request.form.get("sucursal_id", 0, type=int)
    restaurar = request.form.get("accion") == "restaurar"
    todas = request.form.get("todas") == "1"
    n = s.reprogramar_ocurrencia(who(), reunion_id, fecha, request.form.get("hora"), request.form.get("motivo"),
                                 sucursal_id=None if todas else sucursal, restaurar=restaurar)
    log_audit(session, "reunion_restaurar_horario" if restaurar else "reunion_reprogramar_fecha", "reuniones", reunion_id)
    if restaurar:
        flash("La fecha volvió a su horario habitual.", "success")
    else:
        flash(f"Horario de la fecha cambiado a las {request.form.get('hora')}"
              + (f" en {n} sucursales" if n > 1 else "") + ". La app ya muestra el nuevo horario.", "success")
        _avisar_superposiciones(who(), reunion_id)
    return redirect(url_for("reuniones.ocurrencia", reunion_id=reunion_id, fecha=fecha, sucursal=sucursal or None))


@web.post("/<int:reunion_id>/fecha/<fecha>/cancelar")
@permission_required("reuniones", "editar")
def cancelar(reunion_id, fecha):
    reactivar = request.form.get("accion") == "reactivar"
    sucursal = request.form.get("sucursal_id", 0, type=int)
    todas = request.form.get("todas") == "1"
    s.cancelar_ocurrencia(who(), reunion_id, fecha, request.form.get("motivo"), cancelar=not reactivar,
                          sucursal_id=None if todas else sucursal)
    log_audit(session, "reunion_reactivar_fecha" if reactivar else "reunion_cancelar_fecha", "reuniones", reunion_id)
    if reactivar:
        flash("Fecha reactivada.", "success")
    else:
        flash("Fecha cancelada" + (" en todas las sucursales" if todas else "") + ": no cuenta para las estadísticas.",
              "success")
    return redirect(url_for("reuniones.ocurrencia", reunion_id=reunion_id, fecha=fecha, sucursal=sucursal or None))


@web.get("/<int:reunion_id>/qr")
@permission_required("reuniones", "ver")
def qr(reunion_id):
    with db.transaction(read_only=True) as c:
        reunion = s.obtener(c, who(), reunion_id)
        sedes = s.sedes_efectivas(c, reunion)
    hojas = [dict(sede=x, descripcion=s.describir(x),
                  imagen=build_qr_png_base64(s.qr_fijo(x)) if reunion["qr_modo"] != "dinamico" else None)
             for x in sedes]
    return render_template("reuniones/qr.html", reunion=reunion, hojas=hojas)


@web.post("/<int:reunion_id>/qr/regenerar")
@permission_required("reuniones", "editar")
def regenerar_qr(reunion_id):
    s.regenerar_qr(who(), reunion_id)
    log_audit(session, "reunion_regenerar_qr", "reuniones", reunion_id)
    flash("Se generó un QR nuevo. El impreso anterior dejó de funcionar: imprimí y reemplazá el cartel.", "success")
    return redirect(url_for("reuniones.qr", reunion_id=reunion_id))


def _qr_vivo(reunion_id):
    ahora = now_local()
    with db.transaction(read_only=True) as c:
        base = s.obtener(c, who(), reunion_id)
        sedes = s.sedes_efectivas(c, base)
        pedida = request.args.get("sucursal", type=int)
        reunion = next((x for x in sedes if x["sucursal_id"] == pedida), sedes[0])
        occ = s.ocurrencia(c, reunion, ahora.date(), crear=False)
    hoy = reunion["activa"] and (occ or s.ocurre_en(reunion, ahora.date()))
    data = dict(reunion=reunion, sedes=sedes, ahora=ahora, hoy=hoy, ttl=s.QR_DINAMICO_TTL, imagen=None, horario=None,
                cancelada=bool(occ and occ["estado"] == "cancelada"))
    if hoy and reunion["qr_modo"] != "fijo" and not data["cancelada"]:
        data["horario"] = occ or s.horarios(reunion, ahora.date())
        data["imagen"] = build_qr_png_base64(s.qr_dinamico(reunion, ahora.date()))
    return data


@web.get("/<int:reunion_id>/qr/proyectar")
@permission_required("reuniones", "ver")
def proyectar(reunion_id):
    return render_template("reuniones/proyectar.html", **_qr_vivo(reunion_id))


@web.get("/<int:reunion_id>/qr/vivo")
@permission_required("reuniones", "ver")
def qr_vivo(reunion_id):
    return render_template("reuniones/_qr_vivo.html", **_qr_vivo(reunion_id))


# --- Panel: estadisticas generales ---------------------------------------------------------

@web.get("/estadisticas")
@permission_required("reuniones", "ver")
def estadisticas():
    desde, hasta = _periodo(30)
    actor = who()
    sucursal = request.args.get("sucursal", type=int)
    data = s.estadisticas_empresa(actor, desde, hasta, sucursal)
    puntos = data["serie"]
    salto = max(1, len(puntos) // 8)
    labels = [{"label": f"{p['fecha']:%d/%m}" if i % salto == 0 or i == len(puntos) - 1 else "", "sub": ""}
              for i, p in enumerate(puntos)]
    chart = line_chart(labels, [{"key": "asistencia", "name": "Asistencia",
                                 "values": [p["asistencia_pct"] for p in puntos]}], y_max=100, width=880, height=260)
    tips = [{"title": f"{p['fecha']:%d/%m/%Y}",
             "rows": [{"key": "asistencia", "name": "Asistencia",
                       "value": "s/d" if p["asistencia_pct"] is None else f"{p['asistencia_pct']:g}%"}],
             "note": f"{p['asistidas']} de {int(p['convocatorias']) - int(p['justificados'])} convocatorias",
             "aria": f"{p['fecha']:%d/%m}: asistencia {p['asistencia_pct']}%"} for p in puntos]
    return render_template("reuniones/estadisticas.html", **data, chart=chart, tips=tips, desde=desde, hasta=hasta,
                           sucursales=s.sucursales(actor), sucursal=sucursal)


@web.get("/estadisticas/exportar.csv")
@permission_required("reuniones", "exportar")
def estadisticas_exportar():
    desde, hasta = _periodo(30)
    data = s.estadisticas_empresa(who(), desde, hasta, request.args.get("sucursal", type=int))
    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow(["Apellido", "Nombre", "Legajo", "Sucursal", "Convocatorias", "Presentes", "Tarde", "Ausentes", "Justificados",
                     "Asistencia %", "Puntualidad %"])
    for row in data["por_empleado"]:
        writer.writerow([csv_safe(row[k]) for k in ("apellido", "nombre", "legajo", "sucursal_nombre", "convocatorias",
                                                    "presentes", "tarde",
                                                    "ausentes", "justificados", "asistencia_pct", "puntualidad_pct")])
    return Response("﻿" + out.getvalue(), mimetype="text/csv",
                    headers={"Content-Disposition": f"attachment; filename=reuniones_{desde:%Y%m%d}_{hasta:%Y%m%d}.csv"})


# --- API del empleado ------------------------------------------------------------------------

def _rango_api(dias_default):
    hoy = now_local().date()
    try:
        hasta = dt.date.fromisoformat(request.args["hasta"]) if request.args.get("hasta") else hoy
        desde = dt.date.fromisoformat(request.args["desde"]) if request.args.get("desde") else hasta - dt.timedelta(days=dias_default - 1)
    except ValueError:
        raise s.Error("Fechas inválidas (use AAAA-MM-DD).")
    if desde > hasta:
        raise s.Error("'desde' no puede ser posterior a 'hasta'.")
    if (hasta - desde).days > s.MAX_RANGO_DIAS:
        raise s.Error("El rango máximo es de 366 días.")
    return desde, hasta


@mobile.get("")
@mobile_auth_required
def mobile_listado():
    return jsonify(items=serialize(s.mis_reuniones(employee())))


@mobile.get("/proximas")
@mobile_auth_required
def mobile_proximas():
    # ?semana=actual: de lunes a domingo de esta semana (incluye las ya pasadas); si no, desde hoy.
    if request.args.get("semana") == "actual":
        hoy = now_local().date()
        return jsonify(serialize(s.proximas(employee(), 7, desde=hoy - dt.timedelta(days=hoy.weekday()))))
    return jsonify(serialize(s.proximas(employee(), request.args.get("dias", 7, type=int))))


@mobile.post("/registrar")
@mobile_auth_required
def mobile_registrar():
    body = request.get_json(silent=True) or {}
    if not isinstance(body, dict):
        raise s.Error("Envíe un objeto JSON.")

    def coord(name, limit):
        value = body.get(name)
        if value in (None, ""):
            return None
        try:
            value = float(value)
        except (TypeError, ValueError):
            raise s.Error(f"{name} inválida.")
        if not -limit <= value <= limit:
            raise s.Error(f"{name} inválida.")
        return value

    resultado = s.registrar_qr(employee(), body.get("qr") or body.get("qr_token"), lat=coord("lat", 90),
                               lon=coord("lon", 180))
    return jsonify(resultado), 200 if resultado["ya_registrado"] else 201


@mobile.get("/historial")
@mobile_auth_required
def mobile_historial():
    desde, hasta = _rango_api(366)
    page = max(1, request.args.get("page", 1, type=int) or 1)
    per = max(1, min(request.args.get("per", 20, type=int) or 20, 100))
    return jsonify(s.historial_empleado(employee(), desde=desde, hasta=hasta,
                                        reunion_id=request.args.get("reunion_id", type=int), page=page, per_page=per))


@mobile.get("/estadisticas")
@mobile_auth_required
def mobile_estadisticas():
    desde, hasta = _rango_api(90)
    return jsonify(serialize(s.estadisticas_empleado(employee(), desde, hasta)))


@mobile.get("/<int:reunion_id>")
@mobile_auth_required
def mobile_detalle(reunion_id):
    emp = employee()
    with db.transaction(read_only=True) as c:
        rows = s._de_empleado_en_sede(c, emp, reunion_id=reunion_id, solo_activas=False)
    if not rows:
        raise s.Error("Reunión no encontrada.", 404)
    hoy = now_local().date()
    item = s.reunion_publica(rows[0])
    item["activa"] = bool(rows[0]["activa"])
    item["proximas_fechas"] = [f.isoformat() for f in s.fechas(rows[0], hoy, hoy + dt.timedelta(days=60))][:6] \
        if rows[0]["activa"] else []
    item["historial"] = s.historial_empleado(emp, reunion_id=reunion_id, per_page=10)["items"]
    item["mis_estadisticas"] = s.estadisticas_empleado(emp, hoy - dt.timedelta(days=89), hoy)["por_reunion"]
    item["mis_estadisticas"] = next((x for x in item["mis_estadisticas"] if x["reunion_id"] == reunion_id), None)
    return jsonify(serialize(item))
