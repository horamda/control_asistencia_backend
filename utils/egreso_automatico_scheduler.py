"""Cierre nocturno de jornadas sin egreso (services/egreso_automatico_service)."""

import logging
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from apscheduler.schedulers.background import BackgroundScheduler
from services.egreso_automatico_service import cerrar_jornadas_abiertas

_scheduler = None


def run():
    try:
        cerrar_jornadas_abiertas()
    except Exception:
        logging.getLogger(__name__).exception("Error cerrando jornadas sin egreso")


def init_egreso_automatico_scheduler(app):
    global _scheduler
    if _scheduler is not None:
        return
    zone = ZoneInfo("America/Argentina/Buenos_Aires")
    _scheduler = BackgroundScheduler(daemon=True, timezone=zone)
    # Todas las noches, cuando ya no quedan jornadas del dia anterior en curso.
    _scheduler.add_job(run, "cron", hour=3, minute=30, id="egreso_automatico_nocturno",
                       max_instances=1, coalesce=True)
    # Y una vez al arrancar (p. ej. tras un deploy), para no esperar a la noche.
    _scheduler.add_job(run, "date", run_date=datetime.now(zone) + timedelta(minutes=2),
                       id="egreso_automatico_inicio", max_instances=1)
    _scheduler.start()


def shutdown_egreso_automatico_scheduler(wait=True):
    global _scheduler
    if _scheduler is not None:
        _scheduler.shutdown(wait=wait)
        _scheduler = None
