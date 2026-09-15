from extensions import get_db


def get_all(*, include_feedback_dates=False):
    db = get_db()
    cursor = db.cursor(dictionary=True)
    try:
        cursor.execute("""
            SELECT a.*, u.usuario AS usuario_nombre
            FROM auditoria a
            LEFT JOIN usuarios u ON u.id = a.usuario_id
            WHERE (%s OR a.tabla_afectada IS NULL OR a.tabla_afectada <> 'feedback_fechas')
            ORDER BY a.fecha DESC, a.id DESC
        """, (include_feedback_dates,))
        return cursor.fetchall()
    finally:
        cursor.close()
        db.close()


def get_page(page: int, per_page: int, *, include_feedback_dates=False):
    db = get_db()
    cursor = db.cursor(dictionary=True)
    try:
        offset = (page - 1) * per_page
        cursor.execute("""
            SELECT a.*, u.usuario AS usuario_nombre
            FROM auditoria a
            LEFT JOIN usuarios u ON u.id = a.usuario_id
            WHERE (%s OR a.tabla_afectada IS NULL OR a.tabla_afectada <> 'feedback_fechas')
            ORDER BY a.fecha DESC, a.id DESC
            LIMIT %s OFFSET %s
        """, (include_feedback_dates, per_page, offset))
        rows = cursor.fetchall()

        cursor.execute("SELECT COUNT(*) AS total FROM auditoria WHERE (%s OR tabla_afectada IS NULL OR tabla_afectada <> 'feedback_fechas')", (include_feedback_dates,))
        total = cursor.fetchone()["total"]
        return rows, total
    finally:
        cursor.close()
        db.close()


def create(usuario_id: int | None, accion: str, tabla_afectada: str, registro_id: int | None):
    db = get_db()
    cursor = db.cursor()
    try:
        cursor.execute("""
            INSERT INTO auditoria (usuario_id, accion, tabla_afectada, registro_id)
            VALUES (%s,%s,%s,%s)
        """, (usuario_id, accion, tabla_afectada, registro_id))
        db.commit()
        return True
    finally:
        cursor.close()
        db.close()
