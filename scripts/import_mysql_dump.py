import argparse
import os
import sys
from pathlib import Path

import mysql.connector


DEFAULT_DUMP = r"C:\Users\horac\Downloads\ht627842_rrhh.sql"


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Importa un dump SQL MySQL/MariaDB en una base remota."
    )
    parser.add_argument("--dump", default=os.getenv("MYSQL_DUMP_PATH", DEFAULT_DUMP))
    parser.add_argument("--host", default=os.getenv("MYSQL_IMPORT_HOST"))
    parser.add_argument("--port", type=int, default=int(os.getenv("MYSQL_IMPORT_PORT", "3306")))
    parser.add_argument("--user", default=os.getenv("MYSQL_IMPORT_USER"))
    parser.add_argument("--password", default=os.getenv("MYSQL_IMPORT_PASSWORD"))
    parser.add_argument("--database", default=os.getenv("MYSQL_IMPORT_DATABASE"))
    parser.add_argument(
        "--drop-existing",
        action="store_true",
        help="Elimina tablas existentes antes de importar. Usar solo en base destino descartable.",
    )
    return parser


def _require(value: str | None, name: str) -> str:
    if value:
        return value
    raise SystemExit(f"Falta {name}. Pasalo por argumento o variable de entorno.")


def _strip_delimiter(statement: str, delimiter: str) -> str:
    trimmed = statement.rstrip()
    if delimiter and trimmed.endswith(delimiter):
        trimmed = trimmed[: -len(delimiter)].rstrip()
    return trimmed


def iter_sql_statements(path: Path):
    delimiter = ";"
    buffer: list[str] = []

    with path.open("r", encoding="utf-8-sig", errors="strict") as dump:
        for line in dump:
            stripped = line.strip()
            if stripped.upper().startswith("DELIMITER "):
                if buffer and "".join(buffer).strip():
                    yield _strip_delimiter("".join(buffer), delimiter)
                    buffer = []
                delimiter = stripped.split(None, 1)[1]
                continue

            buffer.append(line)
            if stripped.endswith(delimiter):
                statement = _strip_delimiter("".join(buffer), delimiter)
                buffer = []
                if statement.strip():
                    yield statement

    if buffer and "".join(buffer).strip():
        yield "".join(buffer)


def _drop_existing_tables(cursor) -> int:
    cursor.execute(
        """
        SELECT TABLE_NAME
        FROM information_schema.TABLES
        WHERE TABLE_SCHEMA = DATABASE()
        """
    )
    tables = [row[0] for row in cursor.fetchall()]
    if not tables:
        return 0

    cursor.execute("SET FOREIGN_KEY_CHECKS=0")
    try:
        for table in tables:
            safe_table = table.replace("`", "``")
            cursor.execute(f"DROP TABLE `{safe_table}`")
    finally:
        cursor.execute("SET FOREIGN_KEY_CHECKS=1")
    return len(tables)


def _index_exists(cursor, table_name: str, index_name: str) -> bool:
    cursor.execute(
        """
        SELECT 1
        FROM information_schema.STATISTICS
        WHERE TABLE_SCHEMA = DATABASE()
          AND TABLE_NAME = %s
          AND INDEX_NAME = %s
        LIMIT 1
        """,
        (table_name, index_name),
    )
    return cursor.fetchone() is not None


def _ensure_mysql_compat_indexes(cursor) -> None:
    # MariaDB accepted these composite references with a non-unique helper index.
    # Railway MySQL requires a unique key on the exact referenced column set.
    if not _index_exists(cursor, "empleados", "uk_empleados_id_empresa"):
        cursor.execute(
            "ALTER TABLE `empleados` "
            "ADD UNIQUE KEY `uk_empleados_id_empresa` (`id`, `empresa_id`)"
        )


def main() -> int:
    args = _build_parser().parse_args()
    dump_path = Path(args.dump)
    if not dump_path.exists():
        raise SystemExit(f"No existe el dump: {dump_path}")

    host = _require(args.host, "MYSQL_IMPORT_HOST")
    user = _require(args.user, "MYSQL_IMPORT_USER")
    password = _require(args.password, "MYSQL_IMPORT_PASSWORD")
    database = _require(args.database, "MYSQL_IMPORT_DATABASE")

    conn = mysql.connector.connect(
        host=host,
        port=args.port,
        user=user,
        password=password,
        database=database,
        autocommit=False,
        connection_timeout=30,
        charset="utf8mb4",
        use_unicode=True,
    )
    cursor = conn.cursor()
    count = 0

    try:
        if args.drop_existing:
            dropped = _drop_existing_tables(cursor)
            conn.commit()
            print(f"Tablas eliminadas antes de importar: {dropped}")

        cursor.execute("SET FOREIGN_KEY_CHECKS=0")
        cursor.execute("SET UNIQUE_CHECKS=0")

        for statement in iter_sql_statements(dump_path):
            sql = statement.strip()
            if not sql:
                continue
            if "ADD CONSTRAINT" in sql:
                _ensure_mysql_compat_indexes(cursor)
            cursor.execute(sql)
            count += 1
            if count % 50 == 0:
                conn.commit()
                print(f"Sentencias importadas: {count}")

        cursor.execute("SET UNIQUE_CHECKS=1")
        cursor.execute("SET FOREIGN_KEY_CHECKS=1")
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        cursor.close()
        conn.close()

    print(f"Importacion finalizada. Sentencias ejecutadas: {count}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
