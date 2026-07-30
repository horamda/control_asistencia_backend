from extensions import get_db


def get_all(include_inactive: bool = False, sector_id: int | None = None):
    db = get_db()
    cursor = db.cursor(dictionary=True)
    try:
        where = []
        if not include_inactive:
            where.append("m.activo = 1")
        params = []
        if sector_id:
            where.append("m.sector_id = %s")
            params.append(int(sector_id))
        where_sql = ("WHERE " + " AND ".join(where)) if where else ""
        cursor.execute(
            f"""
            SELECT
                m.*,
                COALESCE(m.tiempo_resolucion_valor, m.sla_dias, 1) AS tiempo_resolucion_valor,
                COALESCE(m.tiempo_resolucion_unidad, 'DIAS') AS tiempo_resolucion_unidad,
                COALESCE(m.requiere_foto, 0) AS requiere_foto,
                COALESCE(m.requiere_observacion, 1) AS requiere_observacion,
                sec.nombre AS sector_nombre,
                sec.responsable_empleado_id AS sector_responsable_empleado_id
            FROM feedback_motivos m
            LEFT JOIN sectores sec ON sec.id = m.sector_id
            {where_sql}
            ORDER BY m.activo DESC, m.nombre ASC
            """,
            params,
        )
        return cursor.fetchall()
    finally:
        cursor.close()
        db.close()


def get_page(
    page: int,
    per_page: int,
    *,
    search: str | None = None,
    activo: int | None = None,
    sector_id: int | None = None,
):
    db = get_db()
    cursor = db.cursor(dictionary=True)
    try:
        offset = max(0, (int(page) - 1) * int(per_page))
        where = []
        params = []
        if search:
            like = f"%{search}%"
            where.append("(m.nombre LIKE %s OR m.descripcion LIKE %s)")
            params.extend([like, like])
        if activo in (0, 1):
            where.append("m.activo = %s")
            params.append(int(activo))
        if sector_id:
            where.append("m.sector_id = %s")
            params.append(int(sector_id))
        where_sql = ("WHERE " + " AND ".join(where)) if where else ""

        cursor.execute(
            f"""
            SELECT
                m.*,
                COALESCE(m.tiempo_resolucion_valor, m.sla_dias, 1) AS tiempo_resolucion_valor,
                COALESCE(m.tiempo_resolucion_unidad, 'DIAS') AS tiempo_resolucion_unidad,
                COALESCE(m.requiere_foto, 0) AS requiere_foto,
                COALESCE(m.requiere_observacion, 1) AS requiere_observacion,
                sec.nombre AS sector_nombre,
                sec.responsable_empleado_id AS sector_responsable_empleado_id
            FROM feedback_motivos m
            LEFT JOIN sectores sec ON sec.id = m.sector_id
            {where_sql}
            ORDER BY m.activo DESC, m.nombre ASC
            LIMIT %s OFFSET %s
            """,
            (*params, int(per_page), offset),
        )
        rows = cursor.fetchall()

        cursor.execute(
            f"""
            SELECT COUNT(*) AS total
            FROM feedback_motivos m
            {where_sql}
            """,
            tuple(params),
        )
        total = int((cursor.fetchone() or {}).get("total") or 0)
        return rows, total
    finally:
        cursor.close()
        db.close()


def get_by_id(motivo_id: int):
    db = get_db()
    cursor = db.cursor(dictionary=True)
    try:
        cursor.execute(
            """
            SELECT
                m.*,
                COALESCE(m.tiempo_resolucion_valor, m.sla_dias, 1) AS tiempo_resolucion_valor,
                COALESCE(m.tiempo_resolucion_unidad, 'DIAS') AS tiempo_resolucion_unidad,
                COALESCE(m.requiere_foto, 0) AS requiere_foto,
                COALESCE(m.requiere_observacion, 1) AS requiere_observacion,
                sec.nombre AS sector_nombre,
                sec.responsable_empleado_id AS sector_responsable_empleado_id
            FROM feedback_motivos m
            LEFT JOIN sectores sec ON sec.id = m.sector_id
            WHERE m.id = %s
            LIMIT 1
            """,
            (motivo_id,),
        )
        return cursor.fetchone()
    finally:
        cursor.close()
        db.close()


def get_by_nombre(nombre: str, sector_id: int | None, exclude_id: int | None = None):
    db = get_db()
    cursor = db.cursor(dictionary=True)
    try:
        where = ["LOWER(nombre) = LOWER(%s)"]
        params = [str(nombre).strip()]
        if sector_id:
            where.append("sector_id = %s")
            params.append(int(sector_id))
        else:
            where.append("sector_id IS NULL")
        if exclude_id:
            where.append("id <> %s")
            params.append(int(exclude_id))
        cursor.execute(
            f"""
            SELECT *
            FROM feedback_motivos
            WHERE {" AND ".join(where)}
            LIMIT 1
            """,
            params,
        )
        return cursor.fetchone()
    finally:
        cursor.close()
        db.close()


def create(data: dict):
    db = get_db()
    cursor = db.cursor()
    try:
        cursor.execute(
            """
            INSERT INTO feedback_motivos
                (nombre, sector_id, descripcion, sla_dias, tiempo_resolucion_valor, tiempo_resolucion_unidad, requiere_foto, requiere_observacion, activo)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                data.get("nombre"),
                data.get("sector_id"),
                data.get("descripcion"),
                int(data.get("sla_dias") or data.get("tiempo_resolucion_valor") or 1),
                int(data.get("tiempo_resolucion_valor") or data.get("sla_dias") or 1),
                data.get("tiempo_resolucion_unidad") or "DIAS",
                1 if data.get("requiere_foto") else 0,
                1 if data.get("requiere_observacion", True) else 0,
                1 if data.get("activo", True) else 0,
            ),
        )
        db.commit()
        return cursor.lastrowid
    finally:
        cursor.close()
        db.close()


def update(motivo_id: int, data: dict):
    db = get_db()
    cursor = db.cursor()
    try:
        cursor.execute(
            """
            UPDATE feedback_motivos
            SET nombre = %s,
                sector_id = %s,
                descripcion = %s,
                sla_dias = %s,
                tiempo_resolucion_valor = %s,
                tiempo_resolucion_unidad = %s,
                requiere_foto = %s,
                requiere_observacion = %s,
                activo = %s
            WHERE id = %s
            """,
            (
                data.get("nombre"),
                data.get("sector_id"),
                data.get("descripcion"),
                int(data.get("sla_dias") or data.get("tiempo_resolucion_valor") or 1),
                int(data.get("tiempo_resolucion_valor") or data.get("sla_dias") or 1),
                data.get("tiempo_resolucion_unidad") or "DIAS",
                1 if data.get("requiere_foto") else 0,
                1 if data.get("requiere_observacion", True) else 0,
                1 if data.get("activo", True) else 0,
                motivo_id,
            ),
        )
        db.commit()
        return True
    finally:
        cursor.close()
        db.close()


def set_activo(motivo_id: int, activo: int):
    db = get_db()
    cursor = db.cursor()
    try:
        cursor.execute(
            """
            UPDATE feedback_motivos
            SET activo = %s
            WHERE id = %s
            """,
            (1 if activo else 0, motivo_id),
        )
        db.commit()
        return True
    finally:
        cursor.close()
        db.close()


def count_all(include_inactive: bool = False) -> int:
    db = get_db()
    cursor = db.cursor(dictionary=True)
    try:
        where = "" if include_inactive else "WHERE activo = 1"
        cursor.execute(
            f"""
            SELECT COUNT(*) AS total
            FROM feedback_motivos
            {where}
            """
        )
        return int((cursor.fetchone() or {}).get("total") or 0)
    finally:
        cursor.close()
        db.close()


def get_active_for_select():
    return get_all(include_inactive=False)
