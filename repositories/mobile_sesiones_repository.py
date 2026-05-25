from extensions import get_db


def create_sesion(data: dict) -> int:
    db = get_db()
    cur = db.cursor()
    try:
        cur.execute(
            """
            INSERT INTO mobile_sesiones
                (empleado_id, dni, ip, platform, device_model, app_version)
            VALUES (%s, %s, %s, %s, %s, %s)
            """,
            (
                int(data["empleado_id"]),
                str(data["dni"]),
                data.get("ip") or None,
                data.get("platform") or None,
                data.get("device_model") or None,
                data.get("app_version") or None,
            ),
        )
        db.commit()
        return cur.lastrowid
    finally:
        cur.close()
        db.close()


def update_ultimo_request(sesion_id: int) -> None:
    db = get_db()
    cur = db.cursor()
    try:
        cur.execute(
            "UPDATE mobile_sesiones SET fecha_ultimo_request = NOW() WHERE id = %s",
            (sesion_id,),
        )
        db.commit()
    finally:
        cur.close()
        db.close()


def get_stats() -> dict:
    db = get_db()
    cur = db.cursor(dictionary=True)
    try:
        cur.execute("""
            SELECT
                COUNT(*)                                                      AS total_sesiones,
                COUNT(DISTINCT empleado_id)                                   AS usuarios_totales,
                SUM(fecha_login >= DATE_SUB(NOW(), INTERVAL 1 DAY))          AS sesiones_hoy,
                SUM(fecha_login >= DATE_SUB(NOW(), INTERVAL 7 DAY))          AS sesiones_7d,
                COUNT(DISTINCT CASE
                    WHEN fecha_login >= DATE_SUB(NOW(), INTERVAL 7 DAY)
                    THEN empleado_id END)                                      AS usuarios_activos_7d,
                COUNT(DISTINCT CASE
                    WHEN fecha_login >= DATE_SUB(NOW(), INTERVAL 30 DAY)
                    THEN empleado_id END)                                      AS usuarios_activos_30d,
                SUM(platform = 'android')                                     AS android,
                SUM(platform = 'ios')                                         AS ios,
                SUM(platform IS NULL)                                         AS platform_desconocida
            FROM mobile_sesiones
        """)
        row = cur.fetchone() or {}

        cur.execute("""
            SELECT app_version, COUNT(*) AS n
            FROM mobile_sesiones
            WHERE app_version IS NOT NULL
              AND fecha_login >= DATE_SUB(NOW(), INTERVAL 30 DAY)
            GROUP BY app_version
            ORDER BY n DESC
            LIMIT 10
        """)
        versiones = [{"version": r["app_version"], "sesiones": int(r["n"])} for r in cur.fetchall()]

        cur.execute("""
            SELECT DATE(fecha_login) AS dia, COUNT(*) AS n
            FROM mobile_sesiones
            WHERE fecha_login >= DATE_SUB(NOW(), INTERVAL 30 DAY)
            GROUP BY dia
            ORDER BY dia
        """)
        actividad_diaria = [
            {"dia": str(r["dia"]), "sesiones": int(r["n"])}
            for r in cur.fetchall()
        ]

        return {
            "total_sesiones": int(row.get("total_sesiones") or 0),
            "usuarios_totales": int(row.get("usuarios_totales") or 0),
            "sesiones_hoy": int(row.get("sesiones_hoy") or 0),
            "sesiones_7d": int(row.get("sesiones_7d") or 0),
            "usuarios_activos_7d": int(row.get("usuarios_activos_7d") or 0),
            "usuarios_activos_30d": int(row.get("usuarios_activos_30d") or 0),
            "android": int(row.get("android") or 0),
            "ios": int(row.get("ios") or 0),
            "platform_desconocida": int(row.get("platform_desconocida") or 0),
            "versiones_30d": versiones,
            "actividad_diaria": actividad_diaria,
        }
    finally:
        cur.close()
        db.close()


def get_sesiones_page(
    page: int,
    per_page: int,
    *,
    fecha_desde: str | None = None,
    fecha_hasta: str | None = None,
    platform: str | None = None,
    app_version: str | None = None,
    empleado_q: str | None = None,
) -> tuple[list[dict], int]:
    db = get_db()
    cur = db.cursor(dictionary=True)
    try:
        conditions = []
        params: list = []

        if fecha_desde:
            conditions.append("s.fecha_login >= %s")
            params.append(fecha_desde)
        if fecha_hasta:
            conditions.append("s.fecha_login <= %s")
            params.append(fecha_hasta + " 23:59:59")
        if platform:
            conditions.append("s.platform = %s")
            params.append(platform)
        if app_version:
            conditions.append("s.app_version = %s")
            params.append(app_version)
        if empleado_q:
            conditions.append(
                "(e.dni LIKE %s OR CONCAT(e.apellido, ' ', e.nombre) LIKE %s)"
            )
            q = f"%{empleado_q}%"
            params += [q, q]

        where = ("WHERE " + " AND ".join(conditions)) if conditions else ""

        cur.execute(
            f"SELECT COUNT(*) AS n FROM mobile_sesiones s "
            f"JOIN empleados e ON e.id = s.empleado_id {where}",
            params,
        )
        total = int((cur.fetchone() or {}).get("n", 0))

        offset = (page - 1) * per_page
        cur.execute(
            f"""
            SELECT
                s.id,
                s.dni,
                CONCAT(e.apellido, ' ', e.nombre) AS empleado_nombre,
                sec.nombre                         AS sector_nombre,
                s.ip,
                s.platform,
                s.device_model,
                s.app_version,
                s.fecha_login,
                s.fecha_ultimo_request
            FROM mobile_sesiones s
            JOIN empleados e ON e.id = s.empleado_id
            LEFT JOIN sectores sec ON sec.id = e.sector_id
            {where}
            ORDER BY s.fecha_login DESC
            LIMIT %s OFFSET %s
            """,
            params + [per_page, offset],
        )
        rows = list(cur.fetchall() or [])
        for r in rows:
            for col in ("fecha_login", "fecha_ultimo_request"):
                if hasattr(r.get(col), "isoformat"):
                    r[col] = r[col].isoformat(sep=" ", timespec="minutes")
        return rows, total
    finally:
        cur.close()
        db.close()


def get_versiones_disponibles() -> list[str]:
    db = get_db()
    cur = db.cursor()
    try:
        cur.execute(
            "SELECT DISTINCT app_version FROM mobile_sesiones "
            "WHERE app_version IS NOT NULL ORDER BY app_version DESC"
        )
        return [r[0] for r in cur.fetchall()]
    finally:
        cur.close()
        db.close()
