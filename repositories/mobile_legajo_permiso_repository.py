from __future__ import annotations

from extensions import get_db


PERMISO_CARGAR_EVENTOS_LEGAJO = "legajos.eventos.mobile.create"
ALCANCES_VALIDOS = {"global", "empresa", "sucursal", "sector", "equipo", "propio"}


def get_permiso(empleado_id: int, permiso: str = PERMISO_CARGAR_EVENTOS_LEGAJO) -> dict | None:
    db = get_db()
    cursor = db.cursor(dictionary=True)
    try:
        cursor.execute(
            """
            SELECT id, empleado_id, permiso, alcance, activo
            FROM empleado_mobile_permisos
            WHERE empleado_id = %s
              AND permiso = %s
              AND activo = 1
            LIMIT 1
            """,
            (int(empleado_id), permiso),
        )
        return cursor.fetchone()
    finally:
        cursor.close()
        db.close()


def has_permiso(empleado_id: int, permiso: str = PERMISO_CARGAR_EVENTOS_LEGAJO) -> bool:
    return get_permiso(empleado_id, permiso) is not None


def alcance_permiso(empleado_id: int, permiso: str = PERMISO_CARGAR_EVENTOS_LEGAJO) -> str | None:
    row = get_permiso(empleado_id, permiso)
    if not row:
        return None
    alcance = str(row.get("alcance") or "sector").strip().lower()
    return alcance if alcance in ALCANCES_VALIDOS else "sector"


def get_page(
    page: int,
    per_page: int,
    *,
    search: str | None = None,
    activo: int | None = None,
) -> tuple[list[dict], int]:
    db = get_db()
    cursor = db.cursor(dictionary=True)
    try:
        offset = max(0, (int(page) - 1) * int(per_page))
        where = ["p.permiso = %s"]
        params = [PERMISO_CARGAR_EVENTOS_LEGAJO]
        if activo in (0, 1):
            where.append("p.activo = %s")
            params.append(int(activo))
        if search:
            like = f"%{search}%"
            where.append("(e.apellido LIKE %s OR e.nombre LIKE %s OR e.dni LIKE %s OR e.legajo LIKE %s)")
            params.extend([like, like, like, like])
        where_sql = "WHERE " + " AND ".join(where)

        cursor.execute(
            f"""
            SELECT
                p.id,
                p.empleado_id,
                p.permiso,
                p.alcance,
                p.activo,
                p.created_at,
                p.updated_at,
                e.apellido,
                e.nombre,
                e.dni,
                e.legajo,
                emp.razon_social AS empresa_nombre,
                s.nombre AS sucursal_nombre,
                sec.nombre AS sector_nombre
            FROM empleado_mobile_permisos p
            JOIN empleados e ON e.id = p.empleado_id
            LEFT JOIN empresas emp ON emp.id = e.empresa_id
            LEFT JOIN sucursales s ON s.id = e.sucursal_id
            LEFT JOIN sectores sec ON sec.id = e.sector_id
            {where_sql}
            ORDER BY p.activo DESC, e.apellido, e.nombre
            LIMIT %s OFFSET %s
            """,
            (*params, int(per_page), offset),
        )
        rows = cursor.fetchall()

        cursor.execute(
            f"""
            SELECT COUNT(*) AS total
            FROM empleado_mobile_permisos p
            JOIN empleados e ON e.id = p.empleado_id
            {where_sql}
            """,
            tuple(params),
        )
        total = int((cursor.fetchone() or {}).get("total") or 0)
        return rows, total
    finally:
        cursor.close()
        db.close()


def upsert_permiso(
    empleado_id: int,
    *,
    alcance: str,
    activo: int = 1,
    permiso: str = PERMISO_CARGAR_EVENTOS_LEGAJO,
) -> None:
    alcance = str(alcance or "sector").strip().lower()
    if alcance not in ALCANCES_VALIDOS:
        raise ValueError("Alcance invalido.")
    db = get_db()
    cursor = db.cursor()
    try:
        cursor.execute(
            """
            INSERT INTO empleado_mobile_permisos (empleado_id, permiso, alcance, activo)
            VALUES (%s, %s, %s, %s)
            ON DUPLICATE KEY UPDATE
                alcance = VALUES(alcance),
                activo = VALUES(activo)
            """,
            (int(empleado_id), permiso, alcance, 1 if activo else 0),
        )
        db.commit()
    finally:
        cursor.close()
        db.close()


def set_activo(permiso_id: int, activo: int) -> bool:
    db = get_db()
    cursor = db.cursor()
    try:
        cursor.execute(
            """
            UPDATE empleado_mobile_permisos
            SET activo = %s
            WHERE id = %s
            """,
            (1 if activo else 0, int(permiso_id)),
        )
        db.commit()
        return cursor.rowcount > 0
    finally:
        cursor.close()
        db.close()
