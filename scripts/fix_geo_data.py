from __future__ import annotations

import argparse
from dataclasses import dataclass
import pathlib
import sys
from typing import Iterable

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from extensions import get_db, init_db


@dataclass(frozen=True, slots=True)
class GeoPoint:
    latitud: float
    longitud: float


LOCALIDAD_POINTS: dict[str, GeoPoint] = {
    "DOLORES": GeoPoint(-36.3153624, -57.6755399),
    "GENERAL LAVALLE": GeoPoint(-36.4063403, -56.9432260),
    "LA LUCILA DEL MAR": GeoPoint(-36.6584442, -56.6928018),
    "MAR DE AJO": GeoPoint(-36.7212921, -56.6776091),
    "MAR DEL TUYU": GeoPoint(-36.5813187, -56.6874786),
    "SAN BERNARDO DEL TUYU": GeoPoint(-36.6865934, -56.6841459),
    "SAN CLEMENTE DEL TUYU": GeoPoint(-36.3560513, -56.7194301),
    "SANTA TERESITA": GeoPoint(-36.5431401, -56.7043746),
}

SUCURSAL_POINTS: dict[str, GeoPoint] = {
    "CASA CENTRAL": GeoPoint(-36.3226892, -57.6801836),
    "DOLORES": GeoPoint(-36.3057885, -57.6844726),
}


def _normalize_name(value: str | None) -> str:
    return str(value or "").strip().upper()


def _looks_inverted(latitud, longitud) -> bool:
    if latitud in (None, 0, 0.0) or longitud in (None, 0, 0.0):
        return False
    try:
        lat = float(latitud)
        lon = float(longitud)
    except (TypeError, ValueError):
        return False
    return abs(lat) > 45 and abs(lon) > 30 and abs(lat) > abs(lon)


def _swap_point(latitud, longitud) -> GeoPoint:
    return GeoPoint(latitud=float(longitud), longitud=float(latitud))


def _update_many(cursor, sql: str, params: Iterable[tuple]) -> int:
    changed = 0
    for item in params:
        cursor.execute(sql, item)
        changed += cursor.rowcount if cursor.rowcount != -1 else 0
    return changed


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Corrige coordenadas invertidas o incompletas en los datos geo.")
    parser.add_argument("--dry-run", action="store_true", help="Muestra cambios sin guardarlos.")
    return parser


def main() -> int:
    args = _build_parser().parse_args()
    init_db()

    db = get_db()
    cursor = db.cursor(dictionary=True)
    try:
        cursor.execute(
            """
            SELECT id, descripcion_localidad, latitud, longitud, activo
            FROM feedback_clientes
            ORDER BY id
            """
        )
        clientes = cursor.fetchall()

        feedback_updates: list[tuple[float, float, int]] = []
        for row in clientes:
            locality = _normalize_name(row.get("descripcion_localidad"))
            latitud = row.get("latitud")
            longitud = row.get("longitud")

            if _looks_inverted(latitud, longitud):
                point = _swap_point(latitud, longitud)
            elif latitud in (None, 0, 0.0) or longitud in (None, 0, 0.0):
                point = LOCALIDAD_POINTS.get(locality)
                if point is None:
                    continue
            else:
                continue

            feedback_updates.append((point.latitud, point.longitud, int(row["id"])))

        cursor.execute(
            """
            SELECT id, nombre, latitud, longitud
            FROM sucursales
            ORDER BY id
            """
        )
        sucursales = cursor.fetchall()
        sucursal_updates: list[tuple[float, float, int]] = []
        for row in sucursales:
            point = SUCURSAL_POINTS.get(_normalize_name(row.get("nombre")))
            if not point:
                continue
            if row.get("latitud") == point.latitud and row.get("longitud") == point.longitud:
                continue
            sucursal_updates.append((point.latitud, point.longitud, int(row["id"])))

        cursor.execute(
            """
            SELECT id, sucursal_id, activo, geo_lat, geo_lon
            FROM qr_puerta_historial
            WHERE activo = 1
            ORDER BY id
            """
        )
        qr_rows = cursor.fetchall()
        qr_updates: list[tuple[float, float, int]] = []
        for row in qr_rows:
            point = None
            if row.get("sucursal_id") == 1:
                point = SUCURSAL_POINTS["CASA CENTRAL"]
            elif row.get("sucursal_id") == 2:
                point = SUCURSAL_POINTS["DOLORES"]
            if not point:
                continue
            if row.get("geo_lat") == point.latitud and row.get("geo_lon") == point.longitud:
                continue
            qr_updates.append((point.latitud, point.longitud, int(row["id"])))

        summary = {
            "feedback_clientes": len(feedback_updates),
            "sucursales": len(sucursal_updates),
            "qr_puerta_historial": len(qr_updates),
        }

        if args.dry_run:
            print(summary)
            return 0

        _update_many(
            cursor,
            "UPDATE feedback_clientes SET latitud = %s, longitud = %s WHERE id = %s",
            feedback_updates,
        )
        _update_many(
            cursor,
            "UPDATE sucursales SET latitud = %s, longitud = %s WHERE id = %s",
            sucursal_updates,
        )
        _update_many(
            cursor,
            "UPDATE qr_puerta_historial SET geo_lat = %s, geo_lon = %s WHERE id = %s",
            qr_updates,
        )
        db.commit()
        print(summary)
        return 0
    except Exception:
        db.rollback()
        raise
    finally:
        cursor.close()
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
