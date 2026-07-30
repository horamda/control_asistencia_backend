from extensions import get_db


def existe_calificacion(empleado_id: int, version_app: str | None) -> bool:
    """Retorna True si el empleado ya calificó esa versión de la app."""
    db = get_db()
    cur = db.cursor(dictionary=True)
    try:
        if version_app:
            cur.execute(
                "SELECT 1 FROM app_calificaciones "
                "WHERE empleado_id = %s AND version_app = %s LIMIT 1",
                (int(empleado_id), version_app),
            )
        else:
            cur.execute(
                "SELECT 1 FROM app_calificaciones "
                "WHERE empleado_id = %s AND version_app IS NULL LIMIT 1",
                (int(empleado_id),),
            )
        return cur.fetchone() is not None
    finally:
        cur.close(); db.close()


def create_calificacion(data: dict) -> int:
    db = get_db()
    cur = db.cursor()
    try:
        cur.execute(
            """
            INSERT INTO app_calificaciones
                (empleado_id, dni, puntuacion, comentario, pantalla, version_app)
            VALUES (%s, %s, %s, %s, %s, %s)
            """,
            (
                int(data["empleado_id"]),
                str(data["dni"]),
                int(data["puntuacion"]),
                data.get("comentario") or None,
                data.get("pantalla") or None,
                data.get("version_app") or None,
            ),
        )
        db.commit()
        return cur.lastrowid
    finally:
        cur.close(); db.close()


def get_estadisticas(version_app: str | None = None) -> dict:
    db = get_db()
    cur = db.cursor(dictionary=True)
    try:
        where = "WHERE c.version_app = %s" if version_app else ""
        params = (version_app,) if version_app else ()
        cur.execute(
            f"""
            SELECT
                COUNT(*)                                          AS total,
                ROUND(AVG(c.puntuacion), 2)                      AS promedio,
                SUM(c.puntuacion = 5)                            AS estrellas_5,
                SUM(c.puntuacion = 4)                            AS estrellas_4,
                SUM(c.puntuacion = 3)                            AS estrellas_3,
                SUM(c.puntuacion = 2)                            AS estrellas_2,
                SUM(c.puntuacion = 1)                            AS estrellas_1
            FROM app_calificaciones c
            {where}
            """,
            params,
        )
        row = cur.fetchone() or {}
        total = int(row.get("total") or 0)
        promedio = float(row.get("promedio") or 0)
        distribucion = []
        for stars in range(5, 0, -1):
            count = int(row.get(f"estrellas_{stars}") or 0)
            distribucion.append({
                "estrellas": stars,
                "cantidad": count,
                "porcentaje": round(count / total * 100, 1) if total else 0.0,
            })
        return {
            "total": total,
            "promedio": promedio,
            "distribucion": distribucion,
        }
    finally:
        cur.close(); db.close()


def get_versiones_disponibles() -> list[str]:
    db = get_db()
    cur = db.cursor()
    try:
        cur.execute(
            "SELECT DISTINCT version_app FROM app_calificaciones "
            "WHERE version_app IS NOT NULL ORDER BY version_app DESC"
        )
        return [r[0] for r in cur.fetchall()]
    finally:
        cur.close(); db.close()


def get_calificaciones_page(
    page: int,
    per_page: int,
    *,
    fecha_desde: str | None = None,
    fecha_hasta: str | None = None,
    sector_id: int | None = None,
    sucursal_id: int | None = None,
    version_app: str | None = None,
    puntuacion: int | None = None,
) -> tuple[list[dict], int]:
    db = get_db()
    cur = db.cursor(dictionary=True)
    try:
        conditions = []
        params: list = []

        if fecha_desde:
            conditions.append("c.fecha >= %s")
            params.append(fecha_desde)
        if fecha_hasta:
            conditions.append("c.fecha <= %s")
            params.append(fecha_hasta + " 23:59:59")
        if sector_id:
            conditions.append("e.sector_id = %s")
            params.append(int(sector_id))
        if sucursal_id:
            conditions.append("e.sucursal_id = %s")
            params.append(int(sucursal_id))
        if version_app:
            conditions.append("c.version_app = %s")
            params.append(version_app)
        if puntuacion:
            conditions.append("c.puntuacion = %s")
            params.append(int(puntuacion))

        where = ("WHERE " + " AND ".join(conditions)) if conditions else ""

        cur.execute(
            f"SELECT COUNT(*) AS n FROM app_calificaciones c "
            f"JOIN empleados e ON e.id = c.empleado_id {where}",
            params,
        )
        total = int((cur.fetchone() or {}).get("n", 0))

        offset = (page - 1) * per_page
        cur.execute(
            f"""
            SELECT
                c.id,
                c.puntuacion,
                c.comentario,
                c.pantalla,
                c.version_app,
                c.fecha,
                e.dni,
                CONCAT(e.apellido, ' ', e.nombre) AS empleado_nombre,
                s.nombre AS sector_nombre,
                suc.nombre AS sucursal_nombre
            FROM app_calificaciones c
            JOIN empleados e ON e.id = c.empleado_id
            LEFT JOIN sectores s ON s.id = e.sector_id
            LEFT JOIN sucursales suc ON suc.id = e.sucursal_id
            {where}
            ORDER BY c.fecha DESC
            LIMIT %s OFFSET %s
            """,
            params + [per_page, offset],
        )
        rows = cur.fetchall() or []
        for r in rows:
            if hasattr(r.get("fecha"), "isoformat"):
                r["fecha"] = r["fecha"].isoformat(sep=" ", timespec="minutes")
        return list(rows), total
    finally:
        cur.close(); db.close()
