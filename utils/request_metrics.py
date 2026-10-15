"""Metricas de rendimiento propias de la app (modulo Rendimiento del panel).

Cada pedido suma a un acumulador en memoria por (hora, ruta, metodo); un hilo
vuelca los acumulados a request_metrics_hourly cada FLUSH_SECONDS, asi no se
escribe en la base en cada pedido. La distribucion de tiempos se guarda en
cubetas (histograma) para estimar percentiles sin guardar cada pedido.
"""
import atexit
import logging
import threading
from datetime import datetime, timedelta, timezone

ARGENTINA = timezone(timedelta(hours=-3))
# Limites superiores en ms; la ultima cubeta es "mas de 5000 ms".
BUCKET_LIMITS = (100, 250, 500, 1000, 2000, 5000)
BUCKET_COLUMNS = ("b100", "b250", "b500", "b1000", "b2000", "b5000", "binf")
FLUSH_SECONDS = 60
RETENTION_DAYS = 90
# Tope de claves pendientes: si la base no responde no se crece sin limite.
MAX_PENDING_KEYS = 5000
# Rutas que no aportan al analisis (chequeo de salud de Railway, estaticos).
IGNORED_PATHS = ("/healthz", "/csp-report")
IGNORED_PREFIXES = ("/static/",)

logger = logging.getLogger(__name__)
_lock = threading.Lock()
_pending = {}
_flusher_started = False


def _empty_row():
    return {"pedidos": 0, "errores": 0, "ms_total": 0.0, "ms_max": 0.0,
            "db_ms_total": 0.0, "db_consultas": 0, "buckets": [0] * len(BUCKET_COLUMNS)}


def bucket_index(ms):
    for index, limit in enumerate(BUCKET_LIMITS):
        if ms <= limit:
            return index
    return len(BUCKET_LIMITS)


def should_record(path):
    return path not in IGNORED_PATHS and not path.startswith(IGNORED_PREFIXES)


def record(ruta, metodo, status, ms, db_ms=0.0, db_queries=0, now=None):
    now = now or datetime.now(ARGENTINA)
    hora = now.replace(minute=0, second=0, microsecond=0, tzinfo=None)
    key = (hora, str(ruta)[:190], str(metodo)[:8])
    with _lock:
        row = _pending.get(key)
        if row is None:
            if len(_pending) >= MAX_PENDING_KEYS:
                return
            row = _pending[key] = _empty_row()
        row["pedidos"] += 1
        row["errores"] += 1 if status >= 500 else 0
        row["ms_total"] += ms
        row["ms_max"] = max(row["ms_max"], ms)
        row["db_ms_total"] += db_ms or 0.0
        row["db_consultas"] += db_queries or 0
        row["buckets"][bucket_index(ms)] += 1


def _drain():
    with _lock:
        data = dict(_pending)
        _pending.clear()
    return data


def _restore(data):
    """Si el volcado falla, los datos vuelven al acumulador para el proximo intento."""
    with _lock:
        for key, row in data.items():
            current = _pending.get(key)
            if current is None:
                if len(_pending) < MAX_PENDING_KEYS:
                    _pending[key] = row
                continue
            for field in ("pedidos", "errores", "ms_total", "db_ms_total", "db_consultas"):
                current[field] += row[field]
            current["ms_max"] = max(current["ms_max"], row["ms_max"])
            current["buckets"] = [a + b for a, b in zip(current["buckets"], row["buckets"])]


def flush():
    data = _drain()
    if not data:
        return 0
    from repositories.request_metrics_repository import upsert_hourly
    try:
        upsert_hourly(data)
    except Exception:
        logger.warning("request_metrics_flush_error", exc_info=True)
        _restore(data)
        return 0
    return len(data)


def _flush_loop(stop_event):
    from repositories.request_metrics_repository import purge_older_than
    cycles = 0
    while not stop_event.wait(FLUSH_SECONDS):
        flush()
        cycles += 1
        if cycles % 60 == 0:  # una vez por hora
            try:
                purge_older_than(RETENTION_DAYS)
            except Exception:
                logger.warning("request_metrics_purge_error", exc_info=True)


def start_flusher():
    """Arranca el hilo de volcado (uno por proceso) y vuelca al terminar."""
    global _flusher_started
    with _lock:
        if _flusher_started:
            return
        _flusher_started = True
    stop_event = threading.Event()
    threading.Thread(target=_flush_loop, args=(stop_event,), name="request-metrics", daemon=True).start()

    def _final_flush():
        stop_event.set()
        flush()

    atexit.register(_final_flush)
