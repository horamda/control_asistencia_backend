"""Aviso de ingreso sin fichar: al empleado y a su jefe, una vez por dia, con las excepciones del dia.

MySQL real (SH_TEST_DB_PORT). El martes 14/10/2026 (fixture base): 10, 11, 12, 13 tienen la app; 14 no. Todos con
horario L-V 08-12 y 13-17. El 12 esta de vacaciones (fixture de reuniones)."""
import datetime as dt
import json

import pytest

from services import avisos_push as avisos
from tests.test_avisos_comunicados import HOY, _avisos, _sql, base  # noqa: F401  (fixture)
from tests.test_push import _envios, clave_rsa, firebase, push_db  # noqa: F401  (fixtures)
from tests.test_reuniones import reuniones_db  # noqa: F401
from tests.test_seguridad import database  # noqa: F401

TABLAS = [
    "ALTER TABLE empleados ADD COLUMN fecha_ingreso DATE NULL",
    "ALTER TABLE empleados ADD COLUMN reporta_a_empleado_id INT NULL",
    "UPDATE empleados SET reporta_a_empleado_id = 11 WHERE id IN (10, 14)",
    "CREATE TABLE asistencia_marcas (id BIGINT AUTO_INCREMENT PRIMARY KEY, empresa_id INT, empleado_id INT, fecha DATE,"
    " hora TIME, accion VARCHAR(10))",
    "CREATE TABLE justificaciones (id INT AUTO_INCREMENT PRIMARY KEY, empleado_id INT, fecha DATE, fecha_desde DATE NULL,"
    " fecha_hasta DATE NULL, estado VARCHAR(20))",
    "CREATE TABLE horarios (id INT AUTO_INCREMENT PRIMARY KEY, empresa_id INT, nombre VARCHAR(80), tolerancia_min INT DEFAULT 0)",
    "CREATE TABLE horario_dias (id INT AUTO_INCREMENT PRIMARY KEY, horario_id INT, dia_semana INT)",
    "CREATE TABLE horario_dia_bloques (id INT AUTO_INCREMENT PRIMARY KEY, empresa_id INT, horario_dia_id INT, orden INT,"
    " hora_entrada TIME, hora_salida TIME)",
    "CREATE TABLE empleado_horarios (id INT AUTO_INCREMENT PRIMARY KEY, empresa_id INT, empleado_id INT, horario_id INT,"
    " fecha_desde DATE, fecha_hasta DATE NULL)",
    "CREATE TABLE empleado_excepciones (id INT AUTO_INCREMENT PRIMARY KEY, empresa_id INT, empleado_id INT, fecha DATE,"
    " tipo VARCHAR(30), descripcion VARCHAR(200) NULL, anula_horario TINYINT DEFAULT 0)",
    "CREATE TABLE excepcion_bloques (id INT AUTO_INCREMENT PRIMARY KEY, empresa_id INT, excepcion_id INT, orden INT,"
    " hora_entrada TIME, hora_salida TIME)",
    "INSERT INTO horarios (id, empresa_id, nombre) VALUES (1, 1, 'Administrativo')",
]


@pytest.fixture
def ingreso(base):  # noqa: F811
    for sql in TABLAS:
        _sql(sql)
    for dia in range(1, 6):
        dia_id = _sql("INSERT INTO horario_dias (horario_id, dia_semana) VALUES (1, %s)", (dia,))
        _sql("INSERT INTO horario_dia_bloques (empresa_id, horario_dia_id, orden, hora_entrada, hora_salida) VALUES"
             " (1, %s, 1, '08:00', '12:00'), (1, %s, 2, '13:00', '17:00')", (dia_id, dia_id))
    for eid in (10, 11, 12, 13, 14):
        _sql("INSERT INTO empleado_horarios (empresa_id, empleado_id, horario_id, fecha_desde) VALUES (1, %s, 1, '2026-01-01')", (eid,))
    _sql("INSERT INTO asistencia_marcas (empresa_id, empleado_id, fecha, hora, accion) VALUES (1, 11, %s, '08:05', 'ingreso')", (HOY,))
    _sql("INSERT INTO justificaciones (empleado_id, fecha, estado) VALUES (13, %s, 'aprobada')", (HOY,))
    return base


def _a(hora, minuto):
    return dt.datetime.combine(HOY, dt.time(hora, minuto))


def test_ingreso_sin_fichar_avisa_al_empleado_y_al_jefe_una_vez(ingreso):
    assert avisos.ingresos_pendientes(_a(8, 14)) == 0  # 08:00 + 15 min todavia no
    assert avisos.ingresos_pendientes(_a(8, 15)) == 3
    assert avisos.ingresos_pendientes(_a(8, 40)) == 0  # no repite
    empleado = _avisos("ingreso_pendiente")
    assert [e["empleado_id"] for e in empleado] == [10]  # 11 ficho, 12 vacaciones, 13 justificado, 14 sin la app
    assert empleado[0]["titulo"] == "¿Te olvidaste de fichar el ingreso?"
    assert empleado[0]["cuerpo"].startswith("Tu ingreso de hoy era a las 08:00 y todavía no lo registraste.")
    assert json.loads(empleado[0]["datos"]) == {"fecha": "2026-10-14", "empleado_id": "10", "ruta": "/asistencia"}
    jefe = _avisos("ingreso_equipo")
    assert [(e["empleado_id"], e["cuerpo"]) for e in jefe] == [
        (11, "Perez Ana no fichó el ingreso de las 08:00."),
        (11, "Convocado No no fichó el ingreso de las 08:00."),  # el 14 no tiene la app, su jefe si
    ]


def test_ingreso_sin_fichar_no_avisa_con_feriado_excepcion_ni_terminado_el_horario(ingreso):
    _sql("INSERT INTO empleado_excepciones (empresa_id, empleado_id, fecha, tipo, anula_horario) VALUES (1, 10, %s, 'FRANCO', 1)", (HOY,))
    assert avisos.ingresos_pendientes(_a(9, 0)) == 1  # solo el jefe, por el 14
    assert avisos.ingresos_pendientes(_a(17, 0)) == 0  # terminado el horario
    _sql("INSERT INTO asistencia_dias_no_laborables (empresa_id, sucursal_id, sector_id, fecha, motivo) VALUES (0, 0, 0, %s, 'Feriado')",
         (HOY + dt.timedelta(days=1),))
    assert avisos.ingresos_pendientes(dt.datetime.combine(HOY + dt.timedelta(days=1), dt.time(9, 0))) == 0
