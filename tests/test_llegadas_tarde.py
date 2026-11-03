"""Reporte de llegadas tarde: atraso por tramo contra el horario, filtros, agrupaciones y Excel."""
import datetime as dt
import io

import pytest
from openpyxl import load_workbook

from services import llegadas_tarde_service as tarde
from services import seguridad_service as s
from tests.test_seguridad import database  # noqa: F401

D = dt.date


def horario(empleado_id, fecha):
    # Turno partido 08-12 y 14-18 con 10 min de tolerancia; el 12 no tiene horario el 05/10.
    if empleado_id == 12 and fecha == "2026-10-05":
        return {"bloques": [], "tolerancia": 0}
    return {"bloques": [{"entrada": "08:00", "salida": "12:00"}, {"entrada": "14:00", "salida": "18:00"}],
            "tolerancia": 10}


@pytest.fixture
def base(database):  # noqa: F811
    conn = database()
    c = conn.cursor()
    c.execute("""CREATE TABLE asistencias (id INT AUTO_INCREMENT PRIMARY KEY, empresa_id INT, empleado_id INT, fecha DATE,
                 hora_entrada TIME NULL, hora_salida TIME NULL, estado VARCHAR(30))""")
    filas = [
        (10, "2026-10-05", "08:25", "12:00", "tarde"),             # 25 min
        (10, "2026-10-05", "14:12", "18:00", "tarde"),             # vuelta del almuerzo: 12 min
        (10, "2026-10-06", "08:08", "18:00", "ok"),                # dentro de la tolerancia
        (11, "2026-10-06", "08:40", "16:00", "salida_anticipada"),  # tarde y se fue antes: 40 min
        (12, "2026-10-05", "09:00", "17:00", "tarde"),             # sin horario ese dia: no cuenta
        (12, "2026-10-07", "08:15", "18:00", "tarde"),             # sucursal 2: 15 min
        (11, "2026-11-02", "09:00", "18:00", "tarde"),             # fuera del periodo
    ]
    for eid, fecha, entrada, salida, estado in filas:
        c.execute("INSERT INTO asistencias (empresa_id, empleado_id, fecha, hora_entrada, hora_salida, estado)"
                  " VALUES (1, %s, %s, %s, %s, %s)", (eid, fecha, entrada, salida, estado))
    conn.commit()
    c.close()
    conn.close()


def _reporte(**kw):
    return tarde.reporte(desde=D(2026, 10, 1), hasta=D(2026, 10, 31), horario=horario, **kw)


def test_atraso_por_tramo_y_resumen(base):
    datos = _reporte()
    assert [(d["empleado_id"], d["entrada"], d["atraso"]) for d in datos["detalle"]] == [
        (10, "08:25", 25), (10, "14:12", 12), (11, "08:40", 40), (12, "08:15", 15)]
    assert datos["totales"] == dict(veces=4, personas=3, minutos=92, promedio=23, empleados_con_asistencia=3)
    ana = datos["ranking"][0]
    assert (ana["empleado_id"], ana["veces"], ana["dias"], ana["dias_trabajados"], ana["pct"], ana["minutos"],
            ana["promedio"], ana["maximo"]) == (10, 2, 1, 2, 50, 37, 18, 25)
    assert datos["por_sucursal"] == [{"nombre": "Central", "veces": 3, "personas": 2, "minutos": 77},
                                     {"nombre": "Otra", "veces": 1, "personas": 1, "minutos": 15}]
    assert datos["por_sector"][0]["nombre"] == "Entrega"


def test_filtros(base):
    assert _reporte(sucursal_id=2)["totales"]["veces"] == 1
    assert _reporte(sector_id=99)["totales"]["veces"] == 0
    assert [d["empleado_id"] for d in _reporte(q="0011")["detalle"]] == [11]  # legajo
    assert [d["empleado_id"] for d in _reporte(q="perez")["detalle"]] == [10, 10]  # apellido
    assert _reporte(empresa_id=2)["totales"]["veces"] == 0
    with pytest.raises(ValueError, match="un año"):
        tarde.reporte(desde=D(2025, 1, 1), hasta=D(2026, 10, 31), horario=horario)


def test_excel(base):
    libro = load_workbook(io.BytesIO(tarde.excel(_reporte())))
    assert libro.sheetnames == ["Por persona", "Por sector", "Por sucursal", "Detalle"]
    persona = libro["Por persona"]
    assert persona["A1"].value == "Llegadas tarde del 01/10/2026 al 31/10/2026"
    assert [c.value for c in persona[4]][:5] == ["0010", "Perez Ana", "Entrega", "Central", 2]
    assert libro["Detalle"].max_row == 3 + 4


def test_usa_el_mismo_acceso_a_datos(base):
    assert tarde.db is s.db  # misma conexion parcheada por el fixture
