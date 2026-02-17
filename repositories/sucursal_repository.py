from extensions import get_db


def get_all(include_inactive: bool = False):
    db = get_db()
    cursor = db.cursor(dictionary=True)
    try:
        if include_inactive:
            cursor.execute("""
                SELECT s.*, e.razon_social AS empresa_nombre
                FROM sucursales s
                JOIN empresas e ON e.id = s.empresa_id
                ORDER BY e.razon_social, s.nombre
            """)
        else:
            cursor.execute("""
                SELECT s.*, e.razon_social AS empresa_nombre
                FROM sucursales s
                JOIN empresas e ON e.id = s.empresa_id
                WHERE s.activa = 1
                ORDER BY e.razon_social, s.nombre
            """)
        rows = cursor.fetchall()
        return rows
    finally:
        cursor.close()
        db.close()


def get_by_id(sucursal_id: int):
    db = get_db()
    cursor = db.cursor(dictionary=True)
    try:
        cursor.execute("""
            SELECT *
            FROM sucursales
            WHERE id = %s
        """, (sucursal_id,))
        suc = cursor.fetchone()
        return suc
    finally:
        cursor.close()
        db.close()


def create(data: dict):
    db = get_db()
    cursor = db.cursor()
    try:
        cursor.execute("""
            INSERT INTO sucursales
            (
                empresa_id,
                nombre,
                direccion,
                latitud,
                longitud,
                radio_permitido_m,
                activa
            )
            VALUES (%s,%s,%s,%s,%s,%s,%s)
        """, (
            data.get("empresa_id"),
            data.get("nombre"),
            data.get("direccion"),
            data.get("latitud"),
            data.get("longitud"),
            data.get("radio_permitido_m"),
            1 if data.get("activa") else 0
        ))
        db.commit()
        return cursor.lastrowid
    finally:
        cursor.close()
        db.close()


def update(sucursal_id: int, data: dict):
    db = get_db()
    cursor = db.cursor()
    try:
        cursor.execute("""
            UPDATE sucursales
            SET
                empresa_id = %s,
                nombre = %s,
                direccion = %s,
                latitud = %s,
                longitud = %s,
                radio_permitido_m = %s,
                activa = %s
            WHERE id = %s
        """, (
            data.get("empresa_id"),
            data.get("nombre"),
            data.get("direccion"),
            data.get("latitud"),
            data.get("longitud"),
            data.get("radio_permitido_m"),
            1 if data.get("activa") else 0,
            sucursal_id
        ))
        db.commit()
        return True
    finally:
        cursor.close()
        db.close()


def set_activa(sucursal_id: int, activa: int):
    db = get_db()
    cursor = db.cursor()
    try:
        cursor.execute("""
            UPDATE sucursales
            SET activa = %s
            WHERE id = %s
        """, (1 if activa else 0, sucursal_id))
        db.commit()
        return True
    finally:
        cursor.close()
        db.close()
