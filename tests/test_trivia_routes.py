"""
Tests de la API móvil de Trivia Operativa.
Prefijo: /api/v1/trivia/

Estrategia: monkeypatch sobre el módulo de repositorio (trivia_repository)
y sobre las funciones importadas directamente en trivia_routes.
No se conecta a base de datos real.
"""

import datetime

import app as app_module
import utils.jwt_guard as jwt_guard
import repositories.trivia_repository as trivia_repo
import routes.trivia_routes as trivia_routes
from services.trivia_service import (
    TriviaDuplicadaError,
    TriviaFueraDeHorarioError,
    TriviaNoActivaError,
    TriviaNoEncontradaError,
    TriviaParticipacionEnProgresoError,
    TriviaYaFinalizadaError,
)

# ---------------------------------------------------------------------------
# Fixtures de datos
# ---------------------------------------------------------------------------

_TRIVIA_ACTIVA = {
    "id": 3,
    "titulo": "Trivia Mayo 2026",
    "descripcion": "Preguntas de logística.",
    "fecha_inicio": datetime.datetime(2026, 5, 24, 8, 0),
    "fecha_fin": datetime.datetime(2026, 5, 31, 23, 59),
    "estado": "activa",
    "premio": "Vale $5000",
    "mensaje_ganador": "¡Campeón!",
    "sector_id": None,
    "anio": 2026,
}

_EMPLEADO = {
    "id": 10,
    "activo": 1,
    "empresa_id": 3,
    "dni": "30111222",
    "nombre": "Ana",
    "apellido": "Lopez",
    "sector_id": None,
}

_RESULTADO_COMPLETADO = {
    "id": 1,
    "trivia_id": 3,
    "empleado_id": 10,
    "empleado_dni": "30111222",
    "fecha_inicio_participacion": datetime.datetime(2026, 5, 25, 9, 14),
    "fecha_finalizacion": datetime.datetime(2026, 5, 25, 9, 16, 22),
    "tiempo_total_segundos": 142,
    "puntos_total": 80,
    "correctas": 8,
    "incorrectas": 2,
    "posicion": 1,
    "es_ganador": 1,
    "estado_resultado": "completado",
}

_PREGUNTAS_SIN_RESP = [
    {"id": 101, "trivia_id": 3, "texto": "¿Cuántos bultos?",
     "opcion_a": "60", "opcion_b": "72", "opcion_c": "80", "opcion_d": "48",
     "puntos": 10, "orden": 0},
]


# ---------------------------------------------------------------------------
# Setup del test client
# ---------------------------------------------------------------------------

def _build_client(monkeypatch):
    monkeypatch.setattr(app_module, "init_db", lambda: None)
    app = app_module.create_app()
    app.config["TESTING"] = True
    app.config["WTF_CSRF_ENABLED"] = False
    return app.test_client()


def _auth_headers():
    return {"Authorization": "Bearer test-token"}


def _patch_auth(monkeypatch, empleado=None):
    """Parcha JWT y empleado para simular usuario autenticado."""
    monkeypatch.setattr(jwt_guard, "verificar_token", lambda token: {"empleado_id": 10})
    monkeypatch.setattr(
        trivia_routes, "get_empleado_by_id",
        lambda empleado_id: empleado or _EMPLEADO,
    )


# ===========================================================================
# Auth guard
# ===========================================================================

def test_trivia_estado_requiere_bearer(monkeypatch):
    client = _build_client(monkeypatch)
    resp = client.get("/api/v1/trivia/estado")
    assert resp.status_code == 401


def test_trivia_iniciar_requiere_bearer(monkeypatch):
    client = _build_client(monkeypatch)
    resp = client.post("/api/v1/trivia/iniciar")
    assert resp.status_code == 401


def test_trivia_token_invalido_devuelve_401(monkeypatch):
    client = _build_client(monkeypatch)
    monkeypatch.setattr(
        jwt_guard, "verificar_token",
        lambda token: (_ for _ in ()).throw(ValueError("Token expirado")),
    )
    resp = client.get("/api/v1/trivia/estado", headers=_auth_headers())
    assert resp.status_code == 401
    assert "Sesion invalida" in resp.get_json()["error"]


def test_trivia_empleado_inactivo_devuelve_404(monkeypatch):
    client = _build_client(monkeypatch)
    monkeypatch.setattr(jwt_guard, "verificar_token", lambda token: {"empleado_id": 10})
    monkeypatch.setattr(trivia_routes, "get_empleado_by_id", lambda eid: None)
    resp = client.get("/api/v1/trivia/estado", headers=_auth_headers())
    assert resp.status_code == 404


# ===========================================================================
# GET /estado
# ===========================================================================

def test_trivia_estado_sin_trivia_activa(monkeypatch):
    client = _build_client(monkeypatch)
    _patch_auth(monkeypatch)
    monkeypatch.setattr(trivia_repo, "get_trivia_activa_para_empleado", lambda eid: None)

    resp = client.get("/api/v1/trivia/estado", headers=_auth_headers())
    body = resp.get_json()

    assert resp.status_code == 200
    assert body["success"] is True
    assert body["data"]["hay_trivia_activa"] is False
    assert body["data"]["trivia"] is None
    assert body["data"]["ya_participo"] is False


def test_trivia_estado_con_trivia_sin_participar(monkeypatch):
    client = _build_client(monkeypatch)
    _patch_auth(monkeypatch)
    monkeypatch.setattr(
        trivia_repo, "get_trivia_activa_para_empleado", lambda eid: _TRIVIA_ACTIVA
    )
    monkeypatch.setattr(
        trivia_repo, "get_resultado_by_trivia_empleado", lambda tid, eid: None
    )

    resp = client.get("/api/v1/trivia/estado", headers=_auth_headers())
    body = resp.get_json()

    assert resp.status_code == 200
    assert body["data"]["hay_trivia_activa"] is True
    assert body["data"]["ya_participo"] is False
    assert body["data"]["en_progreso"] is False
    assert body["data"]["trivia"]["titulo"] == "Trivia Mayo 2026"


def test_trivia_estado_ya_participo(monkeypatch):
    client = _build_client(monkeypatch)
    _patch_auth(monkeypatch)
    monkeypatch.setattr(
        trivia_repo, "get_trivia_activa_para_empleado", lambda eid: _TRIVIA_ACTIVA
    )
    monkeypatch.setattr(
        trivia_repo, "get_resultado_by_trivia_empleado",
        lambda tid, eid: _RESULTADO_COMPLETADO,
    )

    resp = client.get("/api/v1/trivia/estado", headers=_auth_headers())
    body = resp.get_json()

    assert resp.status_code == 200
    assert body["data"]["ya_participo"] is True
    assert body["data"]["participacion"]["puntos_total"] == 80
    assert body["data"]["participacion"]["es_ganador"] is True


# ===========================================================================
# GET /activa
# ===========================================================================

def test_trivia_activa_no_encontrada(monkeypatch):
    client = _build_client(monkeypatch)
    _patch_auth(monkeypatch)
    monkeypatch.setattr(trivia_repo, "get_trivia_activa_para_empleado", lambda eid: None)

    resp = client.get("/api/v1/trivia/activa", headers=_auth_headers())
    assert resp.status_code == 404
    assert resp.get_json()["success"] is False


def test_trivia_activa_encontrada(monkeypatch):
    client = _build_client(monkeypatch)
    _patch_auth(monkeypatch)
    monkeypatch.setattr(
        trivia_repo, "get_trivia_activa_para_empleado", lambda eid: _TRIVIA_ACTIVA
    )

    resp = client.get("/api/v1/trivia/activa", headers=_auth_headers())
    body = resp.get_json()

    assert resp.status_code == 200
    assert body["success"] is True
    assert body["data"]["id"] == 3
    assert body["data"]["estado"] == "activa"


# ===========================================================================
# POST /iniciar
# ===========================================================================

def test_trivia_iniciar_exito(monkeypatch):
    client = _build_client(monkeypatch)
    _patch_auth(monkeypatch)
    monkeypatch.setattr(
        trivia_routes, "iniciar_participacion",
        lambda emp: {
            "trivia_id": 3,
            "titulo": "Trivia Mayo 2026",
            "descripcion": "...",
            "fecha_fin": "2026-05-31T23:59:00",
            "preguntas": _PREGUNTAS_SIN_RESP,
        },
    )

    resp = client.post("/api/v1/trivia/iniciar", headers=_auth_headers())
    body = resp.get_json()

    assert resp.status_code == 200
    assert body["success"] is True
    assert body["data"]["trivia_id"] == 3
    assert len(body["data"]["preguntas"]) == 1
    # La respuesta correcta nunca debe estar en las preguntas
    assert "respuesta_correcta" not in body["data"]["preguntas"][0]


def test_trivia_iniciar_ya_participo_devuelve_409(monkeypatch):
    client = _build_client(monkeypatch)
    _patch_auth(monkeypatch)
    monkeypatch.setattr(
        trivia_routes, "iniciar_participacion",
        lambda emp: (_ for _ in ()).throw(TriviaDuplicadaError("Ya participaste en esta trivia.")),
    )

    resp = client.post("/api/v1/trivia/iniciar", headers=_auth_headers())
    assert resp.status_code == 409
    assert "Ya participaste" in resp.get_json()["error"]


def test_trivia_iniciar_sin_trivia_activa_devuelve_404(monkeypatch):
    client = _build_client(monkeypatch)
    _patch_auth(monkeypatch)
    monkeypatch.setattr(
        trivia_routes, "iniciar_participacion",
        lambda emp: (_ for _ in ()).throw(TriviaNoActivaError("No hay trivia activa.")),
    )

    resp = client.post("/api/v1/trivia/iniciar", headers=_auth_headers())
    assert resp.status_code == 404


def test_trivia_iniciar_fuera_de_horario_devuelve_404(monkeypatch):
    client = _build_client(monkeypatch)
    _patch_auth(monkeypatch)
    monkeypatch.setattr(
        trivia_routes, "iniciar_participacion",
        lambda emp: (_ for _ in ()).throw(
            TriviaFueraDeHorarioError("La trivia no está disponible.")
        ),
    )

    resp = client.post("/api/v1/trivia/iniciar", headers=_auth_headers())
    assert resp.status_code == 404


def test_trivia_iniciar_en_progreso_devuelve_preguntas(monkeypatch):
    client = _build_client(monkeypatch)
    _patch_auth(monkeypatch)
    monkeypatch.setattr(
        trivia_routes, "iniciar_participacion",
        lambda emp: (_ for _ in ()).throw(
            TriviaParticipacionEnProgresoError("Tenés una participación en progreso.")
        ),
    )
    monkeypatch.setattr(
        trivia_repo, "get_trivia_activa_para_empleado", lambda eid: _TRIVIA_ACTIVA
    )
    monkeypatch.setattr(
        trivia_repo, "get_preguntas_para_jugar", lambda tid: _PREGUNTAS_SIN_RESP
    )

    resp = client.post("/api/v1/trivia/iniciar", headers=_auth_headers())
    body = resp.get_json()

    assert resp.status_code == 200
    assert body["en_progreso"] is True
    assert len(body["data"]["preguntas"]) == 1


# ===========================================================================
# POST /finalizar
# ===========================================================================

def test_trivia_finalizar_sin_trivia_id_devuelve_400(monkeypatch):
    client = _build_client(monkeypatch)
    _patch_auth(monkeypatch)

    resp = client.post("/api/v1/trivia/finalizar", headers=_auth_headers(), json={})
    assert resp.status_code == 400
    assert "trivia_id" in resp.get_json()["error"]


def test_trivia_finalizar_respuestas_no_lista_devuelve_400(monkeypatch):
    client = _build_client(monkeypatch)
    _patch_auth(monkeypatch)

    resp = client.post(
        "/api/v1/trivia/finalizar",
        headers=_auth_headers(),
        json={"trivia_id": 3, "respuestas": "invalido"},
    )
    assert resp.status_code == 400


def test_trivia_finalizar_exito(monkeypatch):
    client = _build_client(monkeypatch)
    _patch_auth(monkeypatch)
    monkeypatch.setattr(
        trivia_routes, "finalizar_participacion",
        lambda emp, tid, resp: {
            "trivia_id": 3,
            "puntos_total": 25,
            "correctas": 2,
            "incorrectas": 0,
            "tiempo_total_segundos": 142,
            "total_preguntas": 2,
        },
    )

    resp = client.post(
        "/api/v1/trivia/finalizar",
        headers=_auth_headers(),
        json={
            "trivia_id": 3,
            "respuestas": [
                {"pregunta_id": 101, "respuesta": "B", "tiempo_respuesta_segundos": 8},
                {"pregunta_id": 102, "respuesta": "C", "tiempo_respuesta_segundos": 12},
            ],
        },
    )
    body = resp.get_json()

    assert resp.status_code == 200
    assert body["success"] is True
    assert body["data"]["puntos_total"] == 25
    assert body["data"]["correctas"] == 2
    assert body["data"]["incorrectas"] == 0


def test_trivia_finalizar_duplicada_devuelve_409(monkeypatch):
    client = _build_client(monkeypatch)
    _patch_auth(monkeypatch)
    monkeypatch.setattr(
        trivia_routes, "finalizar_participacion",
        lambda emp, tid, resp: (_ for _ in ()).throw(
            TriviaDuplicadaError("Ya enviaste tus respuestas.")
        ),
    )

    resp = client.post(
        "/api/v1/trivia/finalizar",
        headers=_auth_headers(),
        json={"trivia_id": 3, "respuestas": []},
    )
    assert resp.status_code == 409


def test_trivia_finalizar_trivia_no_encontrada_devuelve_404(monkeypatch):
    client = _build_client(monkeypatch)
    _patch_auth(monkeypatch)
    monkeypatch.setattr(
        trivia_routes, "finalizar_participacion",
        lambda emp, tid, resp: (_ for _ in ()).throw(
            TriviaNoEncontradaError("Trivia no encontrada.")
        ),
    )

    resp = client.post(
        "/api/v1/trivia/finalizar",
        headers=_auth_headers(),
        json={"trivia_id": 99, "respuestas": []},
    )
    assert resp.status_code == 404


def test_trivia_finalizar_trivia_ya_finalizada_devuelve_410(monkeypatch):
    client = _build_client(monkeypatch)
    _patch_auth(monkeypatch)
    monkeypatch.setattr(
        trivia_routes, "finalizar_participacion",
        lambda emp, tid, resp: (_ for _ in ()).throw(
            TriviaYaFinalizadaError("Esta trivia ya fue finalizada.")
        ),
    )

    resp = client.post(
        "/api/v1/trivia/finalizar",
        headers=_auth_headers(),
        json={"trivia_id": 3, "respuestas": []},
    )
    assert resp.status_code == 410


# ===========================================================================
# GET /ranking/<trivia_id>
# ===========================================================================

def test_trivia_ranking_no_encontrada_devuelve_404(monkeypatch):
    client = _build_client(monkeypatch)
    _patch_auth(monkeypatch)
    monkeypatch.setattr(trivia_repo, "get_trivia_by_id", lambda tid: None)

    resp = client.get("/api/v1/trivia/ranking/99", headers=_auth_headers())
    assert resp.status_code == 404


def test_trivia_ranking_devuelve_lista_ordenada(monkeypatch):
    client = _build_client(monkeypatch)
    _patch_auth(monkeypatch)
    monkeypatch.setattr(trivia_repo, "get_trivia_by_id", lambda tid: _TRIVIA_ACTIVA)
    monkeypatch.setattr(
        trivia_routes, "calcular_ranking",
        lambda tid: [
            {"posicion": 1, "empleado_id": 10, "empleado_dni": "30111222",
             "empleado_nombre": "Lopez Ana", "puntos_total": 80,
             "correctas": 8, "incorrectas": 2, "tiempo_total_segundos": 98,
             "es_ganador": True},
            {"posicion": 2, "empleado_id": 15, "empleado_dni": "25333444",
             "empleado_nombre": "Gomez Carlos", "puntos_total": 80,
             "correctas": 8, "incorrectas": 2, "tiempo_total_segundos": 120,
             "es_ganador": False},
        ],
    )

    resp = client.get("/api/v1/trivia/ranking/3", headers=_auth_headers())
    body = resp.get_json()

    assert resp.status_code == 200
    assert body["success"] is True
    assert len(body["data"]["ranking"]) == 2
    assert body["data"]["ranking"][0]["posicion"] == 1
    assert body["data"]["ranking"][0]["es_ganador"] is True


# ===========================================================================
# GET /historial
# ===========================================================================

def test_trivia_historial_paginado(monkeypatch):
    client = _build_client(monkeypatch)
    _patch_auth(monkeypatch)
    trivia_con_ganador = {
        **_TRIVIA_ACTIVA,
        "estado": "finalizada",
        "ganador_nombre": "Lopez Ana",
        "ganador_dni": "30111222",
        "ganador_puntos": 80,
    }
    monkeypatch.setattr(
        trivia_repo, "get_trivias_finalizadas",
        lambda page, per_page: ([trivia_con_ganador], 1),
    )

    resp = client.get("/api/v1/trivia/historial?page=1&per_page=5", headers=_auth_headers())
    body = resp.get_json()

    assert resp.status_code == 200
    assert body["success"] is True
    assert body["total"] == 1
    assert body["data"][0]["ganador_nombre"] == "Lopez Ana"


# ===========================================================================
# GET /mi-historial
# ===========================================================================

def test_trivia_mi_historial(monkeypatch):
    client = _build_client(monkeypatch)
    _patch_auth(monkeypatch)
    monkeypatch.setattr(
        trivia_repo, "get_historial_empleado",
        lambda eid: [
            {
                "trivia_id": 3,
                "titulo": "Trivia Mayo 2026",
                "estado_trivia": "finalizada",
                "fecha_inicio": datetime.datetime(2026, 5, 24, 8, 0),
                "fecha_fin": datetime.datetime(2026, 5, 31, 23, 59),
                "premio": "Vale $5000",
                "puntos_total": 80,
                "correctas": 8,
                "incorrectas": 2,
                "tiempo_total_segundos": 142,
                "posicion": 1,
                "es_ganador": 1,
                "estado_resultado": "completado",
                "fecha_inicio_participacion": datetime.datetime(2026, 5, 25, 9, 14),
                "fecha_finalizacion": datetime.datetime(2026, 5, 25, 9, 16),
            }
        ],
    )

    resp = client.get("/api/v1/trivia/mi-historial", headers=_auth_headers())
    body = resp.get_json()

    assert resp.status_code == 200
    assert body["success"] is True
    assert len(body["data"]) == 1
    assert body["data"][0]["es_ganador"] is True
    assert body["data"][0]["puntos_total"] == 80


# ===========================================================================
# GET /ganador/<trivia_id>
# ===========================================================================

def test_trivia_ganador_no_disponible_devuelve_404(monkeypatch):
    client = _build_client(monkeypatch)
    _patch_auth(monkeypatch)
    monkeypatch.setattr(trivia_repo, "get_ganador_trivia", lambda tid: None)

    resp = client.get("/api/v1/trivia/ganador/3", headers=_auth_headers())
    assert resp.status_code == 404


def test_trivia_ganador_ok(monkeypatch):
    client = _build_client(monkeypatch)
    _patch_auth(monkeypatch)
    monkeypatch.setattr(
        trivia_repo, "get_ganador_trivia",
        lambda tid: {
            "trivia_id": 3,
            "titulo": "Trivia Mayo 2026",
            "premio": "Vale $5000",
            "mensaje_ganador": "¡Campeón!",
            "empleado_id": 10,
            "empleado_dni": "30111222",
            "empleado_nombre": "Lopez Ana",
            "puntos_total": 80,
            "tiempo_total_segundos": 98,
            "fecha_registro": datetime.datetime(2026, 6, 1, 0, 1),
        },
    )

    resp = client.get("/api/v1/trivia/ganador/3", headers=_auth_headers())
    body = resp.get_json()

    assert resp.status_code == 200
    assert body["success"] is True
    assert body["data"]["empleado_dni"] == "30111222"
    assert body["data"]["puntos_total"] == 80


# ===========================================================================
# GET /ranking-anual/<anio>
# ===========================================================================

def test_trivia_ranking_anual(monkeypatch):
    client = _build_client(monkeypatch)
    _patch_auth(monkeypatch)
    monkeypatch.setattr(
        trivia_repo, "get_ranking_anual",
        lambda anio: [
            {
                "id": 1, "anio": 2026, "empleado_id": 10,
                "empleado_dni": "30111222", "empleado_nombre": "Lopez Ana",
                "puntos_anuales": 240, "trivias_participadas": 3,
                "trivias_ganadas": 2, "correctas_totales": 26,
                "incorrectas_totales": 4, "tiempo_total_anual": 380,
                "posicion": 1, "es_ganador_anual": False,
            }
        ],
    )

    resp = client.get("/api/v1/trivia/ranking-anual/2026", headers=_auth_headers())
    body = resp.get_json()

    assert resp.status_code == 200
    assert body["success"] is True
    assert body["anio"] == 2026
    assert body["data"][0]["puntos_anuales"] == 240


# ===========================================================================
# GET /ganador-anual/<anio>
# ===========================================================================

def test_trivia_ganador_anual_no_disponible_devuelve_404(monkeypatch):
    client = _build_client(monkeypatch)
    _patch_auth(monkeypatch)
    monkeypatch.setattr(trivia_repo, "get_ganador_anual", lambda anio: None)

    resp = client.get("/api/v1/trivia/ganador-anual/2026", headers=_auth_headers())
    assert resp.status_code == 404


def test_trivia_ganador_anual_ok(monkeypatch):
    client = _build_client(monkeypatch)
    _patch_auth(monkeypatch)
    monkeypatch.setattr(
        trivia_repo, "get_ganador_anual",
        lambda anio: {
            "id": 1, "anio": 2026, "empleado_id": 10,
            "empleado_dni": "30111222", "empleado_nombre": "Lopez Ana",
            "puntos_anuales": 240, "trivias_participadas": 3,
            "trivias_ganadas": 2, "correctas_totales": 26,
            "incorrectas_totales": 4, "tiempo_total_anual": 380,
            "posicion": 1, "es_ganador_anual": True,
        },
    )

    resp = client.get("/api/v1/trivia/ganador-anual/2026", headers=_auth_headers())
    body = resp.get_json()

    assert resp.status_code == 200
    assert body["data"]["es_ganador_anual"] is True


# ===========================================================================
# GET /notificaciones
# ===========================================================================

def test_trivia_notificaciones_vacias(monkeypatch):
    client = _build_client(monkeypatch)
    _patch_auth(monkeypatch)
    monkeypatch.setattr(trivia_repo, "get_notificaciones_no_leidas", lambda eid: [])

    resp = client.get("/api/v1/trivia/notificaciones", headers=_auth_headers())
    body = resp.get_json()

    assert resp.status_code == 200
    assert body["data"] == []


def test_trivia_notificaciones_con_datos(monkeypatch):
    client = _build_client(monkeypatch)
    _patch_auth(monkeypatch)
    monkeypatch.setattr(
        trivia_repo, "get_notificaciones_no_leidas",
        lambda eid: [
            {
                "id": 7, "trivia_id": 3,
                "trivia_titulo": "Trivia Mayo 2026",
                "tipo": "recordatorio_2h",
                "mensaje": "¡Quedan 2 horas!",
                "enviada_en": datetime.datetime(2026, 5, 31, 21, 59),
                "fecha_fin": datetime.datetime(2026, 5, 31, 23, 59),
            }
        ],
    )

    resp = client.get("/api/v1/trivia/notificaciones", headers=_auth_headers())
    body = resp.get_json()

    assert resp.status_code == 200
    assert len(body["data"]) == 1
    assert body["data"][0]["tipo"] == "recordatorio_2h"


# ===========================================================================
# POST /notificaciones/<id>/leer
# ===========================================================================

def test_trivia_marcar_notificacion_leida(monkeypatch):
    client = _build_client(monkeypatch)
    _patch_auth(monkeypatch)
    llamadas = []
    monkeypatch.setattr(
        trivia_repo, "marcar_notificacion_leida",
        lambda nid, eid: llamadas.append((nid, eid)),
    )

    resp = client.post("/api/v1/trivia/notificaciones/7/leer", headers=_auth_headers())
    body = resp.get_json()

    assert resp.status_code == 200
    assert body["data"]["marcada"] is True
    assert llamadas == [(7, 10)]


# ===========================================================================
# POST /notificaciones/leer-todas
# ===========================================================================

def test_trivia_marcar_todas_leidas(monkeypatch):
    client = _build_client(monkeypatch)
    _patch_auth(monkeypatch)
    llamadas = []
    monkeypatch.setattr(
        trivia_repo, "marcar_todas_notificaciones_leidas",
        lambda eid: llamadas.append(eid),
    )

    resp = client.post("/api/v1/trivia/notificaciones/leer-todas", headers=_auth_headers())
    body = resp.get_json()

    assert resp.status_code == 200
    assert body["data"]["marcadas"] is True
    assert 10 in llamadas
