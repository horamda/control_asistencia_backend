"""Egreso automatico por olvido de fichada."""
import datetime as dt

import pytest

from services import egreso_automatico_service as svc
from tests.test_seguridad import database  # noqa: F401  (fixture de base aislada)


# --- Calculo de la hora de egreso ---------------------------------------------------

def test_egreso_uses_end_of_scheduled_block():
    assert svc.calcular_egreso("07:58:00", [{"entrada": "08:00", "salida": "16:00"}], 8) == ("16:00:00", "horario")


def test_split_shift_closes_the_block_that_contains_the_entry():
    bloques = [{"entrada": "14:00", "salida": "18:00"}, {"entrada": "08:00", "salida": "12:00"}]
    assert svc.calcular_egreso("08:05", bloques, 8) == ("12:00:00", "horario")
    assert svc.calcular_egreso("13:50", bloques, 8) == ("18:00:00", "horario")


def test_without_schedule_or_after_it_adds_parameter_hours():
    assert svc.calcular_egreso("07:00", [], 8) == ("15:00:00", "parametro")
    assert svc.calcular_egreso("19:00", [{"entrada": "08:00", "salida": "16:00"}], 7.5) == ("23:59:00", "parametro")
    assert svc.calcular_egreso(dt.timedelta(hours=9, minutes=30), None, 6.25) == ("15:45:00", "parametro")


def test_egreso_never_crosses_midnight():
    assert svc.calcular_egreso("22:00", [], 8) == ("23:59:00", "parametro")
    assert svc.calcular_egreso("23:59", [], 8) == ("23:59:00", "parametro")


# --- Cierre de jornadas (base real, corre en CI) -----------------------------------

@pytest.fixture
def jornadas(database, monkeypatch):  # noqa: F811
    connect = database
    conn = connect()
    c = conn.cursor()
    for sql in [
        "CREATE TABLE configuracion_empresa (empresa_id INT PRIMARY KEY, egreso_automatico_activo TINYINT NOT NULL DEFAULT 1,"
        " egreso_automatico_horas DECIMAL(4,2) NOT NULL DEFAULT 8)",
        "CREATE TABLE asistencias (id INT AUTO_INCREMENT PRIMARY KEY, empresa_id INT, empleado_id INT, fecha DATE,"
        " hora_entrada TIME NULL, hora_salida TIME NULL, metodo_entrada ENUM('qr','manual','facial') NULL,"
        " metodo_salida ENUM('qr','manual','facial') NULL,"
        " estado VARCHAR(30), observaciones TEXT NULL)",
        "CREATE TABLE asistencia_marcas (id BIGINT AUTO_INCREMENT PRIMARY KEY, empresa_id INT, empleado_id INT,"
        " asistencia_id INT NULL, fecha DATE, hora TIME, accion VARCHAR(10), metodo VARCHAR(20), tipo_marca VARCHAR(20),"
        " lat DECIMAL(10,7) NULL, lon DECIMAL(10,7) NULL, foto TEXT NULL, gps_ok TINYINT NULL, gps_distancia_m DECIMAL(10,2) NULL,"
        " gps_tolerancia_m DECIMAL(10,2) NULL, gps_ref_lat DECIMAL(10,7) NULL, gps_ref_lon DECIMAL(10,7) NULL,"
        " estado VARCHAR(30) NULL, observaciones TEXT NULL)",
        "INSERT INTO configuracion_empresa VALUES (1, 1, 7.5), (2, 0, 8)",
        # 1) empleado 10 con horario, ayer abierta; 2) sin horario; 3) hoy abierta; 4) empresa desactivada;
        # 5) cerrada por el empleado; 6) abierta sin marcas (cargada a mano)
        "INSERT INTO asistencias (id,empresa_id,empleado_id,fecha,hora_entrada,hora_salida,metodo_entrada,metodo_salida,estado) VALUES"
        " (1,1,10,'2026-10-13','08:02',NULL,'qr',NULL,'ok'),"
        " (2,1,11,'2026-10-13','09:00',NULL,'qr',NULL,'ok'),"
        " (3,1,10,'2026-10-14','08:00',NULL,'qr',NULL,'ok'),"
        " (4,2,20,'2026-10-13','08:00',NULL,'qr',NULL,'ok'),"
        " (5,1,11,'2026-10-12','09:00','17:00','qr','qr','ok'),"
        " (6,1,12,'2026-10-13','10:00',NULL,'manual',NULL,'ok')",
        "INSERT INTO asistencia_marcas (empresa_id,empleado_id,asistencia_id,fecha,hora,accion,metodo,tipo_marca) VALUES"
        " (1,10,1,'2026-10-13','08:02','ingreso','qr','jornada'), (1,11,2,'2026-10-13','09:00','ingreso','qr','jornada')",
    ]:
        c.execute(sql)
    # Igual que en produccion: metodo_salida es ENUM y la migracion agrega 'automatico'.
    from scripts.migrate_20261015_03_egreso_automatico import migrate_metodo_salida
    migrate_metodo_salida(c)
    migrate_metodo_salida(c)  # idempotente
    conn.commit()
    c.close()
    conn.close()
    monkeypatch.setattr(svc, "get_db", connect)
    horarios = {10: {"bloques": [{"entrada": "08:00", "salida": "16:00"}]}}
    monkeypatch.setattr(svc, "get_horario_esperado", lambda eid, fecha: horarios.get(eid))
    return connect


def _rows(connect, sql):
    conn = connect()
    c = conn.cursor(dictionary=True)
    c.execute(sql)
    rows = c.fetchall()
    c.close()
    conn.close()
    return rows


def test_cierra_solo_dias_anteriores_y_marca_automaticas(jornadas):
    resumen = svc.cerrar_jornadas_abiertas(hoy=dt.date(2026, 10, 14))

    assert resumen["cerradas"] == 3 and resumen["por_horario"] == 1 and resumen["por_parametro"] == 2
    assert resumen["empresa_desactivada"] == 1
    filas = {r["id"]: r for r in _rows(jornadas, "SELECT id, hora_salida, metodo_salida, observaciones FROM asistencias")}
    assert str(filas[1]["hora_salida"]) == "16:00:00" and filas[1]["metodo_salida"] == "automatico"  # horario
    assert str(filas[2]["hora_salida"]) == "16:30:00"  # 09:00 + 7,5 h (parametro de la empresa)
    assert filas[3]["hora_salida"] is None  # hoy: todavia puede fichar
    assert filas[4]["hora_salida"] is None  # empresa con el proceso desactivado
    assert "olvido de fichada" in filas[2]["observaciones"]

    marcas = _rows(jornadas, "SELECT asistencia_id, hora, metodo FROM asistencia_marcas WHERE accion='egreso' ORDER BY asistencia_id")
    # La jornada 6 no tenia marcas: se cierra el resumen sin agregar una marca suelta.
    assert [(m["asistencia_id"], str(m["hora"]), m["metodo"]) for m in marcas] == [
        (1, "16:00:00", "automatico"), (2, "16:30:00", "automatico")]

    # Idempotente: una segunda corrida no toca nada.
    assert svc.cerrar_jornadas_abiertas(hoy=dt.date(2026, 10, 14))["cerradas"] == 0


def test_simulacion_no_escribe(jornadas):
    resumen = svc.cerrar_jornadas_abiertas(hoy=dt.date(2026, 10, 14), dry_run=True)
    assert resumen["cerradas"] == 3
    assert _rows(jornadas, "SELECT COUNT(*) n FROM asistencias WHERE metodo_salida='automatico'")[0]["n"] == 0


def test_efectividad_cuenta_olvidos_como_error(jornadas):
    svc.cerrar_jornadas_abiertas(hoy=dt.date(2026, 10, 14))
    efectividad = svc.efectividad_por_empleado([10, 11], "2026-10-01", "2026-10-31")
    assert efectividad[11] == {"jornadas": 2, "olvidos": 1, "efectividad_pct": 50.0}
    assert efectividad[10] == {"jornadas": 1, "olvidos": 1, "efectividad_pct": 0.0}  # la de hoy sigue abierta
    assert svc.efectividad_empleado(99, "2026-10-01", "2026-10-31")["efectividad_pct"] is None



@pytest.mark.parametrize("raw,expected", [("", 8), ("7,5", 7.5), ("9", 9.0)])
def test_parametro_horas_en_configuracion(raw, expected):
    from web.configuracion.configuracion_empresa_routes import _parse_horas_egreso
    assert _parse_horas_egreso(raw) == expected


@pytest.mark.parametrize("raw", ["0", "17", "ocho"])
def test_parametro_horas_rechaza_valores_invalidos(raw):
    from web.configuracion.configuracion_empresa_routes import _parse_horas_egreso
    with pytest.raises(ValueError):
        _parse_horas_egreso(raw)
