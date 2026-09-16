"""Audit by default; --apply adds only missing covering indexes online."""
import argparse
import datetime
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import mysql.connector
from db import _load_db_settings


INDEXES = (
    ("justificaciones", "idx_just_created_estado", ("created_at", "estado")),
    ("asistencias", "idx_asistencias_fecha_estado", ("fecha", "estado")),
)


def covering_index(indexes, columns):
    for name, parts in indexes.items():
        if tuple(parts[:len(columns)]) == tuple(columns):
            return name
    return None


def run(apply=False):
    settings = _load_db_settings()
    db = mysql.connector.connect(
        host=settings["host"], port=int(settings["port"]), user=settings["user"],
        password=settings["password"], database=settings["db"], connection_timeout=5,
    )
    cursor = db.cursor(dictionary=True)
    try:
        cursor.execute("SET SESSION lock_wait_timeout = 5")
        for table, name, columns in INDEXES:
            cursor.execute(f"SHOW INDEX FROM `{table}`")
            indexes = {}
            for row in sorted(cursor.fetchall(), key=lambda r: (r["Key_name"], r["Seq_in_index"])):
                # Prefix indexes cannot cover the full column.
                indexes.setdefault(row["Key_name"], []).append(
                    row["Column_name"] if row.get("Sub_part") is None else None)
            existing = covering_index(indexes, columns)
            if existing:
                print(f"SKIP {table}: covered by {existing}")
                continue
            if name in indexes:
                raise RuntimeError(f"Index {name} exists with different columns")
            definition = ", ".join(f"`{column}`" for column in columns)
            sql = f"ALTER TABLE `{table}` ADD INDEX `{name}` ({definition}), ALGORITHM=INPLACE, LOCK=NONE"
            if apply:
                cursor.execute(sql)
                print(f"CREATED {name}")
            else:
                print(f"PROPOSED {sql}")
        today = datetime.date.today()
        for label, query, params in (
            ("asistencias", "SELECT COUNT(*), COUNT(CASE WHEN estado='tarde' THEN 1 END) FROM asistencias WHERE fecha BETWEEN %s AND %s", (today.replace(day=1), today)),
            ("justificaciones", "SELECT COUNT(*), COUNT(CASE WHEN estado='aprobada' THEN 1 END) FROM justificaciones WHERE created_at >= %s AND created_at < %s", (today.replace(day=1), today + datetime.timedelta(days=1))),
        ):
            cursor.execute("EXPLAIN " + query, params)
            for row in cursor.fetchall():
                print(label, {key: row.get(key) for key in ("type", "key", "rows", "Extra")})
    finally:
        cursor.close()
        db.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    try:
        run(args.apply)
    except Exception as exc:
        # Never print connection strings or database credentials.
        print(f"FAILED: {type(exc).__name__}, errno={getattr(exc, 'errno', None)}", file=sys.stderr)
        sys.exit(1)
