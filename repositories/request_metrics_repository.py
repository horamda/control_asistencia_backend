from extensions import get_db
from utils.request_metrics import BUCKET_COLUMNS

_SUM_COLUMNS = ("pedidos", "errores", "ms_total", "db_ms_total", "db_consultas", *BUCKET_COLUMNS)
_SUMS_SQL = ", ".join(f"SUM({c}) AS {c}" for c in _SUM_COLUMNS) + ", MAX(ms_max) AS ms_max"


def upsert_hourly(data: dict) -> None:
    """Suma los acumulados de memoria a la fila de la hora (puede haber varios
    procesos o volcados por hora)."""
    columns = ("hora", "ruta", "metodo", "pedidos", "errores", "ms_total", "ms_max",
               "db_ms_total", "db_consultas", *BUCKET_COLUMNS)
    updates = ", ".join(
        f"{c} = GREATEST({c}, VALUES({c}))" if c == "ms_max" else f"{c} = {c} + VALUES({c})"
        for c in columns[3:]
    )
    sql = (
        f"INSERT INTO request_metrics_hourly ({', '.join(columns)}) "
        f"VALUES ({', '.join(['%s'] * len(columns))}) ON DUPLICATE KEY UPDATE {updates}"
    )
    params = [
        (hora, ruta, metodo, row["pedidos"], row["errores"], row["ms_total"], row["ms_max"],
         row["db_ms_total"], row["db_consultas"], *row["buckets"])
        for (hora, ruta, metodo), row in data.items()
    ]
    db = get_db()
    cursor = db.cursor()
    try:
        cursor.executemany(sql, params)
        db.commit()
    finally:
        cursor.close()
        db.close()


def purge_older_than(days: int) -> None:
    db = get_db()
    cursor = db.cursor()
    try:
        cursor.execute("DELETE FROM request_metrics_hourly WHERE hora < NOW() - INTERVAL %s DAY", (int(days),))
        db.commit()
    finally:
        cursor.close()
        db.close()


def get_report_data(desde, *, por_dia: bool, limite_rutas: int = 15) -> dict:
    """Totales, serie temporal (por hora o por dia) y rutas con mas tiempo total."""
    periodo = "DATE(hora)" if por_dia else "hora"
    db = get_db()
    cursor = db.cursor(dictionary=True)
    try:
        cursor.execute(f"SELECT {_SUMS_SQL} FROM request_metrics_hourly WHERE hora >= %s", (desde,))
        totales = cursor.fetchone() or {}
        cursor.execute(
            f"SELECT {periodo} AS periodo, {_SUMS_SQL} FROM request_metrics_hourly "
            f"WHERE hora >= %s GROUP BY {periodo} ORDER BY periodo",
            (desde,),
        )
        serie = cursor.fetchall()
        cursor.execute(
            f"SELECT ruta, metodo, {_SUMS_SQL} FROM request_metrics_hourly WHERE hora >= %s "
            f"GROUP BY ruta, metodo ORDER BY SUM(ms_total) DESC LIMIT %s",
            (desde, int(limite_rutas)),
        )
        rutas = cursor.fetchall()
    finally:
        cursor.close()
        db.close()
    return {"totales": totales, "serie": serie, "rutas": rutas}
