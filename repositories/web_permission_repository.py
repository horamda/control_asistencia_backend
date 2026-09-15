from extensions import get_db
from services.web_permissions_service import PERMISSION_ACTIONS, role_default_module_codes


def get_user_permissions(user_id: int) -> dict[str, dict[str, bool]]:
    db = get_db()
    cursor = db.cursor(dictionary=True)
    try:
        cursor.execute(
            """
            SELECT modulo,
                   puede_ver,
                   puede_crear,
                   puede_editar,
                   puede_eliminar,
                   puede_aprobar,
                   puede_exportar
            FROM usuario_modulo_permisos
            WHERE usuario_id = %s
            """,
            (int(user_id),),
        )
        rows = cursor.fetchall()
        return {
            row["modulo"]: {
                "ver": bool(row.get("puede_ver")),
                "crear": bool(row.get("puede_crear")),
                "editar": bool(row.get("puede_editar")),
                "eliminar": bool(row.get("puede_eliminar")),
                "aprobar": bool(row.get("puede_aprobar")),
                "exportar": bool(row.get("puede_exportar")),
            }
            for row in rows
        }
    finally:
        cursor.close()
        db.close()


def set_user_permissions(user_id: int, permissions: dict[str, dict[str, bool]]) -> bool:
    db = get_db()
    cursor = db.cursor()
    try:
        cursor.execute("DELETE FROM usuario_modulo_permisos WHERE usuario_id = %s", (int(user_id),))
        for modulo, actions in sorted((permissions or {}).items()):
            cursor.execute(
                """
                INSERT INTO usuario_modulo_permisos (
                    usuario_id,
                    modulo,
                    puede_ver,
                    puede_crear,
                    puede_editar,
                    puede_eliminar,
                    puede_aprobar,
                    puede_exportar
                )
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
                """,
                (
                    int(user_id),
                    str(modulo),
                    1 if actions.get("ver") else 0,
                    1 if actions.get("crear") else 0,
                    1 if actions.get("editar") else 0,
                    1 if actions.get("eliminar") else 0,
                    1 if actions.get("aprobar") else 0,
                    1 if actions.get("exportar") else 0,
                ),
            )
        db.commit()
        return True
    finally:
        cursor.close()
        db.close()


def user_has_explicit_permissions(user_id: int) -> bool:
    db = get_db()
    cursor = db.cursor(dictionary=True)
    try:
        cursor.execute(
            "SELECT 1 FROM usuario_modulo_permisos WHERE usuario_id = %s LIMIT 1",
            (int(user_id),),
        )
        return cursor.fetchone() is not None
    finally:
        cursor.close()
        db.close()


def user_can_access_module(
    *,
    user_id: int,
    role: str | None,
    module: str,
    action: str = "ver",
) -> bool:
    role_norm = str(role or "").strip().lower()
    if role_norm == "admin":
        return True
    action_norm = str(action or "ver").strip().lower()
    if action_norm not in PERMISSION_ACTIONS:
        action_norm = "ver"

    permissions = get_user_permissions(int(user_id))
    if permissions:
        return bool(permissions.get(module, {}).get(action_norm))

    # Compatibilidad: usuarios existentes sin permisos explicitos conservan
    # exactamente el acceso derivado de su rol actual.
    return module in role_default_module_codes(role_norm)
