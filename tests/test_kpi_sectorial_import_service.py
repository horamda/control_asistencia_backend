import io
import datetime

import services.kpi_sectorial_import_service as import_service


class _FakeCursor:
    def __init__(self):
        self._last_query = ""

    def execute(self, query, params=()):
        self._last_query = query

    def fetchall(self):
        if "FROM empleados" in self._last_query:
            return [
                {"id": 101, "legajo": "A1", "sector_id": 1},
                {"id": 202, "legajo": "B2", "sector_id": 2},
            ]
        if "FROM kpis_definicion" in self._last_query:
            return [
                {"id": 1001, "codigo": "DUP", "sector_id": 1},
                {"id": 2001, "codigo": "DUP", "sector_id": 2},
                {"id": 1002, "codigo": "SOLO_S1", "sector_id": 1},
            ]
        return []

    def close(self):
        pass


class _FakeDb:
    def cursor(self, dictionary=False):
        return _FakeCursor()

    def close(self):
        pass


def _install_fake_db(monkeypatch):
    monkeypatch.setattr(import_service, "get_db", lambda: _FakeDb())


def test_importar_resultados_mapea_codigo_por_sector_del_empleado(monkeypatch):
    _install_fake_db(monkeypatch)
    inserted = []
    monkeypatch.setattr(import_service, "bulk_upsert_resultados", lambda rows: inserted.extend(rows))

    csv_data = (
        "fecha,legajo,codigo_kpi,valor\n"
        "2024-04-01,A1,DUP,5\n"
        "2024-04-01,B2,DUP,7\n"
    )

    result = import_service.importar_resultados_desde_csv(1, io.BytesIO(csv_data.encode("utf-8")))

    assert result["importadas"] == 2
    assert result["errores"] == 0
    assert inserted == [
        (1, 101, 1001, "2024-04-01", 5.0),
        (1, 202, 2001, "2024-04-01", 7.0),
    ]


def test_importar_resultados_rechaza_codigo_fuera_del_sector_del_empleado(monkeypatch):
    _install_fake_db(monkeypatch)
    monkeypatch.setattr(import_service, "bulk_upsert_resultados", lambda rows: None)

    csv_data = "fecha,legajo,codigo_kpi,valor\n2024-04-01,B2,SOLO_S1,5\n"

    result = import_service.importar_resultados_desde_csv(1, io.BytesIO(csv_data.encode("utf-8")))

    assert result["importadas"] == 0
    assert result["errores"] == 1
    assert "sector del empleado" in result["detalle_errores"][0]["error"]


def test_importar_resultados_limpia_mes_actual_para_empleados_del_csv(monkeypatch):
    _install_fake_db(monkeypatch)
    monkeypatch.setattr(import_service, "_today", lambda: datetime.date(2024, 4, 15))
    calls = []

    def fake_delete(empresa_id, anio, mes, empleado_ids):
        calls.append(("delete", empresa_id, anio, mes, sorted(empleado_ids)))
        return 3

    def fake_upsert(rows):
        calls.append(("upsert", rows))

    monkeypatch.setattr(import_service, "delete_resultados_mes_empleados", fake_delete)
    monkeypatch.setattr(import_service, "bulk_upsert_resultados", fake_upsert)

    csv_data = (
        "fecha,legajo,codigo_kpi,valor\n"
        "2024-04-01,A1,DUP,5\n"
        "2024-04-02,B2,DUP,7\n"
        "2024-03-31,A1,DUP,4\n"
    )

    result = import_service.importar_resultados_desde_csv(1, io.BytesIO(csv_data.encode("utf-8")))

    assert result["importadas"] == 3
    assert result["limpiadas_mes_actual"] == 3
    assert result["empleados_limpiados_mes_actual"] == 2
    assert result["periodo_limpiado"] == "2024-04"
    assert calls[0] == ("delete", 1, 2024, 4, [101, 202])
    assert calls[1][0] == "upsert"
