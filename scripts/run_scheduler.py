"""Dedicated scheduler. A DB advisory lock elects one process across replicas."""
import logging
import signal
import sys
from pathlib import Path
from threading import Event
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from extensions import get_db, init_db
from utils.trivia_scheduler import init_trivia_scheduler, shutdown_trivia_scheduler
from utils.reintegro_scheduler import init_reintegro_scheduler
from utils.egreso_automatico_scheduler import init_egreso_automatico_scheduler, shutdown_egreso_automatico_scheduler
from types import SimpleNamespace


def main():
    logging.basicConfig(level=logging.INFO)
    stop = Event()
    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, lambda *_: stop.set())
    init_db()
    db = get_db()
    cursor = db.cursor()
    started = False
    try:
        while not stop.is_set():
            cursor.execute("SELECT GET_LOCK(CONCAT(DATABASE(), ':scheduler'), 0)")
            if cursor.fetchone()[0] == 1:
                break
            stop.wait(15)
        if stop.is_set():
            return
        app = SimpleNamespace(logger=logging.getLogger('scheduler'))
        init_trivia_scheduler(app)
        init_reintegro_scheduler(app)
        init_egreso_automatico_scheduler(app)
        started = True
        while not stop.wait(15):
            # Do not reconnect: losing the owning connection must stop this process.
            cursor.execute("SELECT IS_USED_LOCK(CONCAT(DATABASE(), ':scheduler')) = CONNECTION_ID()")
            if cursor.fetchone()[0] != 1:
                raise RuntimeError('Scheduler lost its database lock.')
    finally:
        if started:
            shutdown_trivia_scheduler(wait=True)
            from utils import reintegro_scheduler
            if reintegro_scheduler._scheduler:
                reintegro_scheduler._scheduler.shutdown(wait=True)
            shutdown_egreso_automatico_scheduler(wait=True)
        cursor.close()
        db.close()


if __name__ == '__main__':
    main()
