"""Jornada laboral, etapa A: convenios, reglas por nivel con vigencia, topes, asignacion masiva y condiciones.

MySQL real (SH_TEST_DB_PORT), como el resto de los modulos con base."""
import datetime as dt
from pathlib import Path

import pytest
from flask import Flask
from werkzeug.datastructures import MultiDict

from services import jornada_service as s
from tests.test_seguridad import database  # noqa: F401  (fixture)

D = dt.date
QUIEN = dict(empresa_id=1, user_id=99)
HOY = dt.datetime(2026, 10, 19, 10, 0)


@pytest.fixture
def jl(database, monkeypatch):  # noqa: F811
    """Empresa 1: empleados 10, 11 (sucursal 1) y 12 (sucursal 2). Empleado 10 con horario L-V 08-12 y 13-17
    (40 h) desde el 1/10/2026. La empresa 2 tiene al empleado 20."""
    import repositories.empleado_horario_repository as eh
    import repositories.horario_dia_bloque_repository as hb
    import repositories.horario_dia_repository as hd

    conn = database()
    c = conn.cursor()
    for sql in [
        "ALTER TABLE empleados ADD COLUMN tipo_contrato VARCHAR(20) NULL",
        "ALTER TABLE empleados ADD COLUMN fecha_ingreso DATE NULL",
        "ALTER TABLE empleados ADD COLUMN categoria VARCHAR(100) NULL",
        "ALTER TABLE sucursales ADD COLUMN empresa_id INT NOT NULL DEFAULT 1",
        "ALTER TABLE sectores ADD COLUMN empresa_id INT NOT NULL DEFAULT 1",
        "ALTER TABLE puestos ADD COLUMN empresa_id INT NOT NULL DEFAULT 1",
        "UPDATE sucursales SET empresa_id = 2 WHERE id = 3",
        "UPDATE empleados SET tipo_contrato = 'efectivo', fecha_ingreso = '2020-03-01'",
        "CREATE TABLE IF NOT EXISTS usuarios (id INT PRIMARY KEY, usuario VARCHAR(60))",
        "INSERT INTO usuarios VALUES (99, 'rrhh')",
        "CREATE TABLE horarios (id INT AUTO_INCREMENT PRIMARY KEY, empresa_id INT, sucursal_id INT NULL, nombre VARCHAR(80),"
        " tolerancia_min INT DEFAULT 0, descripcion VARCHAR(200) NULL, activo TINYINT DEFAULT 1)",
        "CREATE TABLE horario_dias (id INT AUTO_INCREMENT PRIMARY KEY, horario_id INT, dia_semana INT)",
        "CREATE TABLE horario_dia_bloques (id INT AUTO_INCREMENT PRIMARY KEY, empresa_id INT, horario_dia_id INT, orden INT,"
        " hora_entrada TIME, hora_salida TIME)",
        "CREATE TABLE empleado_horarios (id INT AUTO_INCREMENT PRIMARY KEY, empresa_id INT, empleado_id INT, horario_id INT,"
        " fecha_desde DATE, fecha_hasta DATE NULL)",
        "INSERT INTO horarios (id, empresa_id, nombre, tolerancia_min) VALUES (1, 1, 'Administrativo', 10)",
        "INSERT INTO empleado_horarios (empresa_id, empleado_id, horario_id, fecha_desde) VALUES (1, 10, 1, '2026-10-01')",
    ]:
        c.execute(sql)
    for dia in range(1, 6):
        c.execute("INSERT INTO horario_dias (horario_id, dia_semana) VALUES (1, %s)", (dia,))
        c.execute("INSERT INTO horario_dia_bloques (empresa_id, horario_dia_id, orden, hora_entrada, hora_salida) VALUES "
                  "(1, LAST_INSERT_ID(), 1, '08:00', '12:00')")
        c.execute("INSERT INTO horario_dia_bloques (empresa_id, horario_dia_id, orden, hora_entrada, hora_salida) "
                  "SELECT 1, MAX(id), 2, '13:00', '17:00' FROM horario_dias")
    from scripts.migrate_20261019_01_jornada_laboral import migrate_cursor
    migrate_cursor(c)
    migrate_cursor(c)  # idempotente
    conn.commit()
    c.close()
    conn.close()
    for repo in (eh, hb, hd):
        monkeypatch.setattr(repo, "get_db", database)
    monkeypatch.setattr(s, "now_local", lambda: HOY)
    return database


def _convenio(codigo, empresa_id=1):
    with s.db.transaction(read_only=True) as c:
        return s.db.one(c, "SELECT * FROM jl_convenios WHERE empresa_id = %s AND codigo = %s", (empresa_id, codigo))


def _form(**valores):
    datos = MultiDict()
    for clave, valor in valores.items():
        for v in (valor if isinstance(valor, list) else [valor]):
            datos.add(clave, v)
    return datos


# --- Carga inicial -------------------------------------------------------------------------------------------

def test_carga_inicial_por_empresa_e_idempotente(jl):
    nombres = [c["nombre"] for c in s.convenios(1)]
    assert sorted(nombres) == ["Camioneros (CCT 40/89)", "Fuera de convenio (LCT)", "SUTIAGA"]
    assert len(s.convenios(2)) == 3  # cada empresa los suyos
    lct = s.versiones(1, "convenio", _convenio("LCT")["id"])
    assert len(lct) == 1 and float(lct[0]["horas_semanales"]) == 48 and lct[0]["tope_extras_mes"] == 30
    assert s.versiones(1, "convenio", _convenio("CCT_40_89")["id"]) == []  # sin valores inventados


# --- Reglas por nivel y vigencia --------------------------------------------------------------------------------

def test_el_nivel_mas_especifico_gana_campo_por_campo(jl):
    s.guardar_regla(QUIEN, "empresa", None, _form(vigente_desde="2026-01-01", horas_semanales="45", dias_laborales=["1", "2", "3", "4", "5"],
                                                  tolerancia_ingreso_min="10"))
    s.guardar_regla(QUIEN, "sucursal", 1, _form(vigente_desde="2026-01-01", horas_semanales="44"))
    camioneros = _convenio("CCT_40_89")["id"]
    s.guardar_regla(QUIEN, "convenio", camioneros, _form(vigente_desde="2026-01-01", horas_semanales="48", horas_diarias="9"))
    s.asignar_convenio(QUIEN, [10], camioneros, "2026-01-01")
    s.guardar_regla(QUIEN, "empleado", 10, _form(vigente_desde="2026-06-01", horas_diarias="6"))
    c = s.condiciones(QUIEN, 10)["efectivos"]
    assert (c["horas_diarias"]["valor"], c["horas_diarias"]["origen"]) == ("6 h", "Individual")
    assert (c["horas_semanales"]["valor"], c["horas_semanales"]["origen"]) == ("48 h", "Convenio")
    assert (c["dias_laborales"]["valor"], c["dias_laborales"]["origen"]) == ("Lun, Mar, Mié, Jue, Vie", "Empresa")
    assert c["tolerancia_ingreso_min"]["valor"] == "10"
    # El 11 no tiene convenio: le llega la regla de su sucursal (44) y, para los topes, Fuera de convenio (LCT).
    once = s.condiciones(QUIEN, 11)
    assert once["efectivos"]["horas_semanales"]["valor"] == "44 h" and once["efectivos"]["horas_semanales"]["origen"] == "Sucursal"
    assert once["efectivos"]["horas_semanales"]["tope"] == "48 h" and "LCT" in once["avisos"][0]
    # A una fecha anterior a la condicion individual vale el convenio.
    assert s.condiciones(QUIEN, 10, "2026-05-15")["efectivos"]["horas_diarias"]["valor"] == "9 h"


def test_versiones_cierran_la_anterior_y_no_reescriben_el_pasado(jl):
    primera = s.guardar_regla(QUIEN, "empresa", None, _form(vigente_desde="2026-01-01", horas_semanales="45", motivo="Inicial"))
    s.guardar_regla(QUIEN, "empresa", None, _form(vigente_desde="2026-07-01", horas_semanales="42", motivo="Acuerdo"))
    versiones = s.versiones(1, "empresa")
    assert [(v["vigente_desde"], v["vigente_hasta"]) for v in versiones] == [(D(2026, 7, 1), None), (D(2026, 1, 1), D(2026, 6, 30))]
    assert versiones[0]["reemplaza_id"] == primera
    with pytest.raises(s.Error, match="tiene que empezar después"):
        s.guardar_regla(QUIEN, "empresa", None, _form(vigente_desde="2026-03-01", horas_semanales="40"))
    assert s.vista_reglas(1)["empresa"]["horas_semanales"] == 42


def test_una_condicion_individual_no_supera_los_topes_del_convenio(jl):
    camioneros = _convenio("CCT_40_89")["id"]
    s.guardar_regla(QUIEN, "convenio", camioneros, _form(vigente_desde="2026-01-01", horas_semanales="48", tope_extras_mes="30"))
    s.asignar_convenio(QUIEN, [10], camioneros, "2026-01-01")
    with pytest.raises(s.Error, match="supera el tope de su convenio"):
        s.guardar_regla(QUIEN, "empleado", 10, _form(vigente_desde="2026-10-01", horas_semanales="50"))
    with pytest.raises(s.Error, match="Tope de horas extras por mes"):
        s.guardar_regla(QUIEN, "empleado", 10, _form(vigente_desde="2026-10-01", tope_extras_mes="40"))
    assert s.guardar_regla(QUIEN, "empleado", 10, _form(vigente_desde="2026-10-01", horas_semanales="36"))  # mas favorable
    # Sin convenio asignado, el tope es el de Fuera de convenio (LCT: 48 h).
    with pytest.raises(s.Error, match="48 h"):
        s.guardar_regla(QUIEN, "empleado", 11, _form(vigente_desde="2026-10-01", horas_semanales="49"))


@pytest.mark.parametrize("campos,mensaje", [
    ({}, "al menos un valor"),
    ({"horas_semanales": "90"}, "entre 1 y 80"),
    ({"nocturna_desde": "21:00"}, "hora de inicio y de fin"),
    ({"nocturna_desde": "25:00", "nocturna_hasta": "06:00"}, "hora inválida"),
    ({"regimen_distribucion": "otro"}, "valor inválido"),
])
def test_validaciones(jl, campos, mensaje):
    with pytest.raises(s.Error, match=mensaje):
        s.guardar_regla(QUIEN, "empresa", None, _form(vigente_desde="2026-01-01", **campos))


def test_aislamiento_entre_empresas(jl):
    otra = _convenio("CCT_40_89", empresa_id=2)
    with pytest.raises(s.Error, match="No se encontró"):
        s.guardar_regla(QUIEN, "convenio", otra["id"], _form(vigente_desde="2026-01-01", horas_semanales="40"))
    with pytest.raises(s.Error, match="No se encontró"):
        s.guardar_regla(QUIEN, "sucursal", 3, _form(vigente_desde="2026-01-01", horas_semanales="40"))
    asignados, errores = s.asignar_convenio(QUIEN, [10, 20], _convenio("LCT")["id"], "2026-01-01")
    assert asignados == 1 and errores[0]["empleado_id"] == 20
    with pytest.raises(s.Error, match="Empleado no encontrado"):
        s.condiciones(QUIEN, 20)


# --- Asignacion masiva e historial ------------------------------------------------------------------------------

def test_asignacion_masiva_conserva_el_historial(jl):
    lct, camioneros = _convenio("LCT")["id"], _convenio("CCT_40_89")["id"]
    assert s.asignar_convenio(QUIEN, [10, 11, 12], lct, "2026-01-01", "Alta") == (3, [])
    asignados, errores = s.asignar_convenio(QUIEN, [10, 11], camioneros, "2026-09-01", "Pasan a choferes")
    assert asignados == 2 and errores == []
    datos = s.condiciones(QUIEN, 10)
    assert datos["convenio"]["convenio_nombre"] == "Camioneros (CCT 40/89)"
    assert [(h["convenio_nombre"], h["vigente_hasta"]) for h in datos["historial"]] == [
        ("Camioneros (CCT 40/89)", None), ("Fuera de convenio (LCT)", D(2026, 8, 31))]
    # Repetida, o anterior a la vigente: se informa por empleado y no se toca nada.
    _, errores = s.asignar_convenio(QUIEN, [10], camioneros, "2026-10-01")
    assert errores[0]["error"] == "ya tiene ese convenio"
    _, errores = s.asignar_convenio(QUIEN, [12], camioneros, "2025-12-01")
    assert "ya tiene una asignación desde" in errores[0]["error"]
    assert [e["convenio_nombre"] for e in s.empleados_para_asignar(1, {"convenio_id": str(camioneros)})] == [
        "Camioneros (CCT 40/89)", "Camioneros (CCT 40/89)"]
    assert len(s.empleados_para_asignar(1, {"convenio_id": "sin"})) == 1  # el 13 no tiene convenio
    tipos = {(f["tipo"], f["alcance"]) for f in s.historial(1)}
    assert ("asignacion", "empleado") in tipos and ("regla", "convenio") in tipos


def test_horario_asignado_y_aviso_si_programa_mas_que_lo_pactado(jl):
    s.guardar_regla(QUIEN, "empresa", None, _form(vigente_desde="2026-01-01", horas_semanales="36"))
    datos = s.condiciones(QUIEN, 10)
    h = datos["horario"]
    assert h["nombre"] == "Administrativo" and h["horas_semana"] == 40 and h["tolerancia_min"] == 10
    assert h["dias"][0] == dict(dia=1, nombre="lunes", bloques=[("08:00", "12:00"), ("13:00", "17:00")],
                                descansos=[("12:00", "13:00")], minutos=480)
    assert any("programa 40 h" in a for a in datos["avisos"])
    assert any("Sin horario" in a or "No tiene horario" in a for a in s.condiciones(QUIEN, 11)["avisos"])
    resumen = s.resumen_empleado(QUIEN, 10)
    assert resumen["horas_semanales"] == "36 h" and resumen["horario"] == "Administrativo"


# --- Panel ------------------------------------------------------------------------------------------------------

@pytest.fixture
def client(jl, monkeypatch):
    import web.auth.decorators as auth
    from web.jornada import routes

    app = Flask(__name__, template_folder=str(Path(__file__).resolve().parents[1] / "templates"))
    app.secret_key = "test"
    app.config["TESTING"] = True
    app.register_blueprint(routes.web)
    permisos = {"acciones": {"ver", "crear", "editar"}}

    def can_web(code, action="ver"):
        return code == "jornada_laboral" and action in permisos["acciones"]

    app.jinja_env.globals.update(csp_nonce=lambda: "n", csrf_token=lambda: "t", can_web=can_web,
                                 export_toolbar={"enabled": False, "items": []})
    monkeypatch.setattr(auth, "can_access_module", lambda uid, module, action="ver": can_web(module, action))
    monkeypatch.setattr(routes, "_cached_web_user", lambda uid: dict(id=99, empresa_id=1, activo=1))
    monkeypatch.setattr(routes, "log_audit", lambda *a, **kw: None)
    test_client = app.test_client()
    with test_client.session_transaction() as sess:
        sess["user_id"] = 99
    test_client.permisos = permisos
    return test_client


def test_pantallas_del_panel_y_permisos(client):
    base = "/jornada-laboral"
    for ruta in ("/reglas", "/convenios", "/asignaciones", "/historial", "/empleado/10"):
        assert client.get(base + ruta).status_code == 200, ruta
    assert "Camioneros (CCT 40/89)" in client.get(base + "/convenios").get_data(as_text=True)
    lct = _convenio("LCT")["id"]
    assert "48 h" in client.get(f"{base}/convenios/{lct}").get_data(as_text=True)
    r = client.post(base + "/asignaciones", data={"empleado_id": ["10", "11"], "convenio_id": str(lct), "vigente_desde": "2026-10-01"})
    assert r.status_code == 302 and s.condiciones(QUIEN, 11)["convenio"]["convenio_nombre"] == "Fuera de convenio (LCT)"
    r = client.post(base + "/reglas", data={"vigente_desde": "2026-10-01", "horas_semanales": "45", "sucursal_id": "1"})
    assert r.status_code == 302 and s.vista_reglas(1)["por_sucursal"][1]["horas_semanales"] == 45
    pagina = client.get(base + "/empleado/10").get_data(as_text=True)
    assert "Condiciones laborales" in pagina and "Administrativo" in pagina and "Sucursal" in pagina
    client.permisos["acciones"] = {"ver"}  # solo lectura: no puede guardar
    assert client.post(base + "/reglas", data={"vigente_desde": "2026-11-01", "horas_semanales": "40"}).status_code == 403
    assert "Guardar versión" not in client.get(base + "/reglas").get_data(as_text=True)
    client.permisos["acciones"] = set()
    assert client.get(base + "/reglas").status_code == 403
