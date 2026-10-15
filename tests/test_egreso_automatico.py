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


# --- Historial de ejecuciones y consultas del panel (base real) -------------------

@pytest.fixture
def panel(jornadas):
    conn = jornadas()
    c = conn.cursor()
    from scripts.migrate_20261015_03_egreso_automatico import migrate_ejecuciones
    migrate_ejecuciones(c)
    migrate_ejecuciones(c)  # idempotente
    c.execute("ALTER TABLE empleados ADD COLUMN dni VARCHAR(20) NULL")
    c.execute("CREATE TABLE usuarios (id INT PRIMARY KEY, usuario VARCHAR(80))")
    c.execute("INSERT INTO usuarios VALUES (5, 'rrhh.ana')")
    conn.commit()
    c.close()
    conn.close()
    return jornadas


def test_ejecucion_manual_queda_en_historial_con_origen_y_usuario(panel, monkeypatch):
    monkeypatch.setattr(svc, "_ahora", lambda: dt.datetime(2026, 10, 14, 10, 0))
    assert svc.pendientes() == 4  # 1, 2, 4 y 6 (la 3 es de hoy)

    svc.cerrar_jornadas_abiertas(dry_run=True)
    assert svc.ejecuciones() == []  # la simulacion no queda registrada

    svc.cerrar_jornadas_abiertas(origen="manual", usuario_id=5)
    [ejecucion] = svc.ejecuciones()
    assert ejecucion["origen"] == "manual" and ejecucion["usuario_nombre"] == "rrhh.ana"
    assert (ejecucion["revisadas"], ejecucion["cerradas"], ejecucion["por_horario"], ejecucion["por_parametro"],
            ejecucion["empresa_desactivada"], ejecucion["errores"]) == (4, 3, 1, 2, 1, 0)
    assert svc.pendientes() == 1  # queda la de la empresa desactivada

    rows, total = svc.cerradas_page(per_page=2)
    assert total == 3 and len(rows) == 2
    origenes = {r["empleado_id"]: r["origen"] for r in svc.cerradas_page()[0]}
    assert origenes == {10: "horario", 11: "parametro", 12: "parametro"}
    rows, total = svc.cerradas_page(q="Garcia", desde="2026-10-13", hasta="2026-10-13")
    assert total == 1 and rows[0]["apellido"] == "Garcia" and rows[0]["sector_nombre"] == "Entrega"
    assert svc.cerradas_page(desde="2026-10-14")[1] == 0


# --- Pantalla del panel ----------------------------------------------------------------

def _panel_client(monkeypatch, rol, llamadas=None, permisos=None):
    import app as app_module
    import web.asistencias.egresos_automaticos_routes as routes
    import web.auth.decorators as auth_decorators

    llamadas = llamadas if llamadas is not None else []
    resumen = {"revisadas": 2, "cerradas": 2, "por_horario": 1, "por_parametro": 1, "empresa_desactivada": 0,
               "errores": 0, "detalle": [{"asistencia_id": 1, "fecha": "2026-10-13", "entrada": "08:02:00",
                                          "egreso": "16:00:00", "origen": "horario"}]}
    monkeypatch.setattr(svc, "cerrar_jornadas_abiertas", lambda **kw: llamadas.append(kw) or resumen)
    monkeypatch.setattr(svc, "pendientes", lambda **kw: 2)
    monkeypatch.setattr(svc, "ejecuciones", lambda limite=15: [{
        "inicio": dt.datetime(2026, 10, 14, 3, 30), "origen": "nocturno", "usuario_nombre": None,
        "revisadas": 5, "cerradas": 5, "por_horario": 4, "por_parametro": 1, "errores": 0}])
    monkeypatch.setattr(svc, "cerradas_page", lambda **kw: ([{
        "fecha": dt.date(2026, 10, 13), "hora_entrada": dt.timedelta(hours=8, minutes=2),
        "hora_salida": dt.timedelta(hours=16), "empleado_id": 10, "apellido": "Perez", "nombre": "Ana",
        "legajo": "0010", "sector_nombre": "Entrega", "origen": "horario"}], 1))
    monkeypatch.setattr(routes, "get_configuraciones", lambda: [{
        "empresa_id": 1, "razon_social": "Empresa SA", "egreso_automatico_activo": 1, "egreso_automatico_horas": 7.5}])
    monkeypatch.setattr(routes, "log_audit", lambda *a, **kw: llamadas.append({"audit": a[1]}))
    monkeypatch.setattr(app_module, "init_db", lambda: None)
    monkeypatch.setattr(auth_decorators, "_cached_web_user", lambda uid: {"id": 5, "activo": 1, "rol": rol})
    monkeypatch.setattr(auth_decorators, "_cached_user_permissions", lambda uid: permisos or {})
    app = app_module.create_app()
    app.config["WTF_CSRF_ENABLED"] = False
    client = app.test_client()
    with client.session_transaction() as sess:
        sess["user_id"] = 5
    return client


def test_panel_respeta_permisos_de_asistencias(monkeypatch):
    sin_asistencias = {"empleados": {"ver": True}}
    assert _panel_client(monkeypatch, "supervisor", permisos=sin_asistencias).get(
        "/asistencias/egresos-automaticos/").status_code == 403
    solo_ver = _panel_client(monkeypatch, "supervisor", permisos={"asistencias": {"ver": True}})
    html = solo_ver.get("/asistencias/egresos-automaticos/").get_data(as_text=True)
    assert "Jornadas sin egreso" in html and "Cerrar ahora" not in html
    assert solo_ver.post("/asistencias/egresos-automaticos/ejecutar").status_code == 403

    response = _panel_client(monkeypatch, "rrhh").get("/asistencias/egresos-automaticos/?desde=no-es-fecha")
    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert "Jornadas sin egreso" in html and "Perez Ana" in html and "16:00" in html
    assert "Empresa SA" in html and "7.5 h" in html and "Nocturno" in html and "Cerrar ahora 2 jornadas" in html


def test_panel_sin_pendientes_explica_que_ya_esta_aplicado(monkeypatch):
    client = _panel_client(monkeypatch, "admin")
    monkeypatch.setattr(svc, "pendientes", lambda **kw: 0)
    html = client.get("/asistencias/egresos-automaticos/").get_data(as_text=True)
    assert "Cerrar ahora" not in html and "el cierre ya está aplicado" in html


def test_panel_simular_no_escribe_y_ejecutar_registra_manual(monkeypatch):
    llamadas = []
    client = _panel_client(monkeypatch, "admin", llamadas)

    html = client.post("/asistencias/egresos-automaticos/simular").get_data(as_text=True)
    assert llamadas == [{"dry_run": True}]
    assert "Resultado de la simulación" in html and "No se guardó ningún cambio" in html

    llamadas.clear()
    response = client.post("/asistencias/egresos-automaticos/ejecutar")
    assert response.status_code == 302 and response.headers["Location"].endswith("/asistencias/egresos-automaticos/")
    assert llamadas == [{"origen": "manual", "usuario_id": 5}, {"audit": "egreso_automatico_manual"}]


def test_recalcular_por_parametro_con_las_horas_actuales(jornadas):
    svc.cerrar_jornadas_abiertas(hoy=dt.date(2026, 10, 14))  # empresa 1: 7,5 h
    conn = jornadas()
    c = conn.cursor()
    c.execute("UPDATE configuracion_empresa SET egreso_automatico_horas = 6 WHERE empresa_id = 1")
    conn.commit()
    c.close()
    conn.close()

    simulado = svc.recalcular_por_parametro(dry_run=True)
    # Solo las cerradas por parametro (2 y 6); la 1 fue segun horario asignado.
    assert (simulado["revisadas"], simulado["cambiadas"]) == (2, 2)
    assert _rows(jornadas, "SELECT hora_salida FROM asistencias WHERE id = 2")[0]["hora_salida"] == dt.timedelta(hours=16, minutes=30)

    resultado = svc.recalcular_por_parametro()
    assert resultado["detalle"] == [(2, "16:30:00", "15:00:00"), (6, "17:30:00", "16:00:00")]
    filas = {r["id"]: r for r in _rows(jornadas, "SELECT id, hora_salida, observaciones FROM asistencias")}
    assert str(filas[2]["hora_salida"]) == "15:00:00" and "(ingreso + 6 h)" in filas[2]["observaciones"]
    assert "7.5" not in filas[2]["observaciones"]
    assert str(filas[1]["hora_salida"]) == "16:00:00"  # horario asignado: sin cambios
    marca = _rows(jornadas, "SELECT hora, observaciones FROM asistencia_marcas WHERE asistencia_id = 2 AND accion = 'egreso'")[0]
    assert str(marca["hora"]) == "15:00:00" and "(ingreso + 6 h)" in marca["observaciones"]
    assert svc.recalcular_por_parametro()["cambiadas"] == 0  # idempotente


def test_panel_recalcular(monkeypatch):
    llamadas = []
    client = _panel_client(monkeypatch, "admin", llamadas)
    monkeypatch.setattr(svc, "recalcular_por_parametro", lambda **kw: llamadas.append("recalcular") or {
        "revisadas": 3, "cambiadas": 2, "sin_cambios": 1, "detalle": []})
    assert "Recalcular con las horas actuales" in client.get("/asistencias/egresos-automaticos/").get_data(as_text=True)
    response = client.post("/asistencias/egresos-automaticos/recalcular")
    assert response.status_code == 302 and llamadas == ["recalcular", {"audit": "egreso_automatico_recalculo"}]
