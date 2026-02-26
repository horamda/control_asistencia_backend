import datetime

from flask import Blueprint, abort, render_template, request, session

from repositories.empresa_repository import get_all as get_empresas
from repositories.qr_puerta_repository import create as create_qr_historial
from repositories.qr_puerta_repository import get_by_id as get_qr_historial_by_id
from repositories.qr_puerta_repository import get_recent as get_qr_historial_recent
from repositories.sucursal_repository import get_all as get_sucursales
from utils.audit import log_audit
from utils.jwt import generar_token_qr
from utils.qr import build_qr_png_base64
from web.auth.decorators import role_required

qr_puerta_bp = Blueprint("qr_puerta", __name__, url_prefix="/qr-puerta")

TIPO_MARCA_OPTIONS = [
    ("jornada", "Jornada"),
    ("desayuno", "Desayuno"),
    ("almuerzo", "Almuerzo"),
    ("merienda", "Merienda"),
    ("otro", "Otro"),
]
TIPO_MARCA_ALLOWED = {code for code, _ in TIPO_MARCA_OPTIONS}


def _parse_int(value):
    raw = (value or "").strip()
    if not raw:
        return None
    try:
        return int(raw)
    except ValueError:
        return None


def _normalize_tipo_marca(value):
    raw = str(value or "").strip().lower()
    if not raw:
        return "jornada"
    return raw if raw in TIPO_MARCA_ALLOWED else None


@qr_puerta_bp.route("/", methods=["GET", "POST"])
@role_required("admin", "rrhh")
def generar():
    empresas = get_empresas(include_inactive=False)
    sucursales = get_sucursales(include_inactive=False)
    data = {
        "empresa_id": None,
        "sucursal_id": None,
        "tolerancia_m": None,
        "vigencia_dias": 30,
        "tipo_marca": "jornada",
    }
    errors = []
    result = None

    if request.method == "POST":
        data["empresa_id"] = _parse_int(request.form.get("empresa_id"))
        data["sucursal_id"] = _parse_int(request.form.get("sucursal_id"))
        data["tolerancia_m"] = _parse_int(request.form.get("tolerancia_m"))
        data["vigencia_dias"] = _parse_int(request.form.get("vigencia_dias")) or 30
        data["tipo_marca"] = _normalize_tipo_marca(request.form.get("tipo_marca"))

        empresa = None
        if data["empresa_id"]:
            for item in empresas:
                if int(item["id"]) == int(data["empresa_id"]):
                    empresa = item
                    break
        if not empresa:
            errors.append("Empresa invalida.")

        sucursal = None
        if data["sucursal_id"]:
            for item in sucursales:
                if int(item["id"]) == int(data["sucursal_id"]):
                    sucursal = item
                    break
        if not sucursal:
            errors.append("Sucursal invalida.")
        elif int(sucursal["empresa_id"]) != int(data["empresa_id"] or 0):
            errors.append("La sucursal no pertenece a la empresa seleccionada.")

        if sucursal and (
            sucursal.get("latitud") is None or sucursal.get("longitud") is None
        ):
            errors.append("La sucursal seleccionada no tiene latitud/longitud configurada.")

        if not data["tolerancia_m"]:
            data["tolerancia_m"] = (
                int(sucursal.get("radio_permitido_m") or 0) if sucursal else None
            )
        if not data["tolerancia_m"] or data["tolerancia_m"] <= 0:
            errors.append("Tolerancia GPS invalida (metros).")

        if data["vigencia_dias"] < 1 or data["vigencia_dias"] > 3650:
            errors.append("Vigencia invalida (1 a 3650 dias).")
        if not data["tipo_marca"]:
            errors.append("Tipo de marca invalido.")

        if not errors:
            vigencia_segundos = data["vigencia_dias"] * 86400
            payload = {
                "accion": "auto",
                "scope": "empresa",
                "empresa_id": int(data["empresa_id"]),
                "origen": "web_admin_puerta",
                "tipo_marca": data["tipo_marca"],
                "geo_ref": {
                    "sucursal_id": int(data["sucursal_id"]),
                    "lat": float(sucursal["latitud"]),
                    "lon": float(sucursal["longitud"]),
                    "radio_m": float(data["tolerancia_m"]),
                },
            }
            try:
                qr_token = generar_token_qr(payload, vigencia_segundos=vigencia_segundos)
                qr_png_base64 = build_qr_png_base64(qr_token)
                expira_dt = (
                    datetime.datetime.now(datetime.UTC) + datetime.timedelta(seconds=vigencia_segundos)
                ).replace(microsecond=0)
                expira_at = expira_dt.isoformat().replace("+00:00", "Z")
                historial_id = create_qr_historial(
                    empresa_id=int(data["empresa_id"]),
                    empresa_nombre=str(empresa.get("razon_social") or f"Empresa {data['empresa_id']}"),
                    sucursal_id=int(data["sucursal_id"]),
                    sucursal_nombre=str(sucursal.get("nombre") or f"Sucursal {data['sucursal_id']}"),
                    tipo_marca=data["tipo_marca"],
                    geo_lat=float(sucursal["latitud"]),
                    geo_lon=float(sucursal["longitud"]),
                    tolerancia_m=int(data["tolerancia_m"]),
                    vigencia_dias=int(data["vigencia_dias"]),
                    vigencia_segundos=vigencia_segundos,
                    expira_at=expira_dt.replace(tzinfo=None),
                    qr_token=qr_token,
                    usuario_id=session.get("user_id"),
                )

                result = {
                    "historial_id": historial_id,
                    "empresa_id": int(data["empresa_id"]),
                    "empresa_nombre": empresa.get("razon_social"),
                    "sucursal_id": int(data["sucursal_id"]),
                    "sucursal_nombre": sucursal.get("nombre"),
                    "tipo_marca": data["tipo_marca"],
                    "geo_lat": float(sucursal["latitud"]),
                    "geo_lon": float(sucursal["longitud"]),
                    "tolerancia_m": int(data["tolerancia_m"]),
                    "vigencia_dias": data["vigencia_dias"],
                    "vigencia_segundos": vigencia_segundos,
                    "expira_at": expira_at,
                    "qr_token": qr_token,
                    "qr_png_base64": qr_png_base64,
                }
                log_audit(session, "create", "qr_puerta", int(data["empresa_id"]))
            except RuntimeError as exc:
                errors.append(str(exc))

    historial = get_qr_historial_recent(limit=30)
    return render_template(
        "qr_puerta/generar.html",
        empresas=empresas,
        sucursales=sucursales,
        data=data,
        errors=errors,
        result=result,
        historial=historial,
        tipo_marca_options=TIPO_MARCA_OPTIONS,
    )


@qr_puerta_bp.route("/imprimir/<int:empresa_id>")
@role_required("admin", "rrhh")
def imprimir(empresa_id):
    empresa = None
    empresas = get_empresas(include_inactive=False)
    for item in empresas:
        if int(item["id"]) == int(empresa_id):
            empresa = item
            break
    if not empresa:
        abort(404)

    sucursal_id = _parse_int(request.args.get("sucursal_id"))
    tolerancia_m = _parse_int(request.args.get("tolerancia_m")) or 0
    tipo_marca = _normalize_tipo_marca(request.args.get("tipo_marca"))
    sucursal = None
    if sucursal_id:
        for item in get_sucursales(include_inactive=False):
            if int(item["id"]) == int(sucursal_id):
                sucursal = item
                break

    if not sucursal or int(sucursal["empresa_id"]) != int(empresa_id):
        abort(404)
    if tolerancia_m <= 0:
        tolerancia_m = int(sucursal.get("radio_permitido_m") or 0)
    if tolerancia_m <= 0:
        abort(400)
    if not tipo_marca:
        abort(400)

    vigencia_segundos = 30 * 86400
    payload = {
        "accion": "auto",
        "scope": "empresa",
        "empresa_id": int(empresa_id),
        "origen": "web_admin_puerta",
        "tipo_marca": tipo_marca,
        "geo_ref": {
            "sucursal_id": int(sucursal["id"]),
            "lat": float(sucursal["latitud"]),
            "lon": float(sucursal["longitud"]),
            "radio_m": float(tolerancia_m),
        },
    }
    qr_token = generar_token_qr(payload, vigencia_segundos=vigencia_segundos)
    try:
        qr_png_base64 = build_qr_png_base64(qr_token)
    except RuntimeError as exc:
        abort(503, description=str(exc))

    return render_template(
        "qr_puerta/imprimir.html",
        empresa=empresa,
        sucursal=sucursal,
        tipo_marca=tipo_marca,
        tolerancia_m=tolerancia_m,
        qr_png_base64=qr_png_base64,
        qr_token=qr_token,
        historial=None,
    )


@qr_puerta_bp.route("/reimprimir/<int:historial_id>")
@role_required("admin", "rrhh")
def reimprimir(historial_id):
    row = get_qr_historial_by_id(historial_id)
    if not row:
        abort(404)

    try:
        qr_png_base64 = build_qr_png_base64(row["qr_token"])
    except RuntimeError as exc:
        abort(503, description=str(exc))

    empresa = {"id": row["empresa_id"], "razon_social": row["empresa_nombre"]}
    sucursal = {"id": row["sucursal_id"], "nombre": row["sucursal_nombre"]}
    tipo_marca = _normalize_tipo_marca(row.get("tipo_marca")) or "jornada"
    return render_template(
        "qr_puerta/imprimir.html",
        empresa=empresa,
        sucursal=sucursal,
        tipo_marca=tipo_marca,
        tolerancia_m=row["tolerancia_m"],
        qr_png_base64=qr_png_base64,
        qr_token=row["qr_token"],
        historial=row,
    )

