"""Notificaciones push: envia la cola cada minuto y encola recordatorios de reuniones cada 5 minutos.
Sin Firebase configurado los trabajos no hacen nada."""

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


def init_push_scheduler(app):
    global _scheduler
    if _scheduler is not None:
        return
    zone = ZoneInfo("America/Argentina/Buenos_Aires")
    _scheduler = BackgroundScheduler(daemon=True, timezone=zone)
    inicio = datetime.now(zone) + timedelta(seconds=30)
    _scheduler.add_job(recordar, "interval", minutes=5, id="push_recordatorios", max_instances=1, coalesce=True,
                       next_run_time=inicio)
    _scheduler.add_job(enviar, "interval", minutes=1, id="push_cola", max_instances=1, coalesce=True,
                       next_run_time=inicio + timedelta(seconds=15))
    _scheduler.start()


def shutdown_push_scheduler(wait=True):
    global _scheduler
    if _scheduler is not None:
        _scheduler.shutdown(wait=wait)
        _scheduler = None
