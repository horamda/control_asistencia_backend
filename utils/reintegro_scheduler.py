"""Hourly checks deliver one in-app reminder per employee on the local 5th."""

import logging
from datetime import datetime
from zoneinfo import ZoneInfo
from apscheduler.schedulers.background import BackgroundScheduler
from services.reintegro_monthly_service import generate_reminders

_scheduler = None


def run():
    try:
        generate_reminders()
    except Exception:
        logging.getLogger(__name__).exception(
            "Error generando recordatorios de viáticos"
        )


def init_reintegro_scheduler(app):
    global _scheduler
    if _scheduler is not None:
        return
    zone = ZoneInfo("America/Argentina/Buenos_Aires")
    _scheduler = BackgroundScheduler(daemon=True, timezone=zone)
    _scheduler.add_job(
        run,
        "interval",
        hours=1,
        id="reintegros_recordatorio",
        max_instances=1,
        next_run_time=datetime.now(zone),
        coalesce=True,
    )
    _scheduler.start()
