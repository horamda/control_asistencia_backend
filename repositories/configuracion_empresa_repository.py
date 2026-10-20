from extensions import get_db
import json
from services.facial_policy_service import validate_override


_COLUMN_CACHE: set[str] | None = None


def save_facial_draft(empresa_id, values, *, revision, actor_id,
                      scope="company", record_id=None):
    """Update only the draft, with optimistic locking and atomic audit."""
    draft = validate_override(values)
    if type(revision) is not int or not 0 <= revision < 4294967295:
        raise ValueError("Revision facial invalida.")
    if type(empresa_id) is not int or empresa_id <= 0:
        raise ValueError("Empresa requerida.")
    if type(actor_id) is not int or actor_id <= 0:
        raise ValueError("Administrador requerido.")
    tables = {"company": ("configuracion_empresa", "empresa_id"),
              "branch": ("sucursales", "id"), "employee": ("empleados", "id")}
    if scope not in tables:
        raise ValueError("Alcance facial invalido.")
    table, key = tables[scope]
    target_id = empresa_id if scope == "company" else record_id
    if type(target_id) is not int or target_id <= 0:
        raise ValueError("Registro facial invalido.")
    db = get_db()
    cursor = db.cursor()
    try:
        # Fresh introspection: migrations may have been applied after worker boot.
        cursor.execute(f"SHOW COLUMNS FROM {table}")
        columns = {row[0] for row in cursor.fetchall()}
        if not {"facial_policy_draft", "facial_policy_revision"} <= columns:
            raise RuntimeError("Falta preparar las columnas faciales para este alcance.")
        company_filter = "" if scope == "company" else " AND empresa_id=%s"
        params = (json.dumps(draft, sort_keys=True), target_id, revision)
        if scope != "company":
            params += (empresa_id,)
        cursor.execute(
            f"""UPDATE {table}
               SET facial_policy_draft=%s, facial_policy_revision=facial_policy_revision+1
               WHERE {key}=%s AND facial_policy_revision=%s{company_filter}""",
            params,
        )
        if cursor.rowcount != 1:
            raise ValueError("La configuracion cambio o no existe. Recargue la pagina.")
        cursor.execute(
            """INSERT INTO auditoria (usuario_id, accion, tabla_afectada, registro_id)
               VALUES (%s,%s,%s,%s)""",
            (actor_id, f"facial_draft r={revision + 1} " + json.dumps(draft, sort_keys=True, separators=(",", ":")),
             table, target_id),
        )
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        cursor.close()
        db.close()


def _get_columns(cursor) -> set[str]:
    global _COLUMN_CACHE
    if _COLUMN_CACHE is not None:
        return _COLUMN_CACHE
    cursor.execute("SHOW COLUMNS FROM configuracion_empresa")
    rows = cursor.fetchall()
    columns = set()
    for row in rows:
        if isinstance(row, dict):
            columns.add(row.get("Field"))
        else:
            columns.add(row[0])
    _COLUMN_CACHE = {column for column in columns if column}
    return _COLUMN_CACHE


def _ensure_optional_defaults(row: dict | None) -> dict | None:
    if row is None:
        return None
    row.setdefault("intervalo_minimo_fichadas_minutos", None)
    return row


def get_all():
    db = get_db()
    cursor = db.cursor(dictionary=True)
    try:
        cursor.execute("""
            SELECT c.*, e.razon_social
            FROM configuracion_empresa c
            JOIN empresas e ON e.id = c.empresa_id
            ORDER BY e.razon_social
        """)
        return [_ensure_optional_defaults(row) for row in cursor.fetchall()]
    finally:
        cursor.close()
        db.close()


def get_by_empresa_id(empresa_id: int):
    db = get_db()
    cursor = db.cursor(dictionary=True)
    try:
        cursor.execute("""
            SELECT *
            FROM configuracion_empresa
            WHERE empresa_id = %s
        """, (empresa_id,))
        return _ensure_optional_defaults(cursor.fetchone())
    finally:
        cursor.close()
        db.close()


# Columnas agregadas por migraciones posteriores: se guardan solo si existen.
OPTIONAL_COLUMNS = {
    "intervalo_minimo_fichadas_minutos": "20260310_01_configuracion_empresa_intervalo_fichadas.sql",
    "egreso_automatico_activo": "scripts/migrate_20261015_03_egreso_automatico.py",
    "egreso_automatico_horas": "scripts/migrate_20261015_03_egreso_automatico.py",
}


def upsert(data: dict):
    db = get_db()
    cursor = db.cursor()
    try:
        columns = _get_columns(cursor)
        optional = []
        for column, migration in OPTIONAL_COLUMNS.items():
            if column not in data:
                continue
            if column not in columns:
                raise RuntimeError(
                    f"Falta la columna configuracion_empresa.{column}. Ejecute la migracion {migration}."
                )
            optional.append(column)
        params = [
            data.get("empresa_id"),
            1 if data.get("requiere_qr") else 0,
            1 if data.get("requiere_foto") else 0,
            1 if data.get("requiere_geo") else 0,
            data.get("tolerancia_global"),
            data.get("cooldown_scan_segundos"),
            *[data.get(column) for column in optional],
        ]
        optional_insert_column = "".join(f", {c}" for c in optional)
        optional_insert_placeholder = ", %s" * len(optional)
        optional_update_column = "".join(f", {c} = VALUES({c})" for c in optional)

        cursor.execute("""
            INSERT INTO configuracion_empresa
            (
                empresa_id,
                requiere_qr,
                requiere_foto,
                requiere_geo,
                tolerancia_global,
                cooldown_scan_segundos{optional_insert_column}
            )
            VALUES (%s,%s,%s,%s,%s,%s{optional_insert_placeholder})
            ON DUPLICATE KEY UPDATE
                requiere_qr = VALUES(requiere_qr),
                requiere_foto = VALUES(requiere_foto),
                requiere_geo = VALUES(requiere_geo),
                tolerancia_global = VALUES(tolerancia_global),
                cooldown_scan_segundos = VALUES(cooldown_scan_segundos){optional_update_column}
        """.format(
            optional_insert_column=optional_insert_column,
            optional_insert_placeholder=optional_insert_placeholder,
            optional_update_column=optional_update_column,
        ), params)
        db.commit()
        return True
    finally:
        cursor.close()
        db.close()
