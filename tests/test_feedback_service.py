import datetime
import io

import pytest

import services.feedback_import_service as import_service
import services.feedback_service as feedback_service


def test_create_feedback_sets_due_date_and_snapshots(monkeypatch):
    empleado = {
        "id": 10,
        "activo": 1,
        "empresa_id": 3,
        "reporta_a_empleado_id": 20,
        "nombre": "Ana",
        "apellido": "Lopez",
    }
    jefe = {
        "id": 20,
        "activo": 1,
        "nombre": "Jose",
        "apellido": "Perez",
    }
    cliente = {
        "id": 7,
        "activo": 1,
        "codigo_externo": "C-7",
        "razon_social": "Cliente SA",
        "nombre_fantasia": "Cliente",
        "tipo_descripcion": "ALMACEN",
    }
    motivo = {
        "id": 5,
        "activo": 1,
        "nombre": "Rotura de mercaderia",
        "sla_dias": 3,
    }
    captured = {}

    monkeypatch.setattr(feedback_service, "get_empleado_by_id", lambda empleado_id: empleado if empleado_id == 10 else jefe)
    monkeypatch.setattr(feedback_service, "get_cliente_by_id", lambda cliente_id: cliente)
    monkeypatch.setattr(feedback_service, "get_motivo_by_id", lambda motivo_id: motivo)
    monkeypatch.setattr(
        feedback_service,
        "create_feedback_row",
        lambda data: captured.update(data) or 99,
    )

    feedback_id = feedback_service.create_feedback(
        empleado_id=10,
        cliente_id=7,
        motivo_id=5,
        descripcion="Se rompio una caja en la calle",
    )

    assert feedback_id == 99
    assert captured["empresa_id"] == 3
    assert captured["jefe_directo_id"] == 20
    assert captured["cliente_codigo_snapshot"] == "C-7"
    assert captured["motivo_nombre_snapshot"] == "Rotura de mercaderia"
    assert captured["fecha_vencimiento"] == (datetime.date.today() + datetime.timedelta(days=3)).isoformat()


def test_create_feedback_without_boss_fails(monkeypatch):
    empleado = {
        "id": 10,
        "activo": 1,
        "empresa_id": 3,
        "reporta_a_empleado_id": None,
    }
    monkeypatch.setattr(feedback_service, "get_empleado_by_id", lambda empleado_id: empleado)
    with pytest.raises(ValueError, match="jefe directo"):
        feedback_service.create_feedback(
            empleado_id=10,
            cliente_id=7,
            motivo_id=5,
            descripcion="Problema",
        )


def test_resolver_feedback_only_direct_boss(monkeypatch):
    current = {
        "id": 44,
        "jefe_directo_id": 20,
        "estado": "pendiente",
        "fecha_vencimiento": datetime.date.today(),
    }
    captured = {}
    monkeypatch.setattr(feedback_service, "get_by_id", lambda feedback_id: current)
    monkeypatch.setattr(
        feedback_service,
        "update_estado",
        lambda feedback_id, estado, **kwargs: captured.update({"feedback_id": feedback_id, "estado": estado, **kwargs}),
    )

    feedback_service.resolver_feedback(
        44,
        actor_empleado_id=20,
        resolucion_descripcion="Se entrego reposicion al cliente",
    )

    assert captured["feedback_id"] == 44
    assert captured["estado"] == "resuelto"
    assert captured["resolucion_descripcion"] == "Se entrego reposicion al cliente"
    assert captured["resuelto_en_sla"] is True


def test_importar_clientes_desde_csv(monkeypatch):
    csv_content = (
        "Sucursal;Cliente;Razon social;Nombre de fantasia;Telefonos;Movil;e-Mail;Domicilio;Localidad;Provincia;Ramo;Descripcion ramo;Coord X;Coord Y;Comentario;Anulado\n"
        "1;10;Cliente SA;Fantasia SA;111;222;cliente@test.com;Calle 1;Dolores;Buenos Aires;8;ALMACEN;-56.1;-36.2;Nota;NO\n"
    )
    captured = []

    monkeypatch.setattr(
        import_service,
        "upsert_cliente",
        lambda payload: captured.append(payload) or (1, True),
    )

    resultado = import_service.importar_clientes_desde_csv(io.BytesIO(csv_content.encode("utf-8")))

    assert resultado["total_filas"] == 1
    assert resultado["importadas"] == 1
    assert resultado["creados"] == 1
    assert resultado["errores"] == 0
    assert captured[0]["codigo_externo"] == "10"
    assert captured[0]["tipo_descripcion"] == "ALMACEN"
    assert captured[0]["activo"] is True
    assert captured[0]["latitud"] == -36.2
    assert captured[0]["longitud"] == -56.1
