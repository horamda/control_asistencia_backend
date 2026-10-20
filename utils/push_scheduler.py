"""Notificaciones push: envia la cola y los comunicados programados cada minuto; cada 5 minutos encola los
recordatorios de reuniones y los avisos de ingreso y salida sin fichar; a las 8 los de acciones de seguridad por vencer y a
las 9 los de vacaciones (inicio y solicitudes sin resolver).
Sin Firebase configurado los trabajos de push no hacen nada (los comunicados programados igual quedan en la
bandeja de la app)."""

import logging
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from apscheduler.schedulers.background import BackgroundScheduler

_scheduler = None


def enviar():
    try:
        from services.push_service import procesar_cola
        procesar_cola()
    except Exception:
        logging.getLogger(__name__).exception("Error enviando notificaciones push")


def recordar():
    try:
        from services.reunion_avisos import recordatorios
        recordatorios()
    except Exception:
        logging.getLogger(__name__).exception("Error encolando recordatorios de reuniones")


def salidas():
    try:
        from services.avisos_push import salidas_pendientes
        salidas_pendientes()
    except Exception:
        logging.getLogger(__name__).exception("Error encolando avisos de salida pendiente")


def ingresos():
    try:
        from services.avisos_push import ingresos_pendientes
        ingresos_pendientes()
    except Exception:
        logging.getLogger(__name__).exception("Error encolando avisos de ingreso pendiente")


def comunicados_programados():
    try:
        from services.comunicado_programado_service import ejecutar_vencidos
        ejecutar_vencidos()
    except Exception:
        logging.getLogger(__name__).exception("Error enviando comunicados programados")


def acciones_seguridad():
    try:
        from services.avisos_push import acciones_por_vencer
        acciones_por_vencer()
    except Exception:
        logging.getLogger(__name__).exception("Error encolando avisos de acciones de seguridad")


def vacaciones():
    """Recordatorio del dia habil anterior al inicio y escalamiento de solicitudes sin resolver."""
    log = logging.getLogger(__name__)
    from services import avisos_push
    for tarea in (avisos_push.vacaciones_por_empezar, avisos_push.vacaciones_sin_resolver):
        try:
            tarea()
        except Exception:
            log.exception("Error encolando avisos de vacaciones")


def init_push_scheduler(app):
    global _scheduler
    if _scheduler is not None:
        return
    zone = ZoneInfo("America/Argentina/Buenos_Aires")
    _scheduler = BackgroundScheduler(daemon=True, timezone=zone)
    inicio = datetime.now(zone) + timedelta(seconds=30)
    _scheduler.add_job(recordar, "interval", minutes=5, id="push_recordatorios", max_instances=1, coalesce=True,
                       next_run_time=inicio)
    _scheduler.add_job(salidas, "interval", minutes=5, id="push_salidas", max_instances=1, coalesce=True,
                       next_run_time=inicio + timedelta(seconds=5))
    _scheduler.add_job(ingresos, "interval", minutes=5, id="push_ingresos", max_instances=1, coalesce=True,
                       next_run_time=inicio + timedelta(seconds=20))
    _scheduler.add_job(enviar, "interval", minutes=1, id="push_cola", max_instances=1, coalesce=True,
                       next_run_time=inicio + timedelta(seconds=15))
    # Comunicados programados: antes de vaciar la cola, para que salgan en ese mismo minuto.
    _scheduler.add_job(comunicados_programados, "interval", minutes=1, id="push_comunicados_programados",
                       max_instances=1, coalesce=True, next_run_time=inicio + timedelta(seconds=10))
    # Acciones correctivas por vencer / vencidas: una vez por dia, a las 8 (la clave evita repetir).
    _scheduler.add_job(acciones_seguridad, "cron", hour=8, minute=0, id="push_acciones_seguridad", max_instances=1,
                       coalesce=True)
    # Vacaciones: una vez por dia, a las 9 (las claves evitan repetir si el proceso reinicia).
    _scheduler.add_job(vacaciones, "cron", hour=9, minute=0, id="push_vacaciones", max_instances=1, coalesce=True)
    _scheduler.start()


def shutdown_push_scheduler(wait=True):
    global _scheduler
    if _scheduler is not None:
        _scheduler.shutdown(wait=wait)
        _scheduler = None
