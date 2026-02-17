from extensions import get_db


def get_all(
    empleado_id: int | None = None,
    fecha_desde: str | None = None,
    fecha_hasta: str | None = None,
    tipo: str | None = None,
    anula_horario: int | None = None,
    order_by: str | None = None
):
    db = get_db()
    cursor = db.cursor(dictionary=True)
    try:
        where = []
        params = []
        if empleado_id:
            where.append("ex.empleado_id = %s")
            params.append(empleado_id)
        if fecha_desde:
            where.append("ex.fecha >= %s")
            params.append(fecha_desde)
        if fecha_hasta:
            where.append("ex.fecha <= %s")
            params.append(fecha_hasta)
        if tipo:
            where.append("ex.tipo = %s")
            params.append(tipo)
        if anula_horario is not None:
            where.append("ex.anula_horario = %s")
            params.append(anula_horario)
        where_sql = ("WHERE " + " AND ".join(where)) if where else ""
        order_sql = "ORDER BY ex.fecha DESC, e.apellido, e.nombre"
        if order_by == "fecha_asc":
            order_sql = "ORDER BY ex.fecha ASC, e.apellido, e.nombre"
        elif order_by == "empleado_asc":
            order_sql = "ORDER BY e.apellido ASC, e.nombre ASC, ex.fecha DESC"
        elif order_by == "empleado_desc":
            order_sql = "ORDER BY e.apellido DESC, e.nombre DESC, ex.fecha DESC"
        cursor.execute(f"""
            SELECT ex.*, e.apellido, e.nombre, emp.razon_social AS empresa_nombre
            FROM empleado_excepciones ex
            JOIN empleados e ON e.id = ex.empleado_id
            JOIN empresas emp ON emp.id = ex.empresa_id
            {where_sql}
            {order_sql}
        """, params)
        return cursor.fetchall()
    finally:
        cursor.close()
        db.close()


def get_by_id(excepcion_id: int):
    db = get_db()
    cursor = db.cursor(dictionary=True)
    try:
        cursor.execute("""
            SELECT ex.*, e.apellido, e.nombre, e.empresa_id, emp.razon_social AS empresa_nombre
            FROM empleado_excepciones ex
            JOIN empleados e ON e.id = ex.empleado_id
            JOIN empresas emp ON emp.id = ex.empresa_id
            WHERE ex.id = %s
        """, (excepcion_id,))
        return cursor.fetchone()
    finally:
        cursor.close()
        db.close()


def get_by_empleado_fecha(empleado_id: int, fecha: str):
    db = get_db()
    cursor = db.cursor(dictionary=True)
    try:
        cursor.execute("""
            SELECT *
            FROM empleado_excepciones
            WHERE empleado_id = %s
              AND fecha = %s
            LIMIT 1
        """, (empleado_id, fecha))
        return cursor.fetchone()
    finally:
        cursor.close()
        db.close()


def create(data: dict):
    db = get_db()
    cursor = db.cursor()
    try:
        cursor.execute("""
            INSERT INTO empleado_excepciones
            (
                empresa_id,
                empleado_id,
                fecha,
                tipo,
                descripcion,
                anula_horario
            )
            VALUES (%s,%s,%s,%s,%s,%s)
        """, (
            data.get("empresa_id"),
            data.get("empleado_id"),
            data.get("fecha"),
            data.get("tipo"),
            data.get("descripcion"),
            1 if data.get("anula_horario") else 0
        ))
        db.commit()
        return cursor.lastrowid
    finally:
        cursor.close()
        db.close()


def update(excepcion_id: int, data: dict):
    db = get_db()
    cursor = db.cursor()
    try:
        cursor.execute("""
            UPDATE empleado_excepciones
            SET
                empresa_id = %s,
                empleado_id = %s,
                fecha = %s,
                tipo = %s,
                descripcion = %s,
                anula_horario = %s
            WHERE id = %s
        """, (
            data.get("empresa_id"),
            data.get("empleado_id"),
            data.get("fecha"),
            data.get("tipo"),
            data.get("descripcion"),
            1 if data.get("anula_horario") else 0,
            excepcion_id
        ))
        db.commit()
        return True
    finally:
        cursor.close()
        db.close()


def delete(excepcion_id: int):
    db = get_db()
    cursor = db.cursor()
    try:
        cursor.execute("""
            DELETE FROM empleado_excepciones
            WHERE id = %s
        """, (excepcion_id,))
        db.commit()
        return True
    finally:
        cursor.close()
        db.close()
