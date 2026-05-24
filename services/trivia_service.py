"""
Trivia Operativa – capa de servicio.

Toda la lógica de negocio: iniciar participación, finalizar, calcular
ranking, finalizar trivia completa, notificaciones y ranking anual.
"""

import datetime

import repositories.trivia_repository as repo


# ---------------------------------------------------------------------------
# Excepciones de dominio
# ---------------------------------------------------------------------------

class TriviaError(ValueError):
    pass


class TriviaDuplicadaError(TriviaError):
    pass


class TriviaFueraDeHorarioError(TriviaError):
    pass


class TriviaNoEncontradaError(TriviaError):
    pass


class TriviaNoActivaError(TriviaError):
    pass


class TriviaYaFinalizadaError(TriviaError):
    pass


class TriviaParticipacionEnProgresoError(TriviaError):
    pass


# ---------------------------------------------------------------------------
# Helpers privados
# ---------------------------------------------------------------------------

def _now() -> datetime.datetime:
    return datetime.datetime.now()


def _segundos_entre(inicio: datetime.datetime, fin: datetime.datetime) -> int:
    delta = fin - inicio
    return max(0, int(delta.total_seconds()))


def _full_name(emp: dict) -> str:
    return f"{emp.get('apellido', '')} {emp.get('nombre', '')}".strip()


# ---------------------------------------------------------------------------
# Participación – Iniciar
# ---------------------------------------------------------------------------

def iniciar_participacion(empleado: dict) -> dict:
    """
    Registra el inicio de la participación del empleado en la trivia activa.
    Devuelve las preguntas SIN respuesta correcta.

    Raises:
        TriviaNoActivaError      – no hay trivia activa para el empleado.
        TriviaDuplicadaError     – el empleado ya participó o tiene una en progreso.
        TriviaFueraDeHorarioError – la trivia existe pero está fuera de ventana.
    """
    empleado_id = int(empleado["id"])

    trivia = repo.get_trivia_activa_para_empleado(empleado_id)
    if not trivia:
        raise TriviaNoActivaError("No hay trivia activa disponible para vos.")

    ahora = _now()
    if trivia["fecha_inicio"] > ahora or trivia["fecha_fin"] < ahora:
        raise TriviaFueraDeHorarioError("La trivia no está disponible en este momento.")

    ya_existe = repo.get_resultado_by_trivia_empleado(trivia["id"], empleado_id)
    if ya_existe:
        if ya_existe["estado_resultado"] == "completado":
            raise TriviaDuplicadaError("Ya participaste en esta trivia.")
        # Tiene participación en progreso: devuelve el mismo resultado para continuar
        raise TriviaParticipacionEnProgresoError(
            "Tenés una participación en progreso para esta trivia."
        )

    empleado_dni = str(empleado["dni"])
    repo.create_resultado_inicio(trivia["id"], empleado_id, empleado_dni)

    preguntas = repo.get_preguntas_para_jugar(trivia["id"])
    return {
        "trivia_id": trivia["id"],
        "titulo": trivia["titulo"],
        "descripcion": trivia["descripcion"],
        "fecha_fin": trivia["fecha_fin"].isoformat() if hasattr(trivia["fecha_fin"], "isoformat") else str(trivia["fecha_fin"]),
        "preguntas": preguntas,
    }


# ---------------------------------------------------------------------------
# Participación – Finalizar
# ---------------------------------------------------------------------------

def finalizar_participacion(empleado: dict, trivia_id: int, respuestas: list[dict]) -> dict:
    """
    Recibe las respuestas del empleado, valida, calcula puntaje y persiste.

    respuestas: lista de {"pregunta_id": int, "respuesta": "A"|"B"|"C"|"D",
                           "tiempo_respuesta_segundos": int (opcional)}

    Raises:
        TriviaNoEncontradaError   – trivia inexistente.
        TriviaYaFinalizadaError   – la trivia ya terminó (no se puede responder).
        TriviaDuplicadaError      – el empleado ya completó esta trivia.
        TriviaNoActivaError       – sin participación iniciada.
    """
    empleado_id = int(empleado["id"])
    empleado_dni = str(empleado["dni"])

    trivia = repo.get_trivia_by_id(trivia_id)
    if not trivia:
        raise TriviaNoEncontradaError("Trivia no encontrada.")
    if trivia["estado"] == "finalizada":
        raise TriviaYaFinalizadaError("Esta trivia ya fue finalizada.")

    resultado = repo.get_resultado_by_trivia_empleado(trivia_id, empleado_id)
    if not resultado:
        raise TriviaNoActivaError("No iniciaste la participación en esta trivia.")
    if resultado["estado_resultado"] == "completado":
        raise TriviaDuplicadaError("Ya enviaste tus respuestas para esta trivia.")

    # Cargar preguntas CON respuesta correcta para validar
    preguntas_map: dict[int, dict] = {
        p["id"]: p for p in repo.get_preguntas_admin(trivia_id) if p["activa"]
    }

    ahora = _now()
    puntos_total = 0
    correctas = 0
    incorrectas = 0
    bulk_rows: list[dict] = []

    respuestas_map: dict[int, dict] = {
        int(r["pregunta_id"]): r for r in respuestas
    }

    for pid, pregunta in preguntas_map.items():
        resp = respuestas_map.get(pid)
        seleccionada = (resp.get("respuesta") or "").upper() if resp else None
        es_correcta = seleccionada == pregunta["respuesta_correcta"]
        puntos_obtenidos = int(pregunta["puntos"]) if es_correcta else 0

        if es_correcta:
            correctas += 1
        else:
            incorrectas += 1
        puntos_total += puntos_obtenidos

        bulk_rows.append({
            "trivia_id": trivia_id,
            "pregunta_id": pid,
            "empleado_id": empleado_id,
            "empleado_dni": empleado_dni,
            "respuesta_seleccionada": seleccionada or "A",
            "correcta": 1 if es_correcta else 0,
            "puntos_obtenidos": puntos_obtenidos,
            "tiempo_respuesta_segundos": resp.get("tiempo_respuesta_segundos") if resp else None,
            "fecha_respuesta": ahora,
        })

    tiempo_total = _segundos_entre(resultado["fecha_inicio_participacion"], ahora)

    repo.save_respuestas_bulk(bulk_rows)
    repo.update_resultado_final(
        resultado["id"],
        {
            "fecha_finalizacion": ahora,
            "tiempo_total_segundos": tiempo_total,
            "puntos_total": puntos_total,
            "correctas": correctas,
            "incorrectas": incorrectas,
        },
    )

    return {
        "trivia_id": trivia_id,
        "puntos_total": puntos_total,
        "correctas": correctas,
        "incorrectas": incorrectas,
        "tiempo_total_segundos": tiempo_total,
        "total_preguntas": len(preguntas_map),
    }


# ---------------------------------------------------------------------------
# Ranking de una trivia
# ---------------------------------------------------------------------------

def calcular_ranking(trivia_id: int) -> list[dict]:
    """Devuelve el ranking de la trivia sin modificar la base."""
    rows = repo.get_ranking_trivia(trivia_id)
    resultado = []
    for pos, row in enumerate(rows, start=1):
        resultado.append({
            "posicion": pos,
            "empleado_id": row["empleado_id"],
            "empleado_dni": row["empleado_dni"],
            "empleado_nombre": row.get("empleado_nombre"),
            "puntos_total": row["puntos_total"],
            "correctas": row["correctas"],
            "incorrectas": row["incorrectas"],
            "tiempo_total_segundos": row["tiempo_total_segundos"],
            "es_ganador": pos == 1,
        })
    return resultado


# ---------------------------------------------------------------------------
# Finalizar trivia (scheduler o admin manual)
# ---------------------------------------------------------------------------

def finalizar_trivia(trivia_id: int):
    """
    Cierra la trivia, calcula ranking, asigna posiciones,
    guarda ganador y actualiza ranking anual.
    Usa múltiples escrituras pero con commit en cada repo (atómico por operación).
    """
    trivia = repo.get_trivia_by_id(trivia_id)
    if not trivia:
        raise TriviaNoEncontradaError(f"Trivia {trivia_id} no encontrada.")
    if trivia["estado"] == "finalizada":
        return  # idempotente

    # 1) Marcar como finalizada
    repo.set_trivia_estado(trivia_id, "finalizada")

    # 2) Obtener ranking ordenado
    ranking = repo.get_ranking_trivia(trivia_id)
    if not ranking:
        return

    # 3) Guardar posiciones
    ordered_ids = [r["id"] for r in ranking]
    repo.set_posiciones_ranking(trivia_id, ordered_ids)

    # 4) Guardar ganador histórico (primer puesto)
    ganador_row = ranking[0]
    repo.save_ganador({
        "trivia_id": trivia_id,
        "empleado_id": ganador_row["empleado_id"],
        "empleado_dni": ganador_row["empleado_dni"],
        "empleado_nombre": ganador_row.get("empleado_nombre"),
        "puntos_total": ganador_row["puntos_total"],
        "tiempo_total_segundos": ganador_row["tiempo_total_segundos"],
        "posicion": 1,
    })

    # 5) Recalcular ranking anual del año de la trivia
    repo.recalcular_ranking_anual(trivia["anio"])


# ---------------------------------------------------------------------------
# Notificaciones automáticas
# ---------------------------------------------------------------------------

def generar_notificaciones(trivia_id: int):
    """
    Genera recordatorios (24h y 2h antes del fin) para empleados que
    no participaron. Usa INSERT IGNORE para evitar duplicados.
    """
    trivia = repo.get_trivia_by_id(trivia_id)
    if not trivia or trivia["estado"] != "activa":
        return

    ahora = _now()
    fecha_fin = trivia["fecha_fin"]
    if hasattr(fecha_fin, "timestamp"):
        segundos_restantes = (fecha_fin - ahora).total_seconds()
    else:
        fecha_fin = datetime.datetime.fromisoformat(str(fecha_fin))
        segundos_restantes = (fecha_fin - ahora).total_seconds()

    if segundos_restantes <= 0:
        return

    # Determinar qué tipo de notificación corresponde ahora
    tipos_a_enviar: list[str] = []
    if segundos_restantes <= 7200:   # <= 2 horas
        tipos_a_enviar.append("recordatorio_2h")
    if segundos_restantes <= 86400:  # <= 24 horas
        tipos_a_enviar.append("recordatorio_24h")

    if not tipos_a_enviar:
        return

    empleados = repo.get_empleados_sin_participar(trivia_id)
    for emp in empleados:
        for tipo in tipos_a_enviar:
            if repo.exists_notificacion(trivia_id, emp["empleado_id"], tipo):
                continue
            mensaje = _build_mensaje(trivia, tipo)
            repo.save_notificacion({
                "trivia_id": trivia_id,
                "empleado_id": emp["empleado_id"],
                "empleado_dni": emp["empleado_dni"],
                "tipo": tipo,
                "mensaje": mensaje,
            })


def _build_mensaje(trivia: dict, tipo: str) -> str:
    titulo = trivia.get("titulo", "Trivia")
    if tipo == "recordatorio_2h":
        return f"¡Quedan solo 2 horas para participar en '{titulo}'! No te lo pierdas."
    return f"¡Tenés 24 horas para participar en '{titulo}'! Ingresá y jugá."


# ---------------------------------------------------------------------------
# Ranking anual
# ---------------------------------------------------------------------------

def calcular_ranking_anual(anio: int) -> list[dict]:
    repo.recalcular_ranking_anual(anio)
    return repo.get_ranking_anual(anio)
