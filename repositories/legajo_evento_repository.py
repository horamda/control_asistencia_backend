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


def get_tipos_evento_page(
    page: int,
    per_page: int,
    *,
    search: str | None = None,
    activo: int | None = None,
):
    db = get_db()
    cursor = db.cursor(dictionary=True)
    try:
        offset = max(0, (int(page) - 1) * int(per_page))
        where = []
        params = []

        if search:
            where.append("(codigo LIKE %s OR nombre LIKE %s)")
            like = f"%{search}%"
            params.extend([like, like])
        if activo is not None:
            where.append("activo = %s")
            params.append(1 if int(activo) else 0)

        where_sql = ("WHERE " + " AND ".join(where)) if where else ""

        cursor.execute(
            f"""
            SELECT
                id,
                codigo,
                nombre,
                requiere_rango_fechas,
                permite_adjuntos,
                activo
            FROM legajo_tipos_evento
            {where_sql}
            ORDER BY nombre
            LIMIT %s OFFSET %s
            """,
            (*params, int(per_page), offset),
        )
        rows = cursor.fetchall()

        cursor.execute(
            f"""
            SELECT COUNT(*) AS total
            FROM legajo_tipos_evento
            {where_sql}
            """,
            tuple(params),
        )
        total = int(cursor.fetchone()["total"] or 0)
        return rows, total
    finally:
        cursor.close()
        db.close()


def get_tipo_evento_by_codigo(codigo: str):
    db = get_db()
    cursor = db.cursor(dictionary=True)
    try:
        cursor.execute(
            """
            SELECT id, codigo, nombre, requiere_rango_fechas, permite_adjuntos, activo
            FROM legajo_tipos_evento
            WHERE codigo = %s
            """,
            (codigo,),
        )
        return cursor.fetchone()
    finally:
        cursor.close()
        db.close()


def create_tipo_evento(data: dict):
    db = get_db()
    cursor = db.cursor()
    try:
        cursor.execute(
            """
            INSERT INTO legajo_tipos_evento
            (
                codigo,
                nombre,
                requiere_rango_fechas,
                permite_adjuntos,
                activo
            )
            VALUES (%s,%s,%s,%s,%s)
            """,
            (
                data.get("codigo"),
                data.get("nombre"),
                1 if data.get("requiere_rango_fechas") else 0,
                1 if data.get("permite_adjuntos") else 0,
                1 if data.get("activo") else 0,
            ),
        )
        db.commit()
        return cursor.lastrowid
    finally:
        cursor.close()
        db.close()


def update_tipo_evento(tipo_id: int, data: dict):
    db = get_db()
    cursor = db.cursor()
    try:
        cursor.execute(
            """
            UPDATE legajo_tipos_evento
            SET
                codigo = %s,
                nombre = %s,
                requiere_rango_fechas = %s,
                permite_adjuntos = %s,
                activo = %s
            WHERE id = %s
            """,
            (
                data.get("codigo"),
                data.get("nombre"),
                1 if data.get("requiere_rango_fechas") else 0,
                1 if data.get("permite_adjuntos") else 0,
                1 if data.get("activo") else 0,
                tipo_id,
            ),
        )
        db.commit()
        return cursor.rowcount > 0
    finally:
        cursor.close()
        db.close()


def set_tipo_evento_activo(tipo_id: int, activo: int):
    db = get_db()
    cursor = db.cursor()
    try:
        cursor.execute(
            """
            UPDATE legajo_tipos_evento
            SET activo = %s
            WHERE id = %s
            """,
            (1 if activo else 0, tipo_id),
        )
        db.commit()
        return cursor.rowcount > 0
    finally:
        cursor.close()
        db.close()


def count_eventos_vigentes_by_tipo(tipo_id: int):
    db = get_db()
    cursor = db.cursor(dictionary=True)
    try:
        cursor.execute(
            """
            SELECT COUNT(*) AS total
            FROM legajo_eventos
            WHERE tipo_id = %s
              AND estado = 'vigente'
            """,
            (tipo_id,),
        )
        row = cursor.fetchone() or {}
        return int(row.get("total") or 0)
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


def get_eventos_page(
    page: int,
    per_page: int,
    *,
    search: str | None = None,
    empresa_id: int | None = None,
    empleado_id: int | None = None,
    tipo_id: int | None = None,
    estado: str | None = None,
):
    db = get_db()
    cursor = db.cursor(dictionary=True)
    try:
        offset = max(0, (int(page) - 1) * int(per_page))
        where = []
        params = []

        if search:
            where.append(
                "(e.titulo LIKE %s OR e.descripcion LIKE %s OR emp.apellido LIKE %s OR emp.nombre LIKE %s OR emp.dni LIKE %s)"
            )
            like = f"%{search}%"
            params.extend([like, like, like, like, like])
        if empresa_id:
            where.append("e.empresa_id = %s")
            params.append(int(empresa_id))
        if empleado_id:
            where.append("e.empleado_id = %s")
            params.append(int(empleado_id))
        if tipo_id:
            where.append("e.tipo_id = %s")
            params.append(int(tipo_id))
        if estado in {"vigente", "anulado"}:
            where.append("e.estado = %s")
            params.append(estado)

        where_sql = ("WHERE " + " AND ".join(where)) if where else ""

        cursor.execute(
            f"""
            SELECT
                e.id,
                e.empresa_id,
                e.empleado_id,
                e.tipo_id,
                e.fecha_evento,
                e.fecha_desde,
                e.fecha_hasta,
                e.titulo,
                e.descripcion,
                e.estado,
                e.severidad,
                e.justificacion_id,
                e.created_at,
                e.updated_at,
                t.codigo AS tipo_codigo,
                t.nombre AS tipo_nombre,
                emp.apellido AS empleado_apellido,
                emp.nombre AS empleado_nombre,
                emp.legajo AS empleado_legajo,
                emp.dni AS empleado_dni,
                emp.foto AS empleado_foto,
                em.razon_social AS empresa_nombre
            FROM legajo_eventos e
            JOIN legajo_tipos_evento t ON t.id = e.tipo_id
            JOIN empleados emp ON emp.id = e.empleado_id
            JOIN empresas em ON em.id = e.empresa_id
            {where_sql}
            ORDER BY e.fecha_evento DESC, e.id DESC
            LIMIT %s OFFSET %s
            """,
            (*params, int(per_page), offset),
        )
        rows = cursor.fetchall()

        cursor.execute(
            f"""
            SELECT COUNT(*) AS total
            FROM legajo_eventos e
            JOIN legajo_tipos_evento t ON t.id = e.tipo_id
            JOIN empleados emp ON emp.id = e.empleado_id
            JOIN empresas em ON em.id = e.empresa_id
            {where_sql}
            """,
            tuple(params),
        )
        total = int(cursor.fetchone()["total"] or 0)
        return rows, total
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
