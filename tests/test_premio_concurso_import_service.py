import io

import services.premio_concurso_import_service as import_service


def test_importar_premios_csv_ok(monkeypatch):
    saved = []
    monkeypatch.setattr(
        import_service,
        "get_empleados_lookup_by_empresa",
        lambda empresa_id: {
            "L001": {
                "id": 10,
                "empresa_id": empresa_id,
                "legajo": "L001",
                "nombre": "Ana",
                "apellido": "Lopez",
                "sector_id": 3,
                "sector_nombre": "Logistica",
            }
        },
    )
    monkeypatch.setattr(
        import_service,
        "get_concursos_for_empresa",
        lambda empresa_id, **kw: [
            {
                "id": 9,
                "empresa_id": empresa_id,
                "codigo": "SEGURIDAD",
                "nombre": "Premio de seguridad",
                "alcance": "global",
                "sector_id": None,
            }
        ],
    )
    monkeypatch.setattr(
        import_service,
        "save_prepared_resultado",
        lambda prepared: saved.append(prepared) or (len(saved), True),
    )

    payload = (
        "periodo,legajo,codigo_concurso,ranking\n"
        "2026-01,L001,SEGURIDAD,1\n"
        "2026-03,L001,SEGURIDAD,3\n"
        "2026-04,L001,SEGURIDAD,4\n"
    ).encode("utf-8")
    result = import_service.importar_premios_desde_archivo(1, io.BytesIO(payload), "premios.csv", actor_id=99)

    assert result["total_filas"] == 3
    assert result["importadas"] == 3
    assert result["errores"] == 0
    assert [row["periodo"] for row in saved] == ["2026-01-01", "2026-03-01", "2026-04-01"]
    assert [row["ranking"] for row in saved] == [1, 3, 4]


def test_importar_premios_csv_valida_sector(monkeypatch):
    monkeypatch.setattr(
        import_service,
        "get_empleados_lookup_by_empresa",
        lambda empresa_id: {
            "L001": {
                "id": 10,
                "empresa_id": empresa_id,
                "legajo": "L001",
                "nombre": "Ana",
                "apellido": "Lopez",
                "sector_id": 3,
            }
        },
    )
    monkeypatch.setattr(
        import_service,
        "get_concursos_for_empresa",
        lambda empresa_id, **kw: [
            {
                "id": 12,
                "empresa_id": empresa_id,
                "codigo": "VENTAS_MES",
                "nombre": "Ventas del mes",
                "alcance": "sector",
                "sector_id": 4,
            }
        ],
    )
    monkeypatch.setattr(import_service, "save_prepared_resultado", lambda prepared: (1, True))

    payload = b"periodo,legajo,codigo_concurso,ranking\n2026-01,L001,VENTAS_MES,1\n"
    result = import_service.importar_premios_desde_archivo(1, io.BytesIO(payload), "premios.csv")

    assert result["importadas"] == 0
    assert result["errores"] == 1
    assert "sector" in result["detalle_errores"][0]["error"]
