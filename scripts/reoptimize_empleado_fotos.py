import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from extensions import get_db
import services.profile_photo_service as photo_service


def _canonical_photo_url(dni: str):
    safe_dni = "".join(ch for ch in str(dni or "") if ch.isdigit())
    path = f"/media/empleados/foto/{safe_dni}"
    base = str(
        os.getenv("FOTO_PUBLIC_BASE_URL")
        or os.getenv("API_PUBLIC_BASE_URL")
        or ""
    ).strip()
    if base:
        return f"{base.rstrip('/')}/{path.lstrip('/')}"
    return path


def _ensure_photo_table(cursor):
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS empleado_fotos (
            dni VARCHAR(32) NOT NULL PRIMARY KEY,
            mime_type VARCHAR(32) NOT NULL,
            ext VARCHAR(8) NOT NULL,
            data LONGBLOB NOT NULL,
            updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """
    )


def run(dry_run: bool, only_dni: str | None, batch_size: int):
    max_bytes = int(os.getenv("FOTO_MAX_BYTES", "220000"))
    processed = 0
    changed = 0
    unchanged = 0
    failures = []
    url_synced = 0

    db = get_db()
    read_cursor = db.cursor(dictionary=True)
    write_cursor = db.cursor()
    try:
        _ensure_photo_table(write_cursor)
        db.commit()

        where_sql = ""
        params = []
        if only_dni:
            only_digits = "".join(ch for ch in str(only_dni) if ch.isdigit())
            where_sql = "WHERE dni = %s"
            params = [only_digits]

        read_cursor.execute(
            f"""
            SELECT dni, mime_type, ext, data
            FROM empleado_fotos
            {where_sql}
            ORDER BY dni
            """,
            params,
        )

        while True:
            rows = read_cursor.fetchmany(batch_size)
            if not rows:
                break

            for row in rows:
                processed += 1
                dni = "".join(ch for ch in str(row.get("dni") or "") if ch.isdigit())
                payload = bytes(row.get("data") or b"")

                try:
                    normalized, out_ext, out_mime = photo_service._normalize_profile_photo(
                        payload,
                        output_max_bytes=max_bytes,
                    )
                except Exception as exc:
                    failures.append(f"{dni}: {exc}")
                    continue

                same_binary = normalized == payload
                same_meta = (
                    str(row.get("ext") or "").strip().lower() == out_ext
                    and str(row.get("mime_type") or "").strip().lower() == out_mime
                )

                if same_binary and same_meta:
                    unchanged += 1
                else:
                    changed += 1
                    if not dry_run:
                        write_cursor.execute(
                            """
                            UPDATE empleado_fotos
                            SET mime_type = %s,
                                ext = %s,
                                data = %s
                            WHERE dni = %s
                            """,
                            (out_mime, out_ext, normalized, dni),
                        )

                if not dry_run:
                    canonical_url = _canonical_photo_url(dni)
                    write_cursor.execute(
                        """
                        UPDATE empleados
                        SET foto = %s
                        WHERE dni = %s
                          AND (foto IS NULL OR foto <> %s)
                        """,
                        (canonical_url, dni, canonical_url),
                    )
                    if write_cursor.rowcount > 0:
                        url_synced += int(write_cursor.rowcount)

        if dry_run:
            db.rollback()
        else:
            db.commit()
    finally:
        read_cursor.close()
        write_cursor.close()
        db.close()

    print(
        (
            f"[done] processed={processed} changed={changed} unchanged={unchanged} "
            f"url_synced={url_synced} failures={len(failures)} dry_run={int(dry_run)}"
        )
    )
    for item in failures[:50]:
        print(f"[fail] {item}")
    if len(failures) > 50:
        print(f"[fail] ... and {len(failures) - 50} more")

    return 0 if not failures else 2


def main():
    parser = argparse.ArgumentParser(
        description=(
            "Reoptimiza fotos de empleado_fotos usando la misma configuracion "
            "de FOTO_OUTPUT_* y sincroniza empleados.foto al endpoint /media."
        )
    )
    parser.add_argument("--dry-run", action="store_true", help="No persiste cambios.")
    parser.add_argument("--dni", help="Procesa solo un DNI especifico.")
    parser.add_argument(
        "--batch-size",
        type=int,
        default=100,
        help="Cantidad de registros por lote de lectura.",
    )
    args = parser.parse_args()

    batch_size = max(1, int(args.batch_size or 100))
    return run(dry_run=bool(args.dry_run), only_dni=args.dni, batch_size=batch_size)


if __name__ == "__main__":
    raise SystemExit(main())
