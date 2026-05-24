"""
Trivia Operativa – tareas automáticas con APScheduler.

Se inicializa una sola vez desde create_app() con init_trivia_scheduler(app).
Usa BackgroundScheduler (hilo daemon) para no bloquear la app.
"""

import logging

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger

import repositories.trivia_repository as repo
from services.trivia_service import finalizar_trivia, generar_notificaciones

logger = logging.getLogger(__name__)

_scheduler: BackgroundScheduler | None = None


# ---------------------------------------------------------------------------
# Tareas
# ---------------------------------------------------------------------------

def _activar_trivias():
    """Activa trivias cuya fecha_inicio ya llegó."""
    try:
        pendientes = repo.get_trivias_a_activar()
        for t in pendientes:
            repo.set_trivia_estado(t["id"], "activa")
            logger.info(f"[trivia_scheduler] Trivia {t['id']} '{t['titulo']}' activada.")
    except Exception:
        logger.exception("[trivia_scheduler] Error en _activar_trivias")


def _finalizar_trivias():
    """Finaliza trivias cuya fecha_fin ya llegó."""
    try:
        vencidas = repo.get_trivias_a_finalizar()
        for t in vencidas:
            try:
                finalizar_trivia(t["id"])
                logger.info(f"[trivia_scheduler] Trivia {t['id']} '{t['titulo']}' finalizada.")
            except Exception:
                logger.exception(f"[trivia_scheduler] Error al finalizar trivia {t['id']}")
    except Exception:
        logger.exception("[trivia_scheduler] Error en _finalizar_trivias")


def _notificaciones():
    """Genera recordatorios para empleados que no participaron."""
    try:
        activas = repo.get_trivias_activas()
        for t in activas:
            try:
                generar_notificaciones(t["id"])
            except Exception:
                logger.exception(
                    f"[trivia_scheduler] Error generando notificaciones trivia {t['id']}"
                )
    except Exception:
        logger.exception("[trivia_scheduler] Error en _notificaciones")


# ---------------------------------------------------------------------------
# Inicialización
# ---------------------------------------------------------------------------

def init_trivia_scheduler(app):
    """
    Arranca el scheduler en background.
    Llamar una sola vez desde create_app().
    """
    global _scheduler

    if _scheduler is not None:
        return  # ya inicializado (evita doble-start con use_reloader=True)

    _scheduler = BackgroundScheduler(daemon=True)

    # Cada 2 minutos: activar trivias programadas
    _scheduler.add_job(
        _activar_trivias,
        trigger=IntervalTrigger(minutes=2),
        id="trivia_activar",
        replace_existing=True,
        max_instances=1,
    )

    # Cada 2 minutos: finalizar trivias vencidas
    _scheduler.add_job(
        _finalizar_trivias,
        trigger=IntervalTrigger(minutes=2),
        id="trivia_finalizar",
        replace_existing=True,
        max_instances=1,
    )

    # Cada hora: generar notificaciones de recordatorio
    _scheduler.add_job(
        _notificaciones,
        trigger=IntervalTrigger(hours=1),
        id="trivia_notificaciones",
        replace_existing=True,
        max_instances=1,
    )

    _scheduler.start()
    app.logger.info("[trivia_scheduler] Scheduler de trivia iniciado.")


def shutdown_trivia_scheduler():
    global _scheduler
    if _scheduler and _scheduler.running:
        _scheduler.shutdown(wait=False)
        _scheduler = None
