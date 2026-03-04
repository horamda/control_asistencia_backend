from extensions import get_db


# =========================================================
# GETTERS
# =========================================================

def get_all(include_inactive: bool = False):
    """
    Devuelve todos los empleados.
    include_inactive=False -> solo activos
    include_inactive=True  -> todos
    """
    db = get_db()
    cursor = db.cursor(dictionary=True)
    try:
        if include_inactive:
            cursor.execute("""
                SELECT e.*, emp.razon_social AS empresa_nombre, s.nombre AS sucursal_nombre,
                       sec.nombre AS sector_nombre, p.nombre AS puesto_nombre, l.localidad AS localidad_nombre
                FROM empleados e
                JOIN empresas emp ON emp.id = e.empresa_id
                LEFT JOIN sucursales s ON s.id = e.sucursal_id
                LEFT JOIN sectores sec ON sec.id = e.sector_id
                LEFT JOIN puestos p ON p.id = e.puesto_id
                LEFT JOIN localidades l ON l.codigo_postal = e.codigo_postal
                ORDER BY e.apellido, e.nombre
            """)
        else:
            cursor.execute("""
                SELECT e.*, emp.razon_social AS empresa_nombre, s.nombre AS sucursal_nombre,
                       sec.nombre AS sector_nombre, p.nombre AS puesto_nombre, l.localidad AS localidad_nombre
                FROM empleados e
                JOIN empresas emp ON emp.id = e.empresa_id
                LEFT JOIN sucursales s ON s.id = e.sucursal_id
                LEFT JOIN sectores sec ON sec.id = e.sector_id
                LEFT JOIN puestos p ON p.id = e.puesto_id
                LEFT JOIN localidades l ON l.codigo_postal = e.codigo_postal
                WHERE e.activo = 1
                ORDER BY e.apellido, e.nombre
            """)

        rows = cursor.fetchall()
        return rows
    finally:
        cursor.close()
        db.close()


def get_page(
    page: int,
    per_page: int,
    include_inactive: bool = True,
    search: str | None = None,
    empresa_id: int | None = None,
    activo: int | None = None,
):
    db = get_db()
    cursor = db.cursor(dictionary=True)
    try:
        offset = (page - 1) * per_page
        where = []
        params = []
        if not include_inactive:
            where.append("e.activo = 1")
        if search:
            where.append("(e.apellido LIKE %s OR e.nombre LIKE %s)")
            like = f"%{search}%"
            params.extend([like, like])
        if empresa_id:
            where.append("e.empresa_id = %s")
            params.append(empresa_id)
        if activo in (0, 1):
            where.append("e.activo = %s")
            params.append(activo)
        where_sql = ("WHERE " + " AND ".join(where)) if where else ""
        cursor.execute(f"""
            SELECT e.*, emp.razon_social AS empresa_nombre, s.nombre AS sucursal_nombre,
                   sec.nombre AS sector_nombre, p.nombre AS puesto_nombre, l.localidad AS localidad_nombre
            FROM empleados e
            JOIN empresas emp ON emp.id = e.empresa_id
            LEFT JOIN sucursales s ON s.id = e.sucursal_id
            LEFT JOIN sectores sec ON sec.id = e.sector_id
            LEFT JOIN puestos p ON p.id = e.puesto_id
            LEFT JOIN localidades l ON l.codigo_postal = e.codigo_postal
            {where_sql}
            ORDER BY e.apellido, e.nombre
            LIMIT %s OFFSET %s
        """, (*params, per_page, offset))
        rows = cursor.fetchall()

        cursor.execute(f"SELECT COUNT(*) AS total FROM empleados e {where_sql}", params)
        total = cursor.fetchone()["total"]
        return rows, total
    finally:
        cursor.close()
        db.close()


def get_page_for_roles(page: int, per_page: int, empresa_id: int | None = None, search: str | None = None):
    db = get_db()
    cursor = db.cursor(dictionary=True)
    try:
        offset = (page - 1) * per_page
        where = []
        params = []
        if empresa_id:
            where.append("e.empresa_id = %s")
            params.append(empresa_id)
        if search:
            where.append("(e.apellido LIKE %s OR e.nombre LIKE %s)")
            like = f"%{search}%"
            params.extend([like, like])
        where_sql = ("WHERE " + " AND ".join(where)) if where else ""
        cursor.execute(f"""
            SELECT e.*, emp.razon_social AS empresa_nombre, s.nombre AS sucursal_nombre,
                   sec.nombre AS sector_nombre, p.nombre AS puesto_nombre, l.localidad AS localidad_nombre
            FROM empleados e
            JOIN empresas emp ON emp.id = e.empresa_id
            LEFT JOIN sucursales s ON s.id = e.sucursal_id
            LEFT JOIN sectores sec ON sec.id = e.sector_id
            LEFT JOIN puestos p ON p.id = e.puesto_id
            LEFT JOIN localidades l ON l.codigo_postal = e.codigo_postal
            {where_sql}
            ORDER BY e.apellido, e.nombre
            LIMIT %s OFFSET %s
        """, (*params, per_page, offset))
        rows = cursor.fetchall()

        cursor.execute(f"SELECT COUNT(*) AS total FROM empleados e {where_sql}", params)
        total = cursor.fetchone()["total"]
        return rows, total
    finally:
        cursor.close()
        db.close()


def get_by_id(empleado_id: int):
    db = get_db()
    cursor = db.cursor(dictionary=True)
    try:
        cursor.execute("""
            SELECT *
            FROM empleados
            WHERE id = %s
        """, (empleado_id,))

        emp = cursor.fetchone()
        return emp
    finally:
        cursor.close()
        db.close()


def get_by_dni(dni: str):
    db = get_db()
    cursor = db.cursor(dictionary=True)
    try:
        cursor.execute("""
            SELECT *
            FROM empleados
            WHERE dni = %s
              AND activo = 1
        """, (dni,))

        emp = cursor.fetchone()
        return emp
    finally:
        cursor.close()
        db.close()


def get_by_email(email: str):
    """
    Login principal por email
    """
    db = get_db()
    cursor = db.cursor(dictionary=True)
    try:
        cursor.execute("""
            SELECT *
            FROM empleados
            WHERE email = %s
              AND activo = 1
        """, (email,))

        emp = cursor.fetchone()
        return emp
    finally:
        cursor.close()
        db.close()


def exists_unique(field: str, value: str, exclude_id: int | None = None):
    if field not in {"dni", "email", "legajo"}:
        raise ValueError("Campo no permitido")
    db = get_db()
    cursor = db.cursor()
    try:
        if exclude_id:
            cursor.execute(f"""
                SELECT 1
                FROM empleados
                WHERE {field} = %s
                  AND id <> %s
                LIMIT 1
            """, (value, exclude_id))
        else:
            cursor.execute(f"""
                SELECT 1
                FROM empleados
                WHERE {field} = %s
                LIMIT 1
            """, (value,))
        return cursor.fetchone() is not None
    finally:
        cursor.close()
        db.close()


# Alias para no romper imports existentes
get_by_username = get_by_email


# =========================================================
# CREATE
# =========================================================

def create(data: dict):
    """
    data esperado:
    nombre, apellido, dni, email, password_hash,
    sector, puesto, empresa_id, sucursal_id
    """
    db = get_db()
    cursor = db.cursor()
    try:
        cursor.execute("""
            INSERT INTO empleados
            (
                empresa_id,
                sucursal_id,
                legajo,
                dni,
                nombre,
                apellido,
                fecha_nacimiento,
                sexo,
                email,
                telefono,
                direccion,
                fecha_ingreso,
                estado,
                foto,
                password_hash,
                activo,
                sector_id,
                puesto_id,
                codigo_postal
            )
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,1,%s,%s,%s)
        """, (
            data.get("empresa_id"),
            data.get("sucursal_id"),
            data.get("legajo"),
            data.get("dni"),
            data.get("nombre"),
            data.get("apellido"),
            data.get("fecha_nacimiento") or None,
            data.get("sexo"),
            data.get("email"),
            data.get("telefono"),
            data.get("direccion"),
            data.get("fecha_ingreso") or None,
            data.get("estado", "activo"),
            data.get("foto"),
            data.get("password_hash"),
            data.get("sector_id"),
            data.get("puesto_id"),
            data.get("codigo_postal")
        ))

        db.commit()
        emp_id = cursor.lastrowid
        return emp_id
    finally:
        cursor.close()
        db.close()


# =========================================================
# UPDATE
# =========================================================

def update(empleado_id: int, data: dict):
    db = get_db()
    cursor = db.cursor()
    try:
        cursor.execute("""
            UPDATE empleados
            SET
                empresa_id = %s,
                sucursal_id = %s,
                legajo = %s,
                nombre = %s,
                apellido = %s,
                dni = %s,
                fecha_nacimiento = %s,
                sexo = %s,
                email = %s,
                telefono = %s,
                direccion = %s,
                fecha_ingreso = %s,
                estado = %s,
                foto = %s,
                sector_id = %s,
                puesto_id = %s,
                codigo_postal = %s
            WHERE id = %s
        """, (
            data.get("empresa_id"),
            data.get("sucursal_id"),
            data.get("legajo"),
            data.get("nombre"),
            data.get("apellido"),
            data.get("dni"),
            data.get("fecha_nacimiento") or None,
            data.get("sexo"),
            data.get("email"),
            data.get("telefono"),
            data.get("direccion"),
            data.get("fecha_ingreso") or None,
            data.get("estado", "activo"),
            data.get("foto"),
            data.get("sector_id"),
            data.get("puesto_id"),
            data.get("codigo_postal"),
            empleado_id
        ))

        db.commit()
        return True
    finally:
        cursor.close()
        db.close()


# =========================================================
# ACTIVO / INACTIVO
# =========================================================

def set_activo(empleado_id: int, activo: int):
    db = get_db()
    cursor = db.cursor()
    try:
        cursor.execute("""
            UPDATE empleados
            SET activo = %s
            WHERE id = %s
        """, (1 if activo else 0, empleado_id))

        db.commit()
        return True
    finally:
        cursor.close()
        db.close()


def delete(empleado_id: int):
    """
    Baja lógica
    """
    return set_activo(empleado_id, 0)


def update_password(empleado_id: int, password_hash: str):
    db = get_db()
    cursor = db.cursor()
    try:
        cursor.execute("""
            UPDATE empleados
            SET password_hash = %s
            WHERE id = %s
        """, (password_hash, empleado_id))
        db.commit()
        return True
    finally:
        cursor.close()
        db.close()


def update_mobile_profile(empleado_id: int, telefono: str | None, direccion: str | None, foto: str | None):
    db = get_db()
    cursor = db.cursor()
    try:
        cursor.execute(
            """
            UPDATE empleados
            SET telefono = %s,
                direccion = %s,
                foto = %s
            WHERE id = %s
            """,
            (telefono, direccion, foto, empleado_id),
        )
        db.commit()
        return True
    finally:
        cursor.close()
        db.close()
