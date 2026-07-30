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
        "sector_id": 4,
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
        "sector_id": 4,
        "tiempo_resolucion_valor": 3,
        "tiempo_resolucion_unidad": "DIAS",
        "requiere_observacion": 1,
    }
    sector = {"id": 4, "activo": 1, "responsable_empleado_id": 20}
    captured = {}

    monkeypatch.setattr(feedback_service, "get_empleado_by_id", lambda empleado_id: empleado if empleado_id == 10 else jefe)
    monkeypatch.setattr(feedback_service, "get_sector_by_id", lambda sector_id: sector)
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
    assert captured["responsable_id"] == 20
    assert captured["sector_origen_id"] == 4
    assert captured["sector_responsable_id"] == 4
    assert captured["cliente_codigo_snapshot"] == "C-7"
    assert captured["motivo_nombre_snapshot"] == "Rotura de mercaderia"
    assert captured["fecha_vencimiento"] == (datetime.date.today() + datetime.timedelta(days=3)).isoformat()


def test_create_feedback_assigns_immediate_direct_boss_not_upper_boss(monkeypatch):
    empleado = {
        "id": 10,
        "activo": 1,
        "empresa_id": 3,
        "reporta_a_empleado_id": 20,
        "sector_id": 4,
        "nombre": "Empleado",
        "apellido": "Carga",
    }
    jefe_directo = {
        "id": 20,
        "activo": 1,
        "reporta_a_empleado_id": 30,
        "nombre": "Jefe",
        "apellido": "Directo",
    }
    jefe_superior = {"id": 30, "activo": 1, "nombre": "Jefe", "apellido": "Superior"}
    cliente = {"id": 7, "activo": 1, "codigo_externo": "C-7", "razon_social": "Cliente SA"}
    motivo = {
        "id": 5,
        "activo": 1,
        "nombre": "Visita",
        "sla_dias": 1,
        "sector_id": 9,
        "tiempo_resolucion_valor": 1,
        "tiempo_resolucion_unidad": "DIAS",
        "requiere_observacion": 1,
    }
    sector_responsable = {"id": 9, "activo": 1, "responsable_empleado_id": 30}
    captured = {}

    def fake_empleado(empleado_id):
        return {10: empleado, 20: jefe_directo, 30: jefe_superior}.get(empleado_id)

    monkeypatch.setattr(feedback_service, "get_empleado_by_id", fake_empleado)
    monkeypatch.setattr(feedback_service, "get_sector_by_id", lambda sector_id: sector_responsable)
    monkeypatch.setattr(feedback_service, "get_cliente_by_id", lambda cliente_id: cliente)
    monkeypatch.setattr(feedback_service, "get_motivo_by_id", lambda motivo_id: motivo)
    monkeypatch.setattr(feedback_service, "create_feedback_row", lambda data: captured.update(data) or 99)

    feedback_service.create_feedback(
        empleado_id=10,
        cliente_id=7,
        motivo_id=5,
        descripcion="Caso para jefe directo",
    )

    assert captured["jefe_directo_id"] == 20
    assert captured["responsable_id"] == 20
    assert captured["sector_responsable_id"] == 9
    assert captured["jefe_directo_nombre_snapshot"] == "Directo Jefe"


def test_create_feedback_with_evidence_saves_metadata(monkeypatch, tmp_path):
    empleado = {
        "id": 10,
        "activo": 1,
        "empresa_id": 3,
        "reporta_a_empleado_id": 20,
        "sector_id": 4,
    }
    jefe = {"id": 20, "activo": 1, "nombre": "Jose", "apellido": "Perez"}
    cliente = {
        "id": 7,
        "activo": 1,
        "codigo_externo": "C-7",
        "razon_social": "Cliente SA",
    }
    motivo = {"id": 5, "activo": 1, "nombre": "Rotura", "sla_dias": 1, "sector_id": 4}
    sector = {"id": 4, "activo": 1, "responsable_empleado_id": 20}
    captured = {}

    monkeypatch.setenv("FEEDBACK_EVIDENCIAS_DIR", str(tmp_path))
    monkeypatch.setattr(feedback_service, "get_empleado_by_id", lambda empleado_id: empleado if empleado_id == 10 else jefe)
    monkeypatch.setattr(feedback_service, "get_sector_by_id", lambda sector_id: sector)
    monkeypatch.setattr(feedback_service, "get_cliente_by_id", lambda cliente_id: cliente)
    monkeypatch.setattr(feedback_service, "get_motivo_by_id", lambda motivo_id: motivo)
    monkeypatch.setattr(feedback_service, "create_feedback_row", lambda data: captured.update(data) or 99)

    from werkzeug.datastructures import FileStorage

    evidencia = FileStorage(
        stream=io.BytesIO(b"\x89PNG\r\n\x1a\nfake"),
        filename="foto evidencia.png",
        content_type="image/png",
    )

    feedback_id = feedback_service.create_feedback(
        empleado_id=10,
        cliente_id=7,
        motivo_id=5,
        descripcion="Foto cargada desde el panel",
        evidencia_file=evidencia,
    )

    assert feedback_id == 99
    assert captured["evidencia_filename"] == "foto_evidencia.png"
    assert captured["evidencia_mime_type"] == "image/png"
    assert captured["evidencia_size_bytes"] == 12
    assert (tmp_path / captured["evidencia_path"]).exists()


def test_create_feedback_without_responsable_fails(monkeypatch):
    empleado = {
        "id": 10,
        "activo": 1,
        "empresa_id": 3,
        "sector_id": 4,
    }
    cliente = {"id": 7, "activo": 1}
    motivo = {"id": 5, "activo": 1, "nombre": "Rotura", "sla_dias": 1, "sector_id": 4}
    sector = {"id": 4, "activo": 1, "responsable_empleado_id": None}
    monkeypatch.setattr(feedback_service, "get_empleado_by_id", lambda empleado_id: empleado)
    monkeypatch.setattr(feedback_service, "get_cliente_by_id", lambda cliente_id: cliente)
    monkeypatch.setattr(feedback_service, "get_motivo_by_id", lambda motivo_id: motivo)
    monkeypatch.setattr(feedback_service, "get_sector_by_id", lambda sector_id: sector)
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


def test_importar_clientes_desde_csv_cp1252_preserva_acentos(monkeypatch):
    csv_content = (
        "Sucursal;Cliente;Razon social;Nombre de fantasia;Localidad;Provincia;Anulado\n"
        "1;11;NIÑO ÑANDÚ SA;Café Martínez;Córdoba;Tucumán;NO\n"
    )
    captured = []

    monkeypatch.setattr(
        import_service,
        "upsert_cliente",
        lambda payload: captured.append(payload) or (1, True),
    )

    resultado = import_service.importar_clientes_desde_csv(io.BytesIO(csv_content.encode("cp1252")))

    assert resultado["importadas"] == 1
    assert resultado["errores"] == 0
    assert captured[0]["razon_social"] == "NIÑO ÑANDÚ SA"
    assert captured[0]["nombre_fantasia"] == "Café Martínez"
    assert captured[0]["localidad"] == "Córdoba"
    assert captured[0]["provincia"] == "Tucumán"
