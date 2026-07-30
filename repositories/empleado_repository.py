from extensions import get_db


def _append_search_filter(where: list[str], params: list, search: str | None) -> None:
    if not search:
        return

    terms = [term.strip() for term in str(search).split() if term.strip()]
    if not terms:
        return

    term_conditions = []
    for term in terms:
        like = f"%{term}%"
        term_conditions.append(
            "("
            "e.apellido LIKE %s OR "
            "e.nombre LIKE %s OR "
            "e.dni LIKE %s OR "
            "e.legajo LIKE %s OR "
            "CONCAT_WS(' ', e.apellido, e.nombre) LIKE %s OR "
            "CONCAT_WS(' ', e.nombre, e.apellido) LIKE %s"
            ")"
        )
        params.extend([like, like, like, like, like, like])

    where.append("(" + " AND ".join(term_conditions) + ")")


# =========================================================
# GETTERS
# =========================================================

def get_all(
    include_inactive: bool = False,
    sucursal_id: int | None = None,
    sector_id: int | None = None,
    requiere_control_asistencia: int | None = None,
):
    """
    Devuelve todos los empleados.
    include_inactive=False -> solo activos
    include_inactive=True  -> todos
    sucursal_id / sector_id -> filtran por sucursal o sector (None = todas/todos)
    """
    db = get_db()
    cursor = db.cursor(dictionary=True)
    try:
        where = []
        params = []
        if not include_inactive:
            where.append("e.activo = 1")
        if sucursal_id:
            where.append("e.sucursal_id = %s")
            params.append(sucursal_id)
        if sector_id:
            where.append("e.sector_id = %s")
            params.append(sector_id)
        if requiere_control_asistencia in (0, 1):
            where.append("COALESCE(e.requiere_control_asistencia, 1) = %s")
            params.append(int(requiere_control_asistencia))
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
        """, params)

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
    sucursal_id: int | None = None,
    sector_id: int | None = None,
    requiere_control_asistencia: int | None = None,
    legajo_eventos: str | None = None,
):
    db = get_db()
    cursor = db.cursor(dictionary=True)
    try:
        offset = (page - 1) * per_page
        where = []
        params = []
        if not include_inactive:
            where.append("e.activo = 1")
        _append_search_filter(where, params, search)
        if empresa_id:
            where.append("e.empresa_id = %s")
            params.append(empresa_id)
        if activo in (0, 1):
            where.append("e.activo = %s")
            params.append(activo)
        if sucursal_id:
            where.append("e.sucursal_id = %s")
            params.append(sucursal_id)
        if sector_id:
            where.append("e.sector_id = %s")
            params.append(sector_id)
        if requiere_control_asistencia in (0, 1):
            where.append("COALESCE(e.requiere_control_asistencia, 1) = %s")
            params.append(int(requiere_control_asistencia))
        if legajo_eventos == "con_eventos":
            where.append("COALESCE(legajo_stats.eventos_total, 0) > 0")
        elif legajo_eventos == "sin_eventos":
            where.append("COALESCE(legajo_stats.eventos_total, 0) = 0")
        elif legajo_eventos == "vigentes":
            where.append("COALESCE(legajo_stats.eventos_vigentes, 0) > 0")
        where_sql = ("WHERE " + " AND ".join(where)) if where else ""
        cursor.execute(f"""
            SELECT e.*, emp.razon_social AS empresa_nombre, s.nombre AS sucursal_nombre,
                   sec.nombre AS sector_nombre, p.nombre AS puesto_nombre, l.localidad AS localidad_nombre,
                   extras.puestos_adicionales_nombres,
                   COALESCE(legajo_stats.eventos_total, 0) AS legajo_eventos_total,
                   COALESCE(legajo_stats.eventos_vigentes, 0) AS legajo_eventos_vigentes,
                   legajo_stats.ultima_fecha_evento AS legajo_ultima_fecha_evento
            FROM empleados e
            JOIN empresas emp ON emp.id = e.empresa_id
            LEFT JOIN sucursales s ON s.id = e.sucursal_id
            LEFT JOIN sectores sec ON sec.id = e.sector_id
            LEFT JOIN puestos p ON p.id = e.puesto_id
            LEFT JOIN localidades l ON l.codigo_postal = e.codigo_postal
            LEFT JOIN (
                SELECT ep.empleado_id,
                       GROUP_CONCAT(DISTINCT pa.nombre ORDER BY pa.nombre SEPARATOR ', ') AS puestos_adicionales_nombres
                FROM empleado_puestos ep
                JOIN puestos pa ON pa.id = ep.puesto_id
                WHERE ep.activo = 1
                GROUP BY ep.empleado_id
            ) extras ON extras.empleado_id = e.id
            LEFT JOIN (
                SELECT
                    empleado_id,
                    COUNT(*) AS eventos_total,
                    SUM(CASE WHEN estado = 'vigente' THEN 1 ELSE 0 END) AS eventos_vigentes,
                    MAX(fecha_evento) AS ultima_fecha_evento
                FROM legajo_eventos
                GROUP BY empleado_id
            ) legajo_stats ON legajo_stats.empleado_id = e.id
            {where_sql}
            ORDER BY e.apellido, e.nombre
            LIMIT %s OFFSET %s
        """, (*params, per_page, offset))
        rows = cursor.fetchall()

        cursor.execute(f"""
            SELECT COUNT(*) AS total
            FROM empleados e
            LEFT JOIN (
                SELECT
                    empleado_id,
                    COUNT(*) AS eventos_total,
                    SUM(CASE WHEN estado = 'vigente' THEN 1 ELSE 0 END) AS eventos_vigentes
                FROM legajo_eventos
                GROUP BY empleado_id
            ) legajo_stats ON legajo_stats.empleado_id = e.id
            {where_sql}
        """, params)
        total = cursor.fetchone()["total"]
        return rows, total
    finally:
        cursor.close()
        db.close()


def get_page_for_roles(
    page: int,
    per_page: int,
    empresa_id: int | None = None,
    search: str | None = None,
    sucursal_id: int | None = None,
    sector_id: int | None = None,
):
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
        if sucursal_id:
            where.append("e.sucursal_id = %s")
            params.append(sucursal_id)
        if sector_id:
            where.append("e.sector_id = %s")
            params.append(sector_id)
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


def get_by_legajo(legajo: str, empresa_id: int | None = None):
    db = get_db()
    cursor = db.cursor(dictionary=True)
    try:
        if empresa_id:
            cursor.execute(
                "SELECT * FROM empleados WHERE legajo = %s AND empresa_id = %s LIMIT 1",
                (str(legajo).strip(), int(empresa_id)),
            )
        else:
            cursor.execute(
                "SELECT * FROM empleados WHERE legajo = %s LIMIT 1",
                (str(legajo).strip(),),
            )
        return cursor.fetchone()
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
                cuil,
                nombre,
                apellido,
                fecha_nacimiento,
                sexo,
                email,
                telefono,
                direccion,
                fecha_ingreso,
                tipo_contrato,
                modalidad,
                fecha_baja,
                categoria,
                obra_social,
                cod_chess_erp,
                banco,
                cbu,
                numero_emergencia,
                estado,
                foto,
                password_hash,
                activo,
                requiere_control_asistencia,
                sector_id,
                puesto_id,
                codigo_postal,
                reporta_a_empleado_id
            )
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,1,%s,%s,%s,%s,%s)
        """, (
            data.get("empresa_id"),
            data.get("sucursal_id"),
            data.get("legajo"),
            data.get("dni"),
            data.get("cuil") or None,
            data.get("nombre"),
            data.get("apellido"),
            data.get("fecha_nacimiento") or None,
            data.get("sexo"),
            data.get("email"),
            data.get("telefono"),
            data.get("direccion"),
            data.get("fecha_ingreso") or None,
            data.get("tipo_contrato") or None,
            data.get("modalidad") or "presencial",
            data.get("fecha_baja") or None,
            data.get("categoria") or None,
            data.get("obra_social") or None,
            data.get("cod_chess_erp") or None,
            data.get("banco") or None,
            data.get("cbu") or None,
            data.get("numero_emergencia") or None,
            data.get("estado", "activo"),
            data.get("foto"),
            data.get("password_hash"),
            1 if data.get("requiere_control_asistencia", 1) in (1, True, "1", "true", "on") else 0,
            data.get("sector_id"),
            data.get("puesto_id"),
            data.get("codigo_postal"),
            data.get("reporta_a_empleado_id") or None,
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
        estado = data.get("estado", "activo") or "activo"
        activo = 1 if estado == "activo" else 0
        cursor.execute("""
            UPDATE empleados
            SET
                empresa_id = %s,
                sucursal_id = %s,
                legajo = %s,
                nombre = %s,
                apellido = %s,
                dni = %s,
                cuil = %s,
                fecha_nacimiento = %s,
                sexo = %s,
                email = %s,
                telefono = %s,
                direccion = %s,
                fecha_ingreso = %s,
                tipo_contrato = %s,
                modalidad = %s,
                fecha_baja = %s,
                categoria = %s,
                obra_social = %s,
                cod_chess_erp = %s,
                banco = %s,
                cbu = %s,
                numero_emergencia = %s,
                estado = %s,
                activo = %s,
                requiere_control_asistencia = %s,
                foto = %s,
                sector_id = %s,
                puesto_id = %s,
                codigo_postal = %s,
                reporta_a_empleado_id = %s
            WHERE id = %s
        """, (
            data.get("empresa_id"),
            data.get("sucursal_id"),
            data.get("legajo"),
            data.get("nombre"),
            data.get("apellido"),
            data.get("dni"),
            data.get("cuil") or None,
            data.get("fecha_nacimiento") or None,
            data.get("sexo"),
            data.get("email"),
            data.get("telefono"),
            data.get("direccion"),
            data.get("fecha_ingreso") or None,
            data.get("tipo_contrato") or None,
            data.get("modalidad") or "presencial",
            data.get("fecha_baja") or None,
            data.get("categoria") or None,
            data.get("obra_social") or None,
            data.get("cod_chess_erp") or None,
            data.get("banco") or None,
            data.get("cbu") or None,
            data.get("numero_emergencia") or None,
            estado,
            activo,
            1 if data.get("requiere_control_asistencia", 1) in (1, True, "1", "true", "on") else 0,
            data.get("foto"),
            data.get("sector_id"),
            data.get("puesto_id"),
            data.get("codigo_postal"),
            data.get("reporta_a_empleado_id") or None,
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
