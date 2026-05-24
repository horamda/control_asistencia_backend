"""
Trivia Operativa – endpoints de la API móvil.
Prefix: /api/v1/trivia
Auth:   Bearer JWT (mobile_auth_required)
"""

from flask import Blueprint, g, jsonify, request

import repositories.trivia_repository as repo
from repositories.empleado_repository import get_by_id as get_empleado_by_id
from services.trivia_service import (
    TriviaError,
    TriviaDuplicadaError,
    TriviaFueraDeHorarioError,
    TriviaNoActivaError,
    TriviaNoEncontradaError,
    TriviaParticipacionEnProgresoError,
    TriviaYaFinalizadaError,
    calcular_ranking,
    calcular_ranking_anual,
    finalizar_participacion,
    finalizar_trivia,
    iniciar_participacion,
)
from utils.jwt_guard import mobile_auth_required

trivia_bp = Blueprint("trivia", __name__, url_prefix="/api/v1/trivia")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _err(msg: str, code: int = 400):
    return jsonify({"success": False, "error": msg}), code


def _ok(data: dict | list | None = None, **extra):
    body = {"success": True}
    if data is not None:
        body["data"] = data
    body.update(extra)
    return jsonify(body), 200


def _get_empleado():
    """Resuelve el empleado activo desde el token JWT."""
    empleado = get_empleado_by_id(g.mobile_empleado_id)
    if not empleado or not empleado.get("activo"):
        return None
    return empleado


def _serialize_trivia(t: dict) -> dict:
    return {
        "id": t["id"],
        "titulo": t["titulo"],
        "descripcion": t.get("descripcion"),
        "fecha_inicio": _iso(t.get("fecha_inicio")),
        "fecha_fin": _iso(t.get("fecha_fin")),
        "estado": t["estado"],
        "premio": t.get("premio"),
        "mensaje_ganador": t.get("mensaje_ganador"),
        "anio": t.get("anio"),
    }


def _iso(val) -> str | None:
    if val is None:
        return None
    return val.isoformat() if hasattr(val, "isoformat") else str(val)


# ---------------------------------------------------------------------------
# GET /api/v1/trivia/estado
# Devuelve estado general: trivia activa, si ya participó, puntaje propio.
# ---------------------------------------------------------------------------

@trivia_bp.get("/estado")
@mobile_auth_required
def estado():
    empleado = _get_empleado()
    if not empleado:
        return _err("Empleado no encontrado.", 404)

    empleado_id = int(empleado["id"])
    trivia = repo.get_trivia_activa_para_empleado(empleado_id)

    if not trivia:
        return _ok({
            "hay_trivia_activa": False,
            "trivia": None,
            "ya_participo": False,
            "participacion": None,
        })

    resultado = repo.get_resultado_by_trivia_empleado(trivia["id"], empleado_id)
    ya_participo = resultado is not None and resultado["estado_resultado"] == "completado"
    en_progreso = resultado is not None and resultado["estado_resultado"] == "en_progreso"

    participacion = None
    if resultado:
        participacion = {
            "estado_resultado": resultado["estado_resultado"],
            "puntos_total": resultado["puntos_total"],
            "correctas": resultado["correctas"],
            "incorrectas": resultado["incorrectas"],
            "tiempo_total_segundos": resultado["tiempo_total_segundos"],
            "posicion": resultado["posicion"],
            "es_ganador": bool(resultado["es_ganador"]),
        }

    return _ok({
        "hay_trivia_activa": True,
        "trivia": _serialize_trivia(trivia),
        "ya_participo": ya_participo,
        "en_progreso": en_progreso,
        "participacion": participacion,
    })


# ---------------------------------------------------------------------------
# GET /api/v1/trivia/activa
# Devuelve datos completos de la trivia activa (sin preguntas aún).
# ---------------------------------------------------------------------------

@trivia_bp.get("/activa")
@mobile_auth_required
def activa():
    empleado = _get_empleado()
    if not empleado:
        return _err("Empleado no encontrado.", 404)

    trivia = repo.get_trivia_activa_para_empleado(int(empleado["id"]))
    if not trivia:
        return _err("No hay trivia activa.", 404)

    return _ok(_serialize_trivia(trivia))


# ---------------------------------------------------------------------------
# POST /api/v1/trivia/iniciar
# Registra inicio de participación, devuelve preguntas sin respuesta correcta.
# ---------------------------------------------------------------------------

@trivia_bp.post("/iniciar")
@mobile_auth_required
def iniciar():
    empleado = _get_empleado()
    if not empleado:
        return _err("Empleado no encontrado.", 404)

    try:
        resultado = iniciar_participacion(empleado)
    except TriviaDuplicadaError as exc:
        return _err(str(exc), 409)
    except TriviaParticipacionEnProgresoError as exc:
        # Devuelve las preguntas de la trivia en progreso para que Flutter las muestre
        trivia = repo.get_trivia_activa_para_empleado(int(empleado["id"]))
        preguntas = repo.get_preguntas_para_jugar(trivia["id"]) if trivia else []
        return jsonify({
            "success": True,
            "en_progreso": True,
            "message": str(exc),
            "data": {
                "trivia_id": trivia["id"] if trivia else None,
                "titulo": trivia["titulo"] if trivia else None,
                "preguntas": preguntas,
            },
        }), 200
    except (TriviaNoActivaError, TriviaFueraDeHorarioError) as exc:
        return _err(str(exc), 404)
    except TriviaError as exc:
        return _err(str(exc), 400)

    return _ok(resultado)


# ---------------------------------------------------------------------------
# POST /api/v1/trivia/finalizar
# Recibe respuestas, calcula puntaje y guarda resultado.
# Body JSON: {"trivia_id": int, "respuestas": [{"pregunta_id":int,"respuesta":"A","tiempo_respuesta_segundos":5}]}
# ---------------------------------------------------------------------------

@trivia_bp.post("/finalizar")
@mobile_auth_required
def finalizar():
    empleado = _get_empleado()
    if not empleado:
        return _err("Empleado no encontrado.", 404)

    body = request.get_json(silent=True) or {}
    trivia_id = body.get("trivia_id")
    respuestas = body.get("respuestas")

    if not trivia_id:
        return _err("trivia_id requerido.")
    if not isinstance(respuestas, list):
        return _err("respuestas debe ser una lista.")

    try:
        resultado = finalizar_participacion(empleado, int(trivia_id), respuestas)
    except TriviaDuplicadaError as exc:
        return _err(str(exc), 409)
    except TriviaYaFinalizadaError as exc:
        return _err(str(exc), 410)
    except (TriviaNoEncontradaError, TriviaNoActivaError) as exc:
        return _err(str(exc), 404)
    except TriviaError as exc:
        return _err(str(exc), 400)

    return _ok(resultado)


# ---------------------------------------------------------------------------
# GET /api/v1/trivia/ranking/<trivia_id>
# ---------------------------------------------------------------------------

@trivia_bp.get("/ranking/<int:trivia_id>")
@mobile_auth_required
def ranking_trivia(trivia_id: int):
    trivia = repo.get_trivia_by_id(trivia_id)
    if not trivia:
        return _err("Trivia no encontrada.", 404)

    ranking = calcular_ranking(trivia_id)
    return _ok({"trivia": _serialize_trivia(trivia), "ranking": ranking})


# ---------------------------------------------------------------------------
# GET /api/v1/trivia/historial?page=1&per_page=10
# Trivias finalizadas con ganador.
# ---------------------------------------------------------------------------

@trivia_bp.get("/historial")
@mobile_auth_required
def historial():
    page = max(1, int(request.args.get("page", 1)))
    per_page = min(50, max(1, int(request.args.get("per_page", 10))))
    rows, total = repo.get_trivias_finalizadas(page, per_page)

    def _fmt(r):
        return {
            **_serialize_trivia(r),
            "ganador_nombre": r.get("ganador_nombre"),
            "ganador_dni": r.get("ganador_dni"),
            "ganador_puntos": r.get("ganador_puntos"),
        }

    return _ok(
        [_fmt(r) for r in rows],
        total=total,
        page=page,
        per_page=per_page,
    )


# ---------------------------------------------------------------------------
# GET /api/v1/trivia/mi-historial
# Historial personal del empleado autenticado.
# ---------------------------------------------------------------------------

@trivia_bp.get("/mi-historial")
@mobile_auth_required
def mi_historial():
    empleado = _get_empleado()
    if not empleado:
        return _err("Empleado no encontrado.", 404)

    rows = repo.get_historial_empleado(int(empleado["id"]))

    def _fmt(r):
        return {
            "trivia_id": r["trivia_id"],
            "titulo": r.get("titulo"),
            "estado_trivia": r.get("estado_trivia"),
            "fecha_inicio": _iso(r.get("fecha_inicio")),
            "fecha_fin": _iso(r.get("fecha_fin")),
            "premio": r.get("premio"),
            "puntos_total": r["puntos_total"],
            "correctas": r["correctas"],
            "incorrectas": r["incorrectas"],
            "tiempo_total_segundos": r["tiempo_total_segundos"],
            "posicion": r["posicion"],
            "es_ganador": bool(r["es_ganador"]),
            "estado_resultado": r["estado_resultado"],
            "fecha_inicio_participacion": _iso(r.get("fecha_inicio_participacion")),
            "fecha_finalizacion": _iso(r.get("fecha_finalizacion")),
        }

    return _ok([_fmt(r) for r in rows])


# ---------------------------------------------------------------------------
# GET /api/v1/trivia/ganador/<trivia_id>
# ---------------------------------------------------------------------------

@trivia_bp.get("/ganador/<int:trivia_id>")
@mobile_auth_required
def ganador_trivia(trivia_id: int):
    ganador = repo.get_ganador_trivia(trivia_id)
    if not ganador:
        return _err("Ganador no disponible aún.", 404)
    return _ok({
        "trivia_id": ganador["trivia_id"],
        "titulo": ganador.get("titulo"),
        "premio": ganador.get("premio"),
        "mensaje_ganador": ganador.get("mensaje_ganador"),
        "empleado_id": ganador["empleado_id"],
        "empleado_dni": ganador["empleado_dni"],
        "empleado_nombre": ganador.get("empleado_nombre"),
        "puntos_total": ganador["puntos_total"],
        "tiempo_total_segundos": ganador["tiempo_total_segundos"],
        "fecha_registro": _iso(ganador.get("fecha_registro")),
    })


# ---------------------------------------------------------------------------
# GET /api/v1/trivia/ranking-anual/<anio>
# ---------------------------------------------------------------------------

@trivia_bp.get("/ranking-anual/<int:anio>")
@mobile_auth_required
def ranking_anual(anio: int):
    rows = repo.get_ranking_anual(anio)
    return _ok(rows, anio=anio)


# ---------------------------------------------------------------------------
# GET /api/v1/trivia/ganador-anual/<anio>
# ---------------------------------------------------------------------------

@trivia_bp.get("/ganador-anual/<int:anio>")
@mobile_auth_required
def ganador_anual(anio: int):
    ganador = repo.get_ganador_anual(anio)
    if not ganador:
        return _err(f"Ganador anual {anio} no disponible aún.", 404)
    return _ok(ganador)


# ---------------------------------------------------------------------------
# GET /api/v1/trivia/notificaciones
# Devuelve notificaciones no leídas del empleado.
# ---------------------------------------------------------------------------

@trivia_bp.get("/notificaciones")
@mobile_auth_required
def notificaciones():
    empleado = _get_empleado()
    if not empleado:
        return _err("Empleado no encontrado.", 404)

    rows = repo.get_notificaciones_no_leidas(int(empleado["id"]))

    def _fmt(r):
        return {
            "id": r["id"],
            "trivia_id": r["trivia_id"],
            "trivia_titulo": r.get("trivia_titulo"),
            "tipo": r["tipo"],
            "mensaje": r.get("mensaje"),
            "enviada_en": _iso(r.get("enviada_en")),
            "fecha_fin_trivia": _iso(r.get("fecha_fin")),
        }

    return _ok([_fmt(r) for r in rows])


# ---------------------------------------------------------------------------
# POST /api/v1/trivia/notificaciones/<id>/leer
# Marca una notificación como leída.
# ---------------------------------------------------------------------------

@trivia_bp.post("/notificaciones/<int:notif_id>/leer")
@mobile_auth_required
def marcar_leida(notif_id: int):
    empleado = _get_empleado()
    if not empleado:
        return _err("Empleado no encontrado.", 404)

    repo.marcar_notificacion_leida(notif_id, int(empleado["id"]))
    return _ok({"marcada": True})


# ---------------------------------------------------------------------------
# POST /api/v1/trivia/notificaciones/leer-todas
# ---------------------------------------------------------------------------

@trivia_bp.post("/notificaciones/leer-todas")
@mobile_auth_required
def marcar_todas_leidas():
    empleado = _get_empleado()
    if not empleado:
        return _err("Empleado no encontrado.", 404)

    repo.marcar_todas_notificaciones_leidas(int(empleado["id"]))
    return _ok({"marcadas": True})
