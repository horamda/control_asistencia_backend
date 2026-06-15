from flask import current_app, url_for

from extensions import get_db

_ADMIN_ROLES = {"admin", "rrhh"}


def _safe_count(cursor, query: str, params: tuple = ()) -> int:
    try:
        cursor.execute(query, params)
        row = cursor.fetchone() or {}
        if isinstance(row, dict):
            value = next(iter(row.values()), 0)
        else:
            value = row[0] if row else 0
        return int(value or 0)
    except Exception:
        current_app.logger.warning("panel_notifications_count_error", exc_info=True)
        return 0


def _build_item(*, key: str, label: str, description: str, count: int, href: str, tone: str) -> dict:
    return {
        "key": key,
        "label": label,
        "description": description,
        "count": int(count),
        "href": href,
        "tone": tone,
    }


def build_panel_notifications(role: str | None) -> dict:
    role_norm = str(role or "").strip().lower()
    if role_norm not in _ADMIN_ROLES:
        return {"enabled": False, "total": 0, "items": []}

    db = get_db()
    cursor = db.cursor(dictionary=True)
    try:
        items = []

        justificaciones = _safe_count(
            cursor,
            """
            SELECT COUNT(*) AS total
            FROM justificaciones
            WHERE LOWER(COALESCE(estado, 'pendiente')) = 'pendiente'
            """,
        )
        if justificaciones:
            items.append(
                _build_item(
                    key="justificaciones",
                    label="Justificaciones",
                    description="Solicitudes pendientes de revisar",
                    count=justificaciones,
                    href=url_for("justificaciones.listado", estado="pendiente"),
                    tone="warning",
                )
            )

        vacaciones = _safe_count(
            cursor,
            """
            SELECT COUNT(*) AS total
            FROM vacaciones_movimientos vm
            WHERE vm.estado = 'pendiente'
              AND vm.revertido_por_movimiento_id IS NULL
              AND vm.origen_movimiento_id IS NULL
            """,
        )
        if vacaciones:
            items.append(
                _build_item(
                    key="vacaciones",
                    label="Vacaciones",
                    description="Solicitudes mobile sin resolver",
                    count=vacaciones,
                    href=url_for("vacaciones.listado", estado="pendiente"),
                    tone="info",
                )
            )

        adelantos = _safe_count(
            cursor,
            """
            SELECT COUNT(*) AS total
            FROM adelantos
            WHERE LOWER(COALESCE(estado, 'pendiente')) = 'pendiente'
            """,
        )
        if adelantos:
            items.append(
                _build_item(
                    key="adelantos",
                    label="Adelantos",
                    description="Solicitudes pendientes de pago o rechazo",
                    count=adelantos,
                    href=url_for("adelantos.listado", estado="pendiente"),
                    tone="warning",
                )
            )

        pedidos = _safe_count(
            cursor,
            """
            SELECT COUNT(*) AS total
            FROM pedidos_mercaderia
            WHERE LOWER(COALESCE(estado, 'pendiente')) = 'pendiente'
            """,
        )
        if pedidos:
            items.append(
                _build_item(
                    key="pedidos_mercaderia",
                    label="Pedidos de mercaderia",
                    description="Solicitudes pendientes de aprobacion",
                    count=pedidos,
                    href=url_for("pedidos_mercaderia.listado", estado="pendiente"),
                    tone="info",
                )
            )

        total = sum(item["count"] for item in items)
        return {
            "enabled": True,
            "total": total,
            "items": items,
            "has_items": bool(items),
        }
    finally:
        cursor.close()
        db.close()
