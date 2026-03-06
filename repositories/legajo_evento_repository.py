from extensions import get_db


def get_tipos_evento(include_inactive: bool = False):
    db = get_db()
    cursor = db.cursor(dictionary=True)
    try:
        where_sql = "" if include_inactive else "WHERE activo = 1"
        cursor.execute(
            f"""
            SELECT id, codigo, nombre, requiere_rango_fechas, permite_adjuntos, activo
            FROM legajo_tipos_evento
            {where_sql}
            ORDER BY nombre
            """
        )
        return cursor.fetchall()
    finally:
        cursor.close()
        db.close()


def get_tipo_evento_by_id(tipo_id: int):
    db = get_db()
    cursor = db.cursor(dictionary=True)
    try:
        cursor.execute(
            """
            SELECT id, codigo, nombre, requiere_rango_fechas, permite_adjuntos, activo
            FROM legajo_tipos_evento
            WHERE id = %s
            """,
            (tipo_id,),
        )
        return cursor.fetchone()
    finally:
        cursor.close()
        db.close()


def get_evento_by_id(evento_id: int):
    db = get_db()
    cursor = db.cursor(dictionary=True)
    try:
        cursor.execute(
            """
            SELECT
                e.*,
                t.codigo AS tipo_codigo,
                t.nombre AS tipo_nombre
            FROM legajo_eventos e
            JOIN legajo_tipos_evento t ON t.id = e.tipo_id
            WHERE e.id = %s
            """,
            (evento_id,),
        )
        return cursor.fetchone()
    finally:
        cursor.close()
        db.close()


def get_eventos_by_empleado(empleado_id: int, include_anulados: bool = True):
    db = get_db()
    cursor = db.cursor(dictionary=True)
    try:
        where = ["e.empleado_id = %s"]
        params = [empleado_id]
        if not include_anulados:
            where.append("e.estado = 'vigente'")
        where_sql = " AND ".join(where)
        cursor.execute(
            f"""
            SELECT
                e.*,
                t.codigo AS tipo_codigo,
                t.nombre AS tipo_nombre,
                uc.usuario AS created_by_usuario,
                uu.usuario AS updated_by_usuario,
                ua.usuario AS anulado_by_usuario
            FROM legajo_eventos e
            JOIN legajo_tipos_evento t ON t.id = e.tipo_id
            LEFT JOIN usuarios uc ON uc.id = e.created_by_usuario_id
            LEFT JOIN usuarios uu ON uu.id = e.updated_by_usuario_id
            LEFT JOIN usuarios ua ON ua.id = e.anulado_by_usuario_id
            WHERE {where_sql}
            ORDER BY e.fecha_evento DESC, e.id DESC
            """,
            tuple(params),
        )
        return cursor.fetchall()
    finally:
        cursor.close()
        db.close()


def create_evento(data: dict):
    db = get_db()
    cursor = db.cursor()
    try:
        cursor.execute(
            """
            INSERT INTO legajo_eventos
            (
                empresa_id,
                empleado_id,
                tipo_id,
                fecha_evento,
                fecha_desde,
                fecha_hasta,
                titulo,
                descripcion,
                estado,
                severidad,
                justificacion_id,
                created_by_usuario_id,
                updated_by_usuario_id
            )
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            """,
            (
                data.get("empresa_id"),
                data.get("empleado_id"),
                data.get("tipo_id"),
                data.get("fecha_evento"),
                data.get("fecha_desde"),
                data.get("fecha_hasta"),
                data.get("titulo"),
                data.get("descripcion"),
                data.get("estado") or "vigente",
                data.get("severidad"),
                data.get("justificacion_id"),
                data.get("created_by_usuario_id"),
                data.get("updated_by_usuario_id"),
            ),
        )
        db.commit()
        return cursor.lastrowid
    finally:
        cursor.close()
        db.close()


def update_evento(evento_id: int, data: dict):
    db = get_db()
    cursor = db.cursor()
    try:
        cursor.execute(
            """
            UPDATE legajo_eventos
            SET
                tipo_id = %s,
                fecha_evento = %s,
                fecha_desde = %s,
                fecha_hasta = %s,
                titulo = %s,
                descripcion = %s,
                severidad = %s,
                justificacion_id = %s,
                updated_by_usuario_id = %s
            WHERE id = %s
            """,
            (
                data.get("tipo_id"),
                data.get("fecha_evento"),
                data.get("fecha_desde"),
                data.get("fecha_hasta"),
                data.get("titulo"),
                data.get("descripcion"),
                data.get("severidad"),
                data.get("justificacion_id"),
                data.get("updated_by_usuario_id"),
                evento_id,
            ),
        )
        db.commit()
        return cursor.rowcount > 0
    finally:
        cursor.close()
        db.close()


def anular_evento(evento_id: int, anulado_by_usuario_id: int | None, motivo: str | None):
    db = get_db()
    cursor = db.cursor()
    try:
        cursor.execute(
            """
            UPDATE legajo_eventos
            SET
                estado = 'anulado',
                anulado_by_usuario_id = %s,
                anulado_motivo = %s,
                anulado_at = NOW(),
                updated_by_usuario_id = %s
            WHERE id = %s
            """,
            (anulado_by_usuario_id, motivo, anulado_by_usuario_id, evento_id),
        )
        db.commit()
        return cursor.rowcount > 0
    finally:
        cursor.close()
        db.close()
