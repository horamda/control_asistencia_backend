import pytest

import services.pedido_mercaderia_service as pedido_service


def test_get_pedido_mes_actual_usa_periodo_derivado_de_fecha(monkeypatch):
    captured = {}

    def _fake_get_by_empleado_periodo(empleado_id, periodo_year, periodo_month):
        captured.update(
            {
                "empleado_id": empleado_id,
                "periodo_year": periodo_year,
                "periodo_month": periodo_month,
            }
        )
        return None

    monkeypatch.setattr(pedido_service, "get_by_empleado_periodo", _fake_get_by_empleado_periodo)

    pedido_service.get_pedido_mes_actual(10, fecha_pedido="2026-04-18")

    assert captured == {
        "empleado_id": 10,
        "periodo_year": 2026,
        "periodo_month": 4,
    }


def test_solicitar_pedido_ok(monkeypatch):
    created = {}

    monkeypatch.setattr(
        pedido_service,
        "get_empleado_by_id",
        lambda empleado_id: {"id": empleado_id, "empresa_id": 3},
    )
    monkeypatch.setattr(pedido_service, "get_by_empleado_periodo", lambda *args: None)
    monkeypatch.setattr(
        pedido_service,
        "get_articulos_by_ids",
        lambda ids, **kw: [
            {"id": 5, "codigo_articulo": "A1", "descripcion": "Gaseosa", "unidades_por_bulto": 8}
        ],
    )
    monkeypatch.setattr(
        pedido_service,
        "create",
        lambda data, items: created.update({"data": data, "items": items}) or 91,
    )

    pedido_id = pedido_service.solicitar_pedido(
        empleado_id=10,
        empresa_id=3,
        fecha_pedido="2026-04-18",
        items=[{"articulo_id": 5, "cantidad_bultos": 2}],
    )

    assert pedido_id == 91
    assert created["data"]["empleado_id"] == 10
    assert created["data"]["periodo_year"] == 2026
    assert created["data"]["periodo_month"] == 4
    assert created["data"]["fecha_pedido"] == "2026-04-18"
    assert created["items"] == [
        {
            "articulo_id": 5,
            "cantidad_bultos": 2,
            "codigo_articulo_snapshot": "A1",
            "descripcion_snapshot": "Gaseosa",
            "unidades_por_bulto_snapshot": 8,
        }
    ]


def test_solicitar_pedido_rechaza_duplicado_logico(monkeypatch):
    monkeypatch.setattr(
        pedido_service,
        "get_empleado_by_id",
        lambda empleado_id: {"id": empleado_id, "empresa_id": 3},
    )
    monkeypatch.setattr(
        pedido_service,
        "get_by_empleado_periodo",
        lambda *args: {"id": 99, "periodo_year": 2026, "periodo_month": 4},
    )
    monkeypatch.setattr(
        pedido_service,
        "get_articulos_by_ids",
        lambda ids, **kw: [
            {"id": 5, "codigo_articulo": "A1", "descripcion": "Gaseosa", "unidades_por_bulto": 8}
        ],
    )

    with pytest.raises(
        pedido_service.PedidoMercaderiaAlreadyRequestedError,
        match="este mes",
    ):
        pedido_service.solicitar_pedido(
            empleado_id=10,
            empresa_id=3,
            fecha_pedido="2026-04-18",
            items=[{"articulo_id": 5, "cantidad_bultos": 2}],
        )


def test_solicitar_pedido_rechaza_articulo_duplicado(monkeypatch):
    monkeypatch.setattr(
        pedido_service,
        "get_empleado_by_id",
        lambda empleado_id: {"id": empleado_id, "empresa_id": 3},
    )

    with pytest.raises(ValueError, match="No puede repetir un articulo"):
        pedido_service.solicitar_pedido(
            empleado_id=10,
            empresa_id=3,
            fecha_pedido="2026-04-18",
            items=[
                {"articulo_id": 5, "cantidad_bultos": 2},
                {"articulo_id": 5, "cantidad_bultos": 1},
            ],
        )


def test_editar_pedido_pendiente_ok(monkeypatch):
    captured = {}
    monkeypatch.setattr(
        pedido_service,
        "get_by_id",
        lambda pedido_id: {"id": pedido_id, "empleado_id": 10, "estado": "pendiente"},
    )
    monkeypatch.setattr(
        pedido_service,
        "get_articulos_by_ids",
        lambda ids, **kw: [
            {"id": 5, "codigo_articulo": "A1", "descripcion": "Gaseosa", "unidades_por_bulto": 8}
        ],
    )
    monkeypatch.setattr(
        pedido_service,
        "replace_items",
        lambda pedido_id, items: captured.update({"pedido_id": pedido_id, "items": items}),
    )

    pedido_service.editar_pedido(
        91,
        empleado_id=10,
        items=[{"articulo_id": 5, "cantidad_bultos": 3}],
    )

    assert captured["pedido_id"] == 91
    assert captured["items"][0]["cantidad_bultos"] == 3


def test_cancelar_pedido_pendiente_ok(monkeypatch):
    called = {}
    monkeypatch.setattr(
        pedido_service,
        "get_by_id",
        lambda pedido_id: {"id": pedido_id, "empleado_id": 10, "estado": "pendiente"},
    )
    monkeypatch.setattr(
        pedido_service,
        "update_estado",
        lambda pedido_id, estado, **kw: called.update({"pedido_id": pedido_id, "estado": estado}),
    )

    pedido_service.cancelar_pedido(91, empleado_id=10)

    assert called == {"pedido_id": 91, "estado": "cancelado"}


def test_aprobar_pedido_desde_pendiente(monkeypatch):
    called = {}
    monkeypatch.setattr(
        pedido_service,
        "get_by_id",
        lambda pedido_id: {"id": pedido_id, "estado": "pendiente"},
    )
    monkeypatch.setattr(
        pedido_service,
        "update_estado",
        lambda pedido_id, estado, **kw: called.update(
            {"pedido_id": pedido_id, "estado": estado, "actor_id": kw.get("resuelto_by_usuario_id")}
        ),
    )

    pedido_service.aprobar_pedido(91, actor_id=7)

    assert called == {"pedido_id": 91, "estado": "aprobado", "actor_id": 7}


def test_rechazar_pedido_desde_pendiente(monkeypatch):
    called = {}
    monkeypatch.setattr(
        pedido_service,
        "get_by_id",
        lambda pedido_id: {"id": pedido_id, "estado": "pendiente"},
    )
    monkeypatch.setattr(
        pedido_service,
        "update_estado",
        lambda pedido_id, estado, **kw: called.update(
            {
                "pedido_id": pedido_id,
                "estado": estado,
                "actor_id": kw.get("resuelto_by_usuario_id"),
                "motivo_rechazo": kw.get("motivo_rechazo"),
            }
        ),
    )

    pedido_service.rechazar_pedido(91, actor_id=7, motivo_rechazo="Sin stock")

    assert called == {
        "pedido_id": 91,
        "estado": "rechazado",
        "actor_id": 7,
        "motivo_rechazo": "Sin stock",
    }
