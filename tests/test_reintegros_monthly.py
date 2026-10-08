"""Monthly close, tenant scope, duplicates, reminders and optional odometer."""

from datetime import datetime, date
from decimal import Decimal
from uuid import uuid4
from concurrent.futures import ThreadPoolExecutor
import pytest
from werkzeug.datastructures import MultiDict
from tests.test_reintegros import (
    database,
    schema,
    client,
    employee,
    photo,
    payload,
    photos,
    OWNER,
    HR,
    BOSS,
    resolve,
)
from services import reintegro_service as s
from services import reintegro_monthly_service as m


def clock(monkeypatch, year, month, day):
    monkeypatch.setattr(s, "now_local", lambda: datetime(year, month, day, 23, 59))
    monkeypatch.setattr(m, "now_local", lambda: datetime(year, month, day, 23, 59))


def test_same_amount_different_receipts_month_unique_and_optional_km():
    data = payload(kilometros="240")
    for i, g in enumerate(data["gastos"]):
        g.update(importe="5000.00", numero_comprobante=str(100 + i), emisor="Peaje")
    rid, _ = s.store(employee(), data, photos())
    row = s.detail(OWNER, rid)
    assert row["total_solicitado"] == Decimal("10000.00") and row["kilometros"] == 240
    assert row["foto_odometro_id"] is None and row["advertencias"] == []
    assert {g["numero_comprobante"] for g in row["gastos"]} == {"100", "101"}
    with pytest.raises(s.Error) as error:
        s.store(employee(), payload(), photos())
    assert error.value.status == 409
    s.transition(OWNER, rid, dict(accion="cancelar", revision=1))
    with pytest.raises(s.Error):
        s.store(employee(), payload(), photos())


def test_incomplete_draft_and_only_kilometers_can_be_approved():
    rid, _ = s.store(employee(), payload(accion="borrador", gastos=[{}]), MultiDict())
    row = s.detail(OWNER, rid)
    assert row["gastos"][0]["importe"] is None and row["total_solicitado"] == 0
    with pytest.raises(s.Error):
        s.store(employee(), payload(gastos=[{}], revision=1), MultiDict(), rid)
    s.store(employee(), payload(gastos=[], kilometros=0, revision=1), MultiDict(), rid)
    resolve(rid, HR, revision=2)
    row = s.detail(OWNER, rid)
    assert (
        row["estado"] == "aprobada"
        and row["total_aprobado"] == 0
        and row["kilometros"] == 0
    )


def test_close_inclusive_reopen_expiry_and_admin_override(monkeypatch):
    clock(monkeypatch, 2026, 10, 15)
    rid, _ = s.store(employee(), payload(accion="borrador", gastos=[]), MultiDict())
    clock(monkeypatch, 2026, 10, 16)
    assert not s.detail(OWNER, rid)["puede_editar_empleado"]
    with pytest.raises(s.Error):
        s.store(employee(), payload(revision=1, gastos=[]), MultiDict(), rid)
    manager = dict(HR, manage_edit=True)
    s.transition(
        manager,
        rid,
        dict(
            accion="reabrir",
            revision=1,
            reabierto_hasta="2026-10-18",
            motivo="Corrección autorizada",
        ),
    )
    assert s.detail(OWNER, rid)["puede_editar_empleado"]
    clock(monkeypatch, 2026, 10, 19)
    with pytest.raises(s.Error):
        s.store(employee(), payload(revision=2, gastos=[]), MultiDict(), rid)
    s.store(
        employee(), payload(revision=2, gastos=[]), MultiDict(), rid, web_actor=manager
    )
    assert s.detail(OWNER, rid)["estado"] == "pendiente"
    assert s.detail(OWNER, rid)["reabierto_hasta"] is None
    assert m.deadline(date(2025, 12, 1)) == date(2026, 1, 15)
    assert m.deadline(date(2024, 2, 1)) == date(2024, 3, 15)


def test_sector_revocation_preserves_history_and_config_revision():
    rid, _ = s.store(employee(), payload(accion="borrador"), MultiDict())
    m.save_settings(1, 99, [], 0)
    assert not m.configuration(employee())["habilitado"]
    assert s.detail(OWNER, rid)["id"] == rid
    with pytest.raises(s.Error):
        s.store(employee(), payload(revision=1), photos(), rid)
    with pytest.raises(s.Error):
        m.save_settings(1, 99, [1], 0)
    m.save_settings(1, 99, [1], 1)
    assert m.configuration(employee())["habilitado"]
    with s.db.transaction() as c:
        c.execute("UPDATE sectores SET activo=0 WHERE id=1")
    assert not m.configuration(employee())["habilitado"]
    # Existing monthly history remains visible; no missing rows for inactive sectors.
    assert [r["empleado_id"] for r in m.report(HR, "2026-09")["items"]] == [10]
    with s.db.transaction() as c:
        c.execute(
            "INSERT INTO sectores(id,nombre,empresa_id,activo) VALUES(2,'Ajeno',2,1)"
        )
    with pytest.raises(s.Error):
        m.save_settings(1, 99, [2], 2)


def test_odometer_private_retention_replacement_and_removal(client):
    rid, _ = s.store(
        employee(),
        payload(gastos=[], accion="borrador", kilometros=120),
        MultiDict([("odometro", photo())]),
    )
    fid = s.detail(OWNER, rid)["foto_odometro_id"]
    assert s.odometer_photo(OWNER, fid)["contenido"]
    with pytest.raises(s.Error):
        s.odometer_photo(dict(OWNER, empleado_id=13), fid)
    s.store(
        employee(), payload(gastos=[], revision=1, kilometros=121), MultiDict(), rid
    )
    assert s.detail(OWNER, rid)["foto_odometro_id"] == fid
    s.transition(HR, rid, dict(accion="devolver", revision=2, motivo="Corregir"))
    s.store(
        employee(),
        payload(gastos=[], revision=3, quitar_odometro="1"),
        MultiDict(),
        rid,
    )
    assert s.detail(OWNER, rid)["foto_odometro_id"] is None
    with pytest.raises(s.Error):
        s.odometer_photo(OWNER, fid)
    assert (
        client.get(
            "/api/v1/mobile/reintegros/config", headers={"Authorization": "Bearer 10"}
        ).json["mensual"]["foto_odometro_obligatoria"]
        is False
    )


def test_report_includes_missing_draft_and_export(client):
    s.store(
        employee(), payload(gastos=[], accion="borrador", kilometros=20), MultiDict()
    )
    report = m.report(HR, "2026-09")
    rows = {r["empleado_id"]: r for r in report["items"]}
    assert rows[10]["estado"] == "borrador" and rows[11]["estado"] is None
    assert 20 not in rows
    for url in [
        "/reintegros/mensual?periodo=2026-09",
        "/reintegros/mensual.csv?periodo=2026-09",
        "/reintegros/configuracion",
    ]:
        response = client.get(url)
        assert response.status_code == 200, response.data[:500]
    assert "Sin cargar" in client.get("/reintegros/mensual?periodo=2026-09").get_data(
        as_text=True
    )


def test_reminder_fifth_once_per_employee_and_privacy(monkeypatch, client):
    s.store(employee(), payload(), photos())  # already submitted: no reminder
    clock(monkeypatch, 2026, 10, 4)
    assert m.generate_reminders() == 0
    clock(monkeypatch, 2026, 10, 5)
    assert m.generate_reminders() == 3  # active peers in enabled sector
    assert m.generate_reminders() == 0
    assert m.reminders(employee()) == []
    rows = m.reminders(employee(11))
    assert len(rows) == 1
    with pytest.raises(s.Error):
        m.read_reminder(employee(10), rows[0]["id"])
    m.read_reminder(employee(11), rows[0]["id"])
    assert m.reminders(employee(11)) == []


def test_concurrent_different_keys_same_month_only_one():
    emp = employee()

    def send(_):
        try:
            return s.store(emp, payload(gastos=[], accion="borrador"), MultiDict())[0]
        except s.Error as exc:
            return str(exc.status)

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(send, [1, 2]))
    assert sum(isinstance(v, int) for v in results) == 1 and "409" in results


@pytest.mark.parametrize(
    "changes",
    [
        {"kilometros": -1},
        {"kilometros": 1.5},
        {"kilometros": True},
        {"periodo": "2026-13"},
        {"periodo": "2027-01"},
    ],
)
def test_invalid_month_or_kilometers(changes):
    with pytest.raises(s.Error):
        s.store(employee(), payload(**changes), photos())


def test_migration_idempotent_and_legacy_not_assigned():
    from scripts.migrate_20261008_01_reintegros_mensuales import migrate_cursor

    with s.db.transaction() as c:
        migrate_cursor(c)
        assert s.db.one(c, "SELECT COUNT(*) n FROM reintegro_solicitudes")["n"] == 0


def test_mobile_retains_receipts_and_reports_possible_duplicate(client):
    data = payload(accion="borrador")
    for g in data["gastos"]:
        g.update(emisor="Comercio", numero_comprobante="0001-123")
    rid, _ = s.store(employee(), data, photos())
    row = s.detail(OWNER, rid)
    assert len(row["advertencias"]) == 2
    data["revision"] = 1
    data["accion"] = "enviar"
    for item, g in zip(data["gastos"], row["gastos"]):
        item["fotos_existentes"] = [g["fotos"][0]["id"]]
    response = client.put(
        f"/api/v1/mobile/reintegros/solicitudes/{rid}",
        json=data,
        headers={"Authorization": "Bearer 10"},
    )
    assert response.status_code == 200, response.json
    assert (
        response.json["periodo"] == "2026-09" and response.json["estado"] == "pendiente"
    )


def test_employee_cannot_reopen_and_admin_cannot_reopen_paid():
    rid, _ = s.store(employee(), payload(accion="borrador", gastos=[]), MultiDict())
    with pytest.raises(s.Error):
        s.transition(
            OWNER,
            rid,
            dict(
                accion="reabrir", revision=1, motivo="x", reabierto_hasta="2026-10-20"
            ),
        )

    s.store(employee(), payload(revision=1), photos(), rid)
    resolve(rid, HR, revision=2)
    with pytest.raises(s.Error):
        s.transition(
            dict(HR, manage_edit=True),
            rid,
            dict(
                accion="reabrir", revision=3, motivo="x", reabierto_hasta="2026-10-20"
            ),
        )


def test_reopening_retains_return_reason(monkeypatch):
    rid, _ = s.store(employee(), payload(), photos())
    s.transition(
        HR,
        rid,
        dict(accion="devolver", revision=1, motivo="Corregir el comprobante ilegible"),
    )
    clock(monkeypatch, 2026, 10, 16)
    s.transition(
        dict(HR, manage_edit=True),
        rid,
        dict(
            accion="reabrir",
            revision=2,
            motivo="Plazo excepcional",
            reabierto_hasta="2026-10-20",
        ),
    )
    row = s.detail(HR, rid)
    assert row["motivo"] == "Corregir el comprobante ilegible"
    assert "Plazo excepcional" in row["auditoria"][-1]["datos"]
