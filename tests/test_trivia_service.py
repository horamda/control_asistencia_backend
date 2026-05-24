"""
Tests unitarios del servicio de Trivia Operativa.
No se conecta a base de datos real: todo via monkeypatch sobre trivia_repository.
"""

import datetime

import pytest

import repositories.trivia_repository as trivia_repo
import services.trivia_service as svc
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

_NOW = datetime.datetime(2026, 5, 25, 10, 0, 0)

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

_PREGUNTAS_ADMIN = [
    {
        "id": 101, "trivia_id": 3, "texto": "¿Cuántos bultos?",
        "opcion_a": "60", "opcion_b": "72", "opcion_c": "80", "opcion_d": "48",
        "respuesta_correcta": "B", "puntos": 10, "activa": 1, "orden": 0,
    },
    {
        "id": 102, "trivia_id": 3, "texto": "¿EPP obligatorio?",
        "opcion_a": "Guantes", "opcion_b": "Casco", "opcion_c": "Casco + calzado", "opcion_d": "Ninguno",
        "respuesta_correcta": "C", "puntos": 15, "activa": 1, "orden": 1,
    },
]

_PREGUNTAS_SIN_RESP = [
    {"id": 101, "trivia_id": 3, "texto": "¿Cuántos bultos?",
     "opcion_a": "60", "opcion_b": "72", "opcion_c": "80", "opcion_d": "48",
     "puntos": 10, "orden": 0},
    {"id": 102, "trivia_id": 3, "texto": "¿EPP obligatorio?",
     "opcion_a": "Guantes", "opcion_b": "Casco", "opcion_c": "Casco + calzado", "opcion_d": "Ninguno",
     "puntos": 15, "orden": 1},
]

_RESULTADO_EN_PROGRESO = {
    "id": 1,
    "trivia_id": 3,
    "empleado_id": 10,
    "empleado_dni": "30111222",
    "fecha_inicio_participacion": datetime.datetime(2026, 5, 25, 9, 0),
    "fecha_finalizacion": None,
    "tiempo_total_segundos": None,
    "puntos_total": 0,
    "correctas": 0,
    "incorrectas": 0,
    "posicion": None,
    "es_ganador": 0,
    "estado_resultado": "en_progreso",
}

_RESULTADO_COMPLETADO = {
    **_RESULTADO_EN_PROGRESO,
    "fecha_finalizacion": datetime.datetime(2026, 5, 25, 9, 2, 22),
    "tiempo_total_segundos": 142,
    "puntos_total": 80,
    "correctas": 8,
    "incorrectas": 2,
    "estado_resultado": "completado",
}


# ===========================================================================
# iniciar_participacion
# ===========================================================================

def test_iniciar_sin_trivia_activa_lanza_excepcion(monkeypatch):
    monkeypatch.setattr(trivia_repo, "get_trivia_activa_para_empleado", lambda eid: None)

    with pytest.raises(TriviaNoActivaError):
        svc.iniciar_participacion(_EMPLEADO)


def test_iniciar_fuera_de_horario_lanza_excepcion(monkeypatch):
    trivia_pasada = {**_TRIVIA_ACTIVA, "fecha_fin": datetime.datetime(2026, 5, 20, 0, 0)}
    monkeypatch.setattr(
        trivia_repo, "get_trivia_activa_para_empleado", lambda eid: trivia_pasada
    )
    monkeypatch.setattr(svc, "_now", lambda: _NOW)

    with pytest.raises(TriviaFueraDeHorarioError):
        svc.iniciar_participacion(_EMPLEADO)


def test_iniciar_ya_completo_lanza_excepcion(monkeypatch):
    monkeypatch.setattr(
        trivia_repo, "get_trivia_activa_para_empleado", lambda eid: _TRIVIA_ACTIVA
    )
    monkeypatch.setattr(svc, "_now", lambda: _NOW)
    monkeypatch.setattr(
        trivia_repo, "get_resultado_by_trivia_empleado",
        lambda tid, eid: _RESULTADO_COMPLETADO,
    )

    with pytest.raises(TriviaDuplicadaError):
        svc.iniciar_participacion(_EMPLEADO)


def test_iniciar_en_progreso_lanza_excepcion(monkeypatch):
    monkeypatch.setattr(
        trivia_repo, "get_trivia_activa_para_empleado", lambda eid: _TRIVIA_ACTIVA
    )
    monkeypatch.setattr(svc, "_now", lambda: _NOW)
    monkeypatch.setattr(
        trivia_repo, "get_resultado_by_trivia_empleado",
        lambda tid, eid: _RESULTADO_EN_PROGRESO,
    )

    with pytest.raises(TriviaParticipacionEnProgresoError):
        svc.iniciar_participacion(_EMPLEADO)


def test_iniciar_exito_devuelve_preguntas_sin_respuesta_correcta(monkeypatch):
    monkeypatch.setattr(
        trivia_repo, "get_trivia_activa_para_empleado", lambda eid: _TRIVIA_ACTIVA
    )
    monkeypatch.setattr(svc, "_now", lambda: _NOW)
    monkeypatch.setattr(
        trivia_repo, "get_resultado_by_trivia_empleado", lambda tid, eid: None
    )
    monkeypatch.setattr(trivia_repo, "create_resultado_inicio", lambda tid, eid, dni: 1)
    monkeypatch.setattr(
        trivia_repo, "get_preguntas_para_jugar", lambda tid: _PREGUNTAS_SIN_RESP
    )

    resultado = svc.iniciar_participacion(_EMPLEADO)

    assert resultado["trivia_id"] == 3
    assert len(resultado["preguntas"]) == 2
    # Confirmar que no hay respuesta_correcta en ninguna pregunta
    for p in resultado["preguntas"]:
        assert "respuesta_correcta" not in p


# ===========================================================================
# finalizar_participacion
# ===========================================================================

def test_finalizar_trivia_no_encontrada_lanza_excepcion(monkeypatch):
    monkeypatch.setattr(trivia_repo, "get_trivia_by_id", lambda tid: None)

    with pytest.raises(TriviaNoEncontradaError):
        svc.finalizar_participacion(_EMPLEADO, 99, [])


def test_finalizar_trivia_ya_finalizada_lanza_excepcion(monkeypatch):
    monkeypatch.setattr(
        trivia_repo, "get_trivia_by_id",
        lambda tid: {**_TRIVIA_ACTIVA, "estado": "finalizada"},
    )

    with pytest.raises(TriviaYaFinalizadaError):
        svc.finalizar_participacion(_EMPLEADO, 3, [])


def test_finalizar_sin_inicio_lanza_excepcion(monkeypatch):
    monkeypatch.setattr(trivia_repo, "get_trivia_by_id", lambda tid: _TRIVIA_ACTIVA)
    monkeypatch.setattr(
        trivia_repo, "get_resultado_by_trivia_empleado", lambda tid, eid: None
    )

    with pytest.raises(TriviaNoActivaError):
        svc.finalizar_participacion(_EMPLEADO, 3, [])


def test_finalizar_ya_completado_lanza_excepcion(monkeypatch):
    monkeypatch.setattr(trivia_repo, "get_trivia_by_id", lambda tid: _TRIVIA_ACTIVA)
    monkeypatch.setattr(
        trivia_repo, "get_resultado_by_trivia_empleado",
        lambda tid, eid: _RESULTADO_COMPLETADO,
    )

    with pytest.raises(TriviaDuplicadaError):
        svc.finalizar_participacion(_EMPLEADO, 3, [])


def test_finalizar_calcula_puntaje_correcto(monkeypatch):
    monkeypatch.setattr(trivia_repo, "get_trivia_by_id", lambda tid: _TRIVIA_ACTIVA)
    monkeypatch.setattr(
        trivia_repo, "get_resultado_by_trivia_empleado",
        lambda tid, eid: _RESULTADO_EN_PROGRESO,
    )
    monkeypatch.setattr(
        trivia_repo, "get_preguntas_admin", lambda tid: _PREGUNTAS_ADMIN
    )
    monkeypatch.setattr(svc, "_now", lambda: _NOW)
    guardadas = []
    monkeypatch.setattr(trivia_repo, "save_respuestas_bulk", lambda rows: guardadas.extend(rows))
    monkeypatch.setattr(trivia_repo, "update_resultado_final", lambda rid, data: None)

    # Respuestas: 101→B (correcta, 10pts), 102→C (correcta, 15pts)
    respuestas = [
        {"pregunta_id": 101, "respuesta": "B", "tiempo_respuesta_segundos": 8},
        {"pregunta_id": 102, "respuesta": "C", "tiempo_respuesta_segundos": 12},
    ]

    resultado = svc.finalizar_participacion(_EMPLEADO, 3, respuestas)

    assert resultado["puntos_total"] == 25
    assert resultado["correctas"] == 2
    assert resultado["incorrectas"] == 0
    assert resultado["total_preguntas"] == 2
    # Verificar que se guardaron las respuestas
    assert len(guardadas) == 2


def test_finalizar_con_respuestas_incorrectas(monkeypatch):
    monkeypatch.setattr(trivia_repo, "get_trivia_by_id", lambda tid: _TRIVIA_ACTIVA)
    monkeypatch.setattr(
        trivia_repo, "get_resultado_by_trivia_empleado",
        lambda tid, eid: _RESULTADO_EN_PROGRESO,
    )
    monkeypatch.setattr(
        trivia_repo, "get_preguntas_admin", lambda tid: _PREGUNTAS_ADMIN
    )
    monkeypatch.setattr(svc, "_now", lambda: _NOW)
    monkeypatch.setattr(trivia_repo, "save_respuestas_bulk", lambda rows: None)
    monkeypatch.setattr(trivia_repo, "update_resultado_final", lambda rid, data: None)

    # Respuestas: 101→A (incorrecta), 102→C (correcta, 15pts)
    respuestas = [
        {"pregunta_id": 101, "respuesta": "A"},
        {"pregunta_id": 102, "respuesta": "C"},
    ]

    resultado = svc.finalizar_participacion(_EMPLEADO, 3, respuestas)

    assert resultado["puntos_total"] == 15
    assert resultado["correctas"] == 1
    assert resultado["incorrectas"] == 1


def test_finalizar_pregunta_omitida_cuenta_como_incorrecta(monkeypatch):
    monkeypatch.setattr(trivia_repo, "get_trivia_by_id", lambda tid: _TRIVIA_ACTIVA)
    monkeypatch.setattr(
        trivia_repo, "get_resultado_by_trivia_empleado",
        lambda tid, eid: _RESULTADO_EN_PROGRESO,
    )
    monkeypatch.setattr(
        trivia_repo, "get_preguntas_admin", lambda tid: _PREGUNTAS_ADMIN
    )
    monkeypatch.setattr(svc, "_now", lambda: _NOW)
    monkeypatch.setattr(trivia_repo, "save_respuestas_bulk", lambda rows: None)
    monkeypatch.setattr(trivia_repo, "update_resultado_final", lambda rid, data: None)

    # Solo responde pregunta 101, omite 102
    respuestas = [{"pregunta_id": 101, "respuesta": "B"}]

    resultado = svc.finalizar_participacion(_EMPLEADO, 3, respuestas)

    assert resultado["puntos_total"] == 10   # solo 101 correcta
    assert resultado["correctas"] == 1
    assert resultado["incorrectas"] == 1     # 102 omitida = incorrecta
    assert resultado["total_preguntas"] == 2


def test_finalizar_sin_respuestas_todo_incorrecto(monkeypatch):
    monkeypatch.setattr(trivia_repo, "get_trivia_by_id", lambda tid: _TRIVIA_ACTIVA)
    monkeypatch.setattr(
        trivia_repo, "get_resultado_by_trivia_empleado",
        lambda tid, eid: _RESULTADO_EN_PROGRESO,
    )
    monkeypatch.setattr(
        trivia_repo, "get_preguntas_admin", lambda tid: _PREGUNTAS_ADMIN
    )
    monkeypatch.setattr(svc, "_now", lambda: _NOW)
    monkeypatch.setattr(trivia_repo, "save_respuestas_bulk", lambda rows: None)
    monkeypatch.setattr(trivia_repo, "update_resultado_final", lambda rid, data: None)

    resultado = svc.finalizar_participacion(_EMPLEADO, 3, [])

    assert resultado["puntos_total"] == 0
    assert resultado["correctas"] == 0
    assert resultado["incorrectas"] == 2


# ===========================================================================
# calcular_ranking
# ===========================================================================

def test_calcular_ranking_orden_correcto(monkeypatch):
    """
    Puntaje DESC, tiempo ASC, inicio ASC.
    Emp A: 80pts, 100s → posición 1
    Emp B: 80pts, 120s → posición 2
    Emp C: 70pts,  50s → posición 3 (menos puntos aunque más rápido)
    """
    filas = [
        {
            "id": 1, "trivia_id": 3, "empleado_id": 10, "empleado_dni": "001",
            "empleado_nombre": "Lopez Ana", "puntos_total": 80,
            "correctas": 8, "incorrectas": 2, "tiempo_total_segundos": 100,
            "fecha_inicio_participacion": datetime.datetime(2026, 5, 25, 9, 0),
            "fecha_finalizacion": datetime.datetime(2026, 5, 25, 9, 1, 40),
        },
        {
            "id": 2, "trivia_id": 3, "empleado_id": 15, "empleado_dni": "002",
            "empleado_nombre": "Gomez Carlos", "puntos_total": 80,
            "correctas": 8, "incorrectas": 2, "tiempo_total_segundos": 120,
            "fecha_inicio_participacion": datetime.datetime(2026, 5, 25, 9, 0),
            "fecha_finalizacion": datetime.datetime(2026, 5, 25, 9, 2, 0),
        },
        {
            "id": 3, "trivia_id": 3, "empleado_id": 20, "empleado_dni": "003",
            "empleado_nombre": "Perez Juan", "puntos_total": 70,
            "correctas": 7, "incorrectas": 3, "tiempo_total_segundos": 50,
            "fecha_inicio_participacion": datetime.datetime(2026, 5, 25, 9, 0),
            "fecha_finalizacion": datetime.datetime(2026, 5, 25, 9, 0, 50),
        },
    ]
    monkeypatch.setattr(trivia_repo, "get_ranking_trivia", lambda tid: filas)

    ranking = svc.calcular_ranking(3)

    assert len(ranking) == 3
    assert ranking[0]["empleado_dni"] == "001"
    assert ranking[0]["posicion"] == 1
    assert ranking[0]["es_ganador"] is True
    assert ranking[1]["empleado_dni"] == "002"
    assert ranking[1]["posicion"] == 2
    assert ranking[1]["es_ganador"] is False
    assert ranking[2]["empleado_dni"] == "003"
    assert ranking[2]["posicion"] == 3


def test_calcular_ranking_vacio(monkeypatch):
    monkeypatch.setattr(trivia_repo, "get_ranking_trivia", lambda tid: [])
    ranking = svc.calcular_ranking(3)
    assert ranking == []


# ===========================================================================
# finalizar_trivia
# ===========================================================================

def test_finalizar_trivia_no_encontrada_lanza_excepcion(monkeypatch):
    monkeypatch.setattr(trivia_repo, "get_trivia_by_id", lambda tid: None)

    with pytest.raises(TriviaNoEncontradaError):
        svc.finalizar_trivia(99)


def test_finalizar_trivia_ya_finalizada_es_idempotente(monkeypatch):
    monkeypatch.setattr(
        trivia_repo, "get_trivia_by_id",
        lambda tid: {**_TRIVIA_ACTIVA, "estado": "finalizada"},
    )
    # No debe lanzar excepción ni llamar a nada más
    svc.finalizar_trivia(3)  # no exception


def test_finalizar_trivia_sin_participantes(monkeypatch):
    monkeypatch.setattr(trivia_repo, "get_trivia_by_id", lambda tid: _TRIVIA_ACTIVA)
    monkeypatch.setattr(trivia_repo, "set_trivia_estado", lambda tid, estado: None)
    monkeypatch.setattr(trivia_repo, "get_ranking_trivia", lambda tid: [])

    # No debe lanzar excepción cuando no hay participantes
    svc.finalizar_trivia(3)


def test_finalizar_trivia_completo(monkeypatch):
    estados_seteados = []
    ganador_guardado = []
    posiciones_seteadas = []
    anio_recalculado = []

    fila_ganador = {
        "id": 1, "trivia_id": 3, "empleado_id": 10, "empleado_dni": "30111222",
        "empleado_nombre": "Lopez Ana", "puntos_total": 80,
        "tiempo_total_segundos": 98,
    }

    monkeypatch.setattr(trivia_repo, "get_trivia_by_id", lambda tid: _TRIVIA_ACTIVA)
    monkeypatch.setattr(
        trivia_repo, "set_trivia_estado",
        lambda tid, estado: estados_seteados.append(estado),
    )
    monkeypatch.setattr(
        trivia_repo, "get_ranking_trivia", lambda tid: [fila_ganador]
    )
    monkeypatch.setattr(
        trivia_repo, "set_posiciones_ranking",
        lambda tid, ids: posiciones_seteadas.append(ids),
    )
    monkeypatch.setattr(
        trivia_repo, "save_ganador",
        lambda data: ganador_guardado.append(data),
    )
    monkeypatch.setattr(
        trivia_repo, "recalcular_ranking_anual",
        lambda anio: anio_recalculado.append(anio),
    )

    svc.finalizar_trivia(3)

    assert "finalizada" in estados_seteados
    assert len(ganador_guardado) == 1
    assert ganador_guardado[0]["empleado_dni"] == "30111222"
    assert posiciones_seteadas[0] == [1]  # id del único participante
    assert 2026 in anio_recalculado


# ===========================================================================
# generar_notificaciones
# ===========================================================================

def test_generar_notificaciones_trivia_no_activa(monkeypatch):
    monkeypatch.setattr(
        trivia_repo, "get_trivia_by_id",
        lambda tid: {**_TRIVIA_ACTIVA, "estado": "programada"},
    )
    guardadas = []
    monkeypatch.setattr(trivia_repo, "save_notificacion", lambda d: guardadas.append(d))

    svc.generar_notificaciones(3)

    assert guardadas == []


def test_generar_notificaciones_ya_vencida_no_envia(monkeypatch):
    trivia_vencida = {
        **_TRIVIA_ACTIVA,
        "estado": "activa",
        "fecha_fin": datetime.datetime(2026, 5, 24, 8, 0),  # ya pasó
    }
    monkeypatch.setattr(trivia_repo, "get_trivia_by_id", lambda tid: trivia_vencida)
    monkeypatch.setattr(svc, "_now", lambda: _NOW)
    guardadas = []
    monkeypatch.setattr(trivia_repo, "save_notificacion", lambda d: guardadas.append(d))

    svc.generar_notificaciones(3)

    assert guardadas == []


def test_generar_notificaciones_recordatorio_2h(monkeypatch):
    # Trivia vence en 1 hora → debe generar recordatorio_2h
    trivia = {
        **_TRIVIA_ACTIVA,
        "estado": "activa",
        "fecha_fin": _NOW + datetime.timedelta(hours=1),
    }
    monkeypatch.setattr(trivia_repo, "get_trivia_by_id", lambda tid: trivia)
    monkeypatch.setattr(svc, "_now", lambda: _NOW)
    monkeypatch.setattr(
        trivia_repo, "get_empleados_sin_participar",
        lambda tid: [
            {"empleado_id": 10, "empleado_dni": "30111222", "empleado_nombre": "Lopez Ana"}
        ],
    )
    monkeypatch.setattr(trivia_repo, "exists_notificacion", lambda tid, eid, tipo: False)
    guardadas = []
    monkeypatch.setattr(trivia_repo, "save_notificacion", lambda d: guardadas.append(d))

    svc.generar_notificaciones(3)

    tipos = [n["tipo"] for n in guardadas]
    assert "recordatorio_2h" in tipos
    assert "recordatorio_24h" in tipos   # 1h < 24h, también aplica


def test_generar_notificaciones_recordatorio_24h_no_2h(monkeypatch):
    # Trivia vence en 12 horas → solo recordatorio_24h
    trivia = {
        **_TRIVIA_ACTIVA,
        "estado": "activa",
        "fecha_fin": _NOW + datetime.timedelta(hours=12),
    }
    monkeypatch.setattr(trivia_repo, "get_trivia_by_id", lambda tid: trivia)
    monkeypatch.setattr(svc, "_now", lambda: _NOW)
    monkeypatch.setattr(
        trivia_repo, "get_empleados_sin_participar",
        lambda tid: [
            {"empleado_id": 10, "empleado_dni": "30111222", "empleado_nombre": "Lopez Ana"}
        ],
    )
    monkeypatch.setattr(trivia_repo, "exists_notificacion", lambda tid, eid, tipo: False)
    guardadas = []
    monkeypatch.setattr(trivia_repo, "save_notificacion", lambda d: guardadas.append(d))

    svc.generar_notificaciones(3)

    tipos = [n["tipo"] for n in guardadas]
    assert "recordatorio_24h" in tipos
    assert "recordatorio_2h" not in tipos


def test_generar_notificaciones_no_duplica(monkeypatch):
    # Trivia vence en 1 hora, pero la notificación ya fue enviada
    trivia = {
        **_TRIVIA_ACTIVA,
        "estado": "activa",
        "fecha_fin": _NOW + datetime.timedelta(hours=1),
    }
    monkeypatch.setattr(trivia_repo, "get_trivia_by_id", lambda tid: trivia)
    monkeypatch.setattr(svc, "_now", lambda: _NOW)
    monkeypatch.setattr(
        trivia_repo, "get_empleados_sin_participar",
        lambda tid: [
            {"empleado_id": 10, "empleado_dni": "30111222", "empleado_nombre": "Lopez Ana"}
        ],
    )
    # Simula que ya existe la notificación para todos los tipos
    monkeypatch.setattr(trivia_repo, "exists_notificacion", lambda tid, eid, tipo: True)
    guardadas = []
    monkeypatch.setattr(trivia_repo, "save_notificacion", lambda d: guardadas.append(d))

    svc.generar_notificaciones(3)

    assert guardadas == []


def test_generar_notificaciones_sin_empleados_sin_participar(monkeypatch):
    trivia = {
        **_TRIVIA_ACTIVA,
        "estado": "activa",
        "fecha_fin": _NOW + datetime.timedelta(hours=1),
    }
    monkeypatch.setattr(trivia_repo, "get_trivia_by_id", lambda tid: trivia)
    monkeypatch.setattr(svc, "_now", lambda: _NOW)
    monkeypatch.setattr(
        trivia_repo, "get_empleados_sin_participar", lambda tid: []
    )
    guardadas = []
    monkeypatch.setattr(trivia_repo, "save_notificacion", lambda d: guardadas.append(d))

    svc.generar_notificaciones(3)

    assert guardadas == []


def test_generar_notificaciones_trivia_lejos_no_genera(monkeypatch):
    # Trivia vence en 48 horas → no entra en ningún umbral
    trivia = {
        **_TRIVIA_ACTIVA,
        "estado": "activa",
        "fecha_fin": _NOW + datetime.timedelta(hours=48),
    }
    monkeypatch.setattr(trivia_repo, "get_trivia_by_id", lambda tid: trivia)
    monkeypatch.setattr(svc, "_now", lambda: _NOW)
    guardadas = []
    monkeypatch.setattr(trivia_repo, "save_notificacion", lambda d: guardadas.append(d))

    svc.generar_notificaciones(3)

    assert guardadas == []


# ===========================================================================
# Helpers internos
# ===========================================================================

def test_segundos_entre_calcula_correctamente():
    inicio = datetime.datetime(2026, 5, 25, 9, 0, 0)
    fin = datetime.datetime(2026, 5, 25, 9, 2, 22)
    assert svc._segundos_entre(inicio, fin) == 142


def test_segundos_entre_no_negativo():
    # fin < inicio → debe devolver 0
    inicio = datetime.datetime(2026, 5, 25, 9, 5, 0)
    fin = datetime.datetime(2026, 5, 25, 9, 0, 0)
    assert svc._segundos_entre(inicio, fin) == 0
