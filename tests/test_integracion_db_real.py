import threading
import uuid
from concurrent.futures import ThreadPoolExecutor

import pytest

from extensions import get_db, init_db
from repositories.empleado_horario_repository import create_asignacion
from services.excepcion_service import create_excepcion
from services.horario_service import (
    create_horario_estructurado,
    delete_horario_estructurado,
)
from utils.asistencia import get_horario_esperado, validar_asistencia


def _db_enabled():
    return str(__import__("os").getenv("RUN_DB_INTEGRATION", "0")).strip() == "1"


pytestmark = pytest.mark.skipif(
    not _db_enabled(),
    reason="Set RUN_DB_INTEGRATION=1 to run real DB integration tests",
)


@pytest.fixture(scope="session", autouse=True)
def _init_engine():
    init_db()


def _get_any_empresa_id():
    db = get_db()
    cur = db.cursor()
    try:
        cur.execute("SELECT id FROM empresas ORDER BY id LIMIT 1")
        row = cur.fetchone()
        if row:
            return int(row[0])

        cur.execute(
            """
            INSERT INTO empresas (razon_social, activa)
            VALUES (%s, 1)
            """,
            (f"TEST_EMPRESA_{uuid.uuid4().hex[:8]}",),
        )
        db.commit()
        return int(cur.lastrowid)
    finally:
        cur.close()
        db.close()


@pytest.fixture()
def test_employee():
    empresa_id = _get_any_empresa_id()
    token = uuid.uuid4().hex[:10]
    legajo = f"TST-{token}"
    dni = f"99{token[:8]}"

    db = get_db()
    cur = db.cursor()
    try:
        cur.execute(
            """
            INSERT INTO empleados
                (empresa_id, legajo, dni, nombre, apellido, estado, activo)
            VALUES (%s, %s, %s, %s, %s, 'activo', 1)
            """,
            (empresa_id, legajo, dni, "Test", "Integracion"),
        )
        empleado_id = int(cur.lastrowid)
        db.commit()
    finally:
        cur.close()
        db.close()

    try:
        yield {"empleado_id": empleado_id, "empresa_id": empresa_id}
    finally:
        db = get_db()
        cur = db.cursor()
        try:
            cur.execute(
                "DELETE FROM asistencias WHERE empleado_id = %s",
                (empleado_id,),
            )
            cur.execute(
                "DELETE FROM excepcion_bloques WHERE excepcion_id IN (SELECT id FROM empleado_excepciones WHERE empleado_id = %s)",
                (empleado_id,),
            )
            cur.execute(
                "DELETE FROM empleado_excepciones WHERE empleado_id = %s",
                (empleado_id,),
            )
            cur.execute(
                "DELETE FROM empleado_horarios WHERE empleado_id = %s",
                (empleado_id,),
            )
            cur.execute(
                "DELETE FROM empleados WHERE id = %s",
                (empleado_id,),
            )
            db.commit()
        finally:
            cur.close()
            db.close()


def _create_test_horario(empresa_id, nombre_suffix):
    payload = {
        "empresa_id": empresa_id,
        "nombre": f"Horario Test {nombre_suffix}",
        "tolerancia_min": 5,
        "descripcion": "Integracion DB real",
        "activo": True,
        "dias": [
            {
                "dia_semana": 1,
                "bloques": [
                    {"entrada": "08:00", "salida": "12:00"},
                    {"entrada": "13:00", "salida": "17:00"},
                ],
            },
            {
                "dia_semana": 2,
                "bloques": [
                    {"entrada": "08:00", "salida": "16:00"},
                ],
            },
        ],
    }
    return create_horario_estructurado(payload)


def _cleanup_horario(horario_id):
    db = get_db()
    cur = db.cursor()
    try:
        cur.execute("DELETE FROM empleado_horarios WHERE horario_id = %s", (horario_id,))
        db.commit()
    finally:
        cur.close()
        db.close()
    delete_horario_estructurado(horario_id)


def test_db_real_asignacion_rechaza_solapamiento(test_employee):
    empresa_id = test_employee["empresa_id"]
    empleado_id = test_employee["empleado_id"]
    horario_1 = _create_test_horario(empresa_id, "A")
    horario_2 = _create_test_horario(empresa_id, "B")

    try:
        create_asignacion(empleado_id, horario_1, "2026-02-01", "2026-02-28", empresa_id)
        with pytest.raises(ValueError, match="superpone"):
            create_asignacion(empleado_id, horario_2, "2026-02-15", "2026-03-15", empresa_id)
    finally:
        _cleanup_horario(horario_1)
        _cleanup_horario(horario_2)


def test_db_real_asignacion_concurrencia_mismo_rango(test_employee):
    empresa_id = test_employee["empresa_id"]
    empleado_id = test_employee["empleado_id"]
    horario_id = _create_test_horario(empresa_id, "CONC")
    barrier = threading.Barrier(2)

    def worker():
        try:
            barrier.wait(timeout=5)
            asignacion_id = create_asignacion(
                empleado_id,
                horario_id,
                "2026-03-01",
                "2026-03-31",
                empresa_id,
            )
            return ("ok", asignacion_id)
        except Exception as exc:  # noqa: BLE001
            return ("error", str(exc))

    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            f1 = pool.submit(worker)
            f2 = pool.submit(worker)
            r1 = f1.result(timeout=20)
            r2 = f2.result(timeout=20)

        outcomes = [r1, r2]
        oks = [r for r in outcomes if r[0] == "ok"]
        errs = [r for r in outcomes if r[0] == "error"]

        assert len(oks) == 1
        assert len(errs) == 1
        assert "superpone" in errs[0][1]
    finally:
        _cleanup_horario(horario_id)


def test_db_real_excepcion_cambio_y_franco_en_horario_esperado(test_employee):
    empresa_id = test_employee["empresa_id"]
    empleado_id = test_employee["empleado_id"]
    horario_id = _create_test_horario(empresa_id, "EXC")

    try:
        create_asignacion(empleado_id, horario_id, "2026-02-01", None, empresa_id)

        exc1_id = create_excepcion(
            {
                "empresa_id": empresa_id,
                "empleado_id": empleado_id,
                "fecha": "2026-02-16",
                "tipo": "CAMBIO_HORARIO",
                "descripcion": "Cambio puntual",
                "anula_horario": False,
            },
            [{"entrada": "10:00", "salida": "18:00"}],
        )
        assert exc1_id > 0

        esperado_cambio = get_horario_esperado(empleado_id, "2026-02-16")
        assert esperado_cambio is not None
        assert esperado_cambio["tiene_excepcion"] is True
        assert esperado_cambio["tipo_excepcion"] == "CAMBIO_HORARIO"
        assert esperado_cambio["anula_horario"] is False
        assert esperado_cambio["bloques"] == [{"entrada": "10:00", "salida": "18:00"}]

        exc2_id = create_excepcion(
            {
                "empresa_id": empresa_id,
                "empleado_id": empleado_id,
                "fecha": "2026-02-17",
                "tipo": "FRANCO",
                "descripcion": "Franco",
                "anula_horario": True,
            },
            [],
        )
        assert exc2_id > 0

        esperado_franco = get_horario_esperado(empleado_id, "2026-02-17")
        assert esperado_franco is not None
        assert esperado_franco["tiene_excepcion"] is True
        assert esperado_franco["anula_horario"] is True
        assert esperado_franco["bloques"] == []
        assert esperado_franco["tolerancia"] == 0
    finally:
        _cleanup_horario(horario_id)


def test_db_real_validar_asistencia_con_tolerancia(test_employee):
    empresa_id = test_employee["empresa_id"]
    empleado_id = test_employee["empleado_id"]
    horario_id = _create_test_horario(empresa_id, "ASIS")

    try:
        create_asignacion(empleado_id, horario_id, "2026-02-01", None, empresa_id)

        errors_ok, estado_ok = validar_asistencia(empleado_id, "2026-02-17", "08:03", "16:00")
        assert errors_ok == []
        assert estado_ok == "ok"

        errors_tarde, estado_tarde = validar_asistencia(empleado_id, "2026-02-17", "08:06", "16:00")
        assert errors_tarde == []
        assert estado_tarde == "tarde"

        errors_out, estado_out = validar_asistencia(empleado_id, "2026-02-17", "07:30", "16:00")
        assert "Hora de entrada fuera de bloques esperados." in errors_out
        assert estado_out is None
    finally:
        _cleanup_horario(horario_id)
