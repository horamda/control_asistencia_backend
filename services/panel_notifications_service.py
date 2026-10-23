from flask import current_app, url_for

from extensions import get_db

_ADMIN_ROLES = {"admin", "rrhh"}


def _build_item(*, key: str, label: str, description: str, count: int, href: str, tone: str) -> dict:
    return {
        "key": key,
        "label": label,
        "description": description,
        "count": int(count),
        "href": href,
        "tone": tone,
    }


def build_panel_notifications(role: str | None, empresa_id: int | None = None) -> dict:
    """empresa_id: usuario que no es admin, cuenta solo los pendientes de empleados de su empresa."""
    role_norm = str(role or "").strip().lower()
    if role_norm not in _ADMIN_ROLES:
        return {"enabled": False, "total": 0, "items": []}
    de_la_empresa = (lambda alias: f" AND EXISTS (SELECT 1 FROM empleados e WHERE e.id = {alias}.empleado_id"
                                   f" AND e.empresa_id = {int(empresa_id)})") if empresa_id is not None else (lambda alias: "")

    db = get_db()
    cursor = db.cursor(dictionary=True)
    try:
        cursor.execute(f"""SELECT (SELECT COUNT(*) AS total
            FROM justificaciones j
            WHERE (j.estado = 'pendiente'
               OR j.estado IS NULL){de_la_empresa('j')}) AS justificaciones,
(SELECT COUNT(*) AS total
            FROM vacaciones_movimientos vm
            WHERE vm.estado = 'pendiente'
              AND vm.revertido_por_movimiento_id IS NULL
              AND vm.origen_movimiento_id IS NULL{de_la_empresa('vm')}) AS vacaciones,
(SELECT COUNT(*) AS total
            FROM adelantos ad
            WHERE (ad.estado = 'pendiente'
               OR ad.estado IS NULL){de_la_empresa('ad')}) AS adelantos,
(SELECT COUNT(*) AS total
            FROM pedidos_mercaderia pm
            WHERE (pm.estado = 'pendiente'
               OR pm.estado IS NULL){de_la_empresa('pm')}) AS pedidos""")
        counts = cursor.fetchone()
        items = []

        justificaciones = int(counts.get("justificaciones") or 0)
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

        vacaciones = int(counts.get("vacaciones") or 0)
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

        adelantos = int(counts.get("adelantos") or 0)
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

        pedidos = int(counts.get("pedidos") or 0)
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
