"""Cierre de reuniones terminadas: ausentes y justificados (services/reunion_service)."""

import logging
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from apscheduler.schedulers.background import BackgroundScheduler
from services.reunion_service import cerrar_ocurrencias

_scheduler = None


def run():
    try:
        cerrar_ocurrencias()
    except Exception:
        logging.getLogger(__name__).exception("Error cerrando reuniones")


def init_reunion_scheduler(app):
    global _scheduler
    if _scheduler is not None:
        return
    zone = ZoneInfo("America/Argentina/Buenos_Aires")
    _scheduler = BackgroundScheduler(daemon=True, timezone=zone)
    # Cada 10 minutos: las ausencias quedan cargadas poco despues del cierre del registro.
    _scheduler.add_job(run, "interval", minutes=10, id="reuniones_cierre", max_instances=1, coalesce=True,
                       next_run_time=datetime.now(zone) + timedelta(minutes=1))
    _scheduler.start()


def shutdown_reunion_scheduler(wait=True):
    global _scheduler
    if _scheduler is not None:
        _scheduler.shutdown(wait=wait)
        _scheduler = None
