import datetime

from repositories.articulo_catalogo_pedido_repository import get_by_ids as get_articulos_by_ids
from repositories.empleado_repository import get_by_id as get_empleado_by_id
from repositories.pedido_mercaderia_repository import (
    create,
    get_by_empleado_periodo,
    get_by_id,
    replace_items,
    update_estado,
)


class PedidoMercaderiaAlreadyRequestedError(ValueError):
    pass


def _parse_fecha_pedido(fecha_pedido: str | None) -> datetime.date:
    raw = str(fecha_pedido or "").strip()
    if not raw:
        return datetime.date.today()
    return datetime.date.fromisoformat(raw)


def _is_duplicate_period_error(exc: Exception) -> bool:
    if getattr(exc, "errno", None) == 1062:
        return True
    orig = getattr(exc, "orig", None)
    if orig is not None and getattr(orig, "errno", None) == 1062:
        return True
    text = str(exc)
    return "Duplicate entry" in text or "uk_pedidos_mercaderia_empleado_periodo" in text


def get_pedido_mes_actual(empleado_id: int, *, fecha_pedido: str | None = None):
    fecha = _parse_fecha_pedido(fecha_pedido)
    return get_by_empleado_periodo(empleado_id, fecha.year, fecha.month)


def _require_record(pedido_id: int) -> dict:
    record = get_by_id(pedido_id)
    if not record:
        raise ValueError("Pedido no encontrado.")
    return record


def _normalize_items(items_payload) -> list[dict]:
    if not isinstance(items_payload, list) or not items_payload:
        raise ValueError("Debe enviar al menos un articulo.")

    normalized = []
    seen_articulos = set()

    for index, raw_item in enumerate(items_payload, start=1):
        if not isinstance(raw_item, dict):
            raise ValueError(f"Item #{index} invalido.")

        try:
            articulo_id = int(raw_item.get("articulo_id"))
        except (TypeError, ValueError):
            raise ValueError(f"Item #{index}: articulo_id invalido.")

        try:
            cantidad_bultos = int(raw_item.get("cantidad_bultos"))
        except (TypeError, ValueError):
            raise ValueError(f"Item #{index}: cantidad_bultos invalida.")

        if articulo_id <= 0:
            raise ValueError(f"Item #{index}: articulo_id invalido.")
        if cantidad_bultos <= 0:
            raise ValueError(f"Item #{index}: cantidad_bultos debe ser mayor a cero.")
        if articulo_id in seen_articulos:
            raise ValueError("No puede repetir un articulo dentro del mismo pedido.")

        seen_articulos.add(articulo_id)
        normalized.append(
            {
                "articulo_id": articulo_id,
                "cantidad_bultos": cantidad_bultos,
            }
        )

    catalog_rows = get_articulos_by_ids([item["articulo_id"] for item in normalized], habilitado_only=True)
    catalog_by_id = {int(row["id"]): row for row in catalog_rows}
    if len(catalog_by_id) != len(normalized):
        raise ValueError("Uno o mas articulos no existen o no estan habilitados para pedido.")

    prepared = []
    for item in normalized:
        articulo = catalog_by_id[item["articulo_id"]]
        prepared.append(
            {
                "articulo_id": item["articulo_id"],
                "cantidad_bultos": item["cantidad_bultos"],
                "codigo_articulo_snapshot": articulo.get("codigo_articulo"),
                "descripcion_snapshot": articulo.get("descripcion"),
                "unidades_por_bulto_snapshot": int(articulo.get("unidades_por_bulto") or 0),
            }
        )
    return prepared


def solicitar_pedido(
    *,
    empleado_id: int,
    empresa_id: int | None = None,
    fecha_pedido: str | None = None,
    items: list[dict] | None = None,
) -> int:
    if not empleado_id:
        raise ValueError("Empleado es requerido.")

    empleado = get_empleado_by_id(empleado_id)
    if not empleado:
        raise ValueError("Empleado no encontrado.")

    prepared_items = _normalize_items(items)
    fecha = _parse_fecha_pedido(fecha_pedido)
    periodo_year = fecha.year
    periodo_month = fecha.month

    existente = get_by_empleado_periodo(empleado_id, periodo_year, periodo_month)
    if existente:
        raise PedidoMercaderiaAlreadyRequestedError("Ya registraste un pedido de mercaderia en este mes.")

    resolved_empresa_id = empresa_id or empleado.get("empresa_id")
    if not resolved_empresa_id:
        raise ValueError("Empleado invalido o sin empresa asignada.")

    try:
        return create(
            {
                "empresa_id": resolved_empresa_id,
                "empleado_id": empleado_id,
                "periodo_year": periodo_year,
                "periodo_month": periodo_month,
                "fecha_pedido": fecha.isoformat(),
                "estado": "pendiente",
            },
            prepared_items,
        )
    except Exception as exc:
        if _is_duplicate_period_error(exc):
            raise PedidoMercaderiaAlreadyRequestedError("Ya registraste un pedido de mercaderia en este mes.") from exc
        raise


def editar_pedido(
    pedido_id: int,
    *,
    empleado_id: int,
    items: list[dict] | None = None,
) -> None:
    current = _require_record(pedido_id)
    if int(current.get("empleado_id") or 0) != int(empleado_id):
        raise ValueError("Pedido no encontrado.")
    estado_actual = (current.get("estado") or "pendiente").strip()
    if estado_actual != "pendiente":
        raise ValueError(f"No se puede editar un pedido en estado '{estado_actual}'.")

    prepared_items = _normalize_items(items)
    replace_items(pedido_id, prepared_items)


def cancelar_pedido(
    pedido_id: int,
    *,
    empleado_id: int,
) -> None:
    current = _require_record(pedido_id)
    if int(current.get("empleado_id") or 0) != int(empleado_id):
        raise ValueError("Pedido no encontrado.")
    estado_actual = (current.get("estado") or "pendiente").strip()
    if estado_actual != "pendiente":
        raise ValueError(f"No se puede cancelar un pedido en estado '{estado_actual}'.")

    update_estado(pedido_id, "cancelado")


def aprobar_pedido(pedido_id: int, *, actor_id: int | None = None) -> None:
    current = _require_record(pedido_id)
    estado_actual = (current.get("estado") or "pendiente").strip()
    if estado_actual != "pendiente":
        raise ValueError(f"No se puede aprobar un pedido en estado '{estado_actual}'.")
    update_estado(pedido_id, "aprobado", resuelto_by_usuario_id=actor_id)


def rechazar_pedido(
    pedido_id: int,
    *,
    actor_id: int | None = None,
    motivo_rechazo: str | None = None,
) -> None:
    current = _require_record(pedido_id)
    estado_actual = (current.get("estado") or "pendiente").strip()
    if estado_actual != "pendiente":
        raise ValueError(f"No se puede rechazar un pedido en estado '{estado_actual}'.")
    update_estado(
        pedido_id,
        "rechazado",
        resuelto_by_usuario_id=actor_id,
        motivo_rechazo=motivo_rechazo,
    )
