from repositories.auditoria_repository import create as create_audit


def log_audit(session, accion: str, tabla: str, registro_id: int | None):
    # Auditoria referencia usuarios.id.
    usuario_id = None
    if session and "user_id" in session:
        usuario_id = session.get("user_id")
    create_audit(usuario_id, accion, tabla, registro_id)
