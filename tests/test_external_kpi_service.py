import datetime
from decimal import Decimal
from unittest.mock import Mock

import pytest

import services.external_kpi_service as service
import repositories.kpi_sectorial_repository as repository


@pytest.fixture
def storage(monkeypatch):
    lookup = Mock(return_value=({
        "001": {"id": 10, "sector_id": 3},
        "002": {"id": 11, "sector_id": 4},
        "003": {"id": 12, "sector_id": None},
    }, {(3, "BULTOS"): 30, (4, "BULTOS"): 40}))
    save = Mock()
    monkeypatch.setattr(service, "_load_lookup_maps", lookup)
    monkeypatch.setattr(service, "bulk_upsert_resultados", save)
    return lookup, save


def row(**changes):
    return {"legajo": "001", "codigo_kpi": "BULTOS", "fecha": "2026-01-01", "valor": 125, **changes}


def test_resolves_sector_and_preserves_decimal(storage):
    result = service.guardar_resultados_kpi({"empresa_id": 1, "resultados": [row(valor="125.1234"), row(legajo="002")]})
    assert result == {"empresa_id": 1, "recibidos": 2, "guardados": 2}
    storage[0].assert_called_once_with(1)
    assert storage[1].call_args.args[0] == [
        (1, 10, 30, "2026-01-01", Decimal("125.1234")),
        (1, 11, 40, "2026-01-01", Decimal("125")),
    ]


@pytest.mark.parametrize("bad_row", [
    None, [], row(legajo=1), row(legajo="unknown"), row(legajo="003"),
    row(codigo_kpi="unknown"), row(codigo_kpi=[]), row(fecha="20260101"),
    row(fecha="2026-02-30"), row(fecha="0001-01-01"),
    row(fecha=(datetime.date.today() + datetime.timedelta(days=1)).isoformat()),
    row(valor=True), row(valor=None), row(valor="NaN"), row(valor="Infinity"),
    row(valor=10000000000), row(valor="0.00001"), row(valor="1,2"), row(valor=[]),
])
def test_rejects_entire_batch_before_writing(storage, bad_row):
    with pytest.raises(service.KpiBatchError) as exc:
        service.guardar_resultados_kpi({"empresa_id": 1, "resultados": [row(), bad_row]})
    assert exc.value.status == 422
    assert exc.value.errors[0]["fila"] == 2
    storage[1].assert_not_called()


@pytest.mark.parametrize("payload", [None, [], {}, {"empresa_id": True, "resultados": [row()]},
    {"empresa_id": "1", "resultados": [row()]}, {"empresa_id": 0, "resultados": [row()]},
    {"empresa_id": 1, "resultados": []}, {"empresa_id": 1, "resultados": [row()] * 1001}])
def test_invalid_envelope_does_not_query_database(storage, payload):
    with pytest.raises(service.KpiBatchError) as exc:
        service.guardar_resultados_kpi(payload)
    assert exc.value.status == 400
    storage[0].assert_not_called()
    storage[1].assert_not_called()


def test_rejects_duplicates_after_normalization(storage):
    with pytest.raises(service.KpiBatchError, match="Lote rechazado"):
        service.guardar_resultados_kpi({"empresa_id": 1, "resultados": [row(), row(codigo_kpi=" bultos ")]})
    storage[1].assert_not_called()


def test_repository_rolls_back_failed_batch(monkeypatch):
    db = Mock()
    db.cursor.return_value.executemany.side_effect = RuntimeError("write failed")
    monkeypatch.setattr(repository, "get_db", lambda: db)
    with pytest.raises(RuntimeError):
        repository.bulk_upsert_resultados([(1, 10, 30, "2026-01-01", Decimal("1"))])
    db.rollback.assert_called_once()
    db.commit.assert_not_called()
    db.close.assert_called_once()


def test_retries_update_only_requested_result(monkeypatch):
    import sqlite3
    connection = sqlite3.connect(":memory:")
    connection.execute("CREATE TABLE kpis_empleado_resultado (empresa_id INT, empleado_id INT, kpi_id INT, fecha TEXT, valor NUMERIC, UNIQUE(empleado_id,kpi_id,fecha))")

    class Cursor:
        def executemany(self, query, rows):
            query = query.replace("%s", "?").replace(
                "ON DUPLICATE KEY UPDATE valor = VALUES(valor)",
                "ON CONFLICT(empleado_id,kpi_id,fecha) DO UPDATE SET valor = excluded.valor")
            connection.executemany(query, [(*r[:4], str(r[4])) for r in rows])

        def close(self):
            pass

    db = Mock()
    db.cursor.return_value = Cursor()
    db.commit.side_effect = connection.commit
    db.rollback.side_effect = connection.rollback
    monkeypatch.setattr(repository, "get_db", lambda: db)
    try:
        other = (1, 10, 30, "2026-01-02", Decimal("99"))
        original = (1, 10, 30, "2026-01-01", Decimal("1"))
        corrected = (*original[:4], Decimal("2"))
        repository.bulk_upsert_resultados([original, other])
        repository.bulk_upsert_resultados([corrected])
        repository.bulk_upsert_resultados([corrected])
        assert connection.execute("SELECT fecha, valor FROM kpis_empleado_resultado ORDER BY fecha").fetchall() == [
            ("2026-01-01", 2), ("2026-01-02", 99)]
    finally:
        connection.close()
