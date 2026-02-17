import datetime

from flask import Blueprint, abort, render_template, request, session

from repositories.empresa_repository import get_all as get_empresas
from repositories.sucursal_repository import get_all as get_sucursales
from utils.audit import log_audit
from utils.jwt import generar_token_qr
from utils.qr import build_qr_png_base64
from web.auth.decorators import role_required

qr_puerta_bp = Blueprint("qr_puerta", __name__, url_prefix="/qr-puerta")


def _parse_int(value):
    raw = (value or "").strip()
    if not raw:
        return None
    try:
        return int(raw)
    except ValueError:
        return None


@qr_puerta_bp.route("/", methods=["GET", "POST"])
@role_required("admin")
def generar():
    empresas = get_empresas(include_inactive=False)
    sucursales = get_sucursales(include_inactive=False)
    data = {"empresa_id": None, "sucursal_id": None, "tolerancia_m": None, "vigencia_dias": 30}
    errors = []
    result = None

    if request.method == "POST":
        data["empresa_id"] = _parse_int(request.form.get("empresa_id"))
        data["sucursal_id"] = _parse_int(request.form.get("sucursal_id"))
        data["tolerancia_m"] = _parse_int(request.form.get("tolerancia_m"))
        data["vigencia_dias"] = _parse_int(request.form.get("vigencia_dias")) or 30

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

        if not errors:
            vigencia_segundos = data["vigencia_dias"] * 86400
            payload = {
                "accion": "auto",
                "scope": "empresa",
                "empresa_id": int(data["empresa_id"]),
                "origen": "web_admin_puerta",
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
                expira_at = (
                    datetime.datetime.now(datetime.UTC) + datetime.timedelta(seconds=vigencia_segundos)
                ).replace(microsecond=0).isoformat().replace("+00:00", "Z")

                result = {
                    "empresa_id": int(data["empresa_id"]),
                    "empresa_nombre": empresa.get("razon_social"),
                    "sucursal_id": int(data["sucursal_id"]),
                    "sucursal_nombre": sucursal.get("nombre"),
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

    return render_template(
        "qr_puerta/generar.html",
        empresas=empresas,
        sucursales=sucursales,
        data=data,
        errors=errors,
        result=result,
    )


@qr_puerta_bp.route("/imprimir/<int:empresa_id>")
@role_required("admin")
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

    vigencia_segundos = 30 * 86400
    payload = {
        "accion": "auto",
        "scope": "empresa",
        "empresa_id": int(empresa_id),
        "origen": "web_admin_puerta",
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
        tolerancia_m=tolerancia_m,
        qr_png_base64=qr_png_base64,
        qr_token=qr_token,
    )
