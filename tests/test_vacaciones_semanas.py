"""Vacaciones por semanas: lunes feriado, saldo, Mi equipo (cadena del jefe), cancelaciones y avisos.

Las de armar_tandas no usan base; el resto usa MySQL real (SH_TEST_DB_PORT), como push y reuniones."""
import datetime as dt
import json
from pathlib import Path

import pytest
from flask import Flask

from services import avisos_push as avisos
from services import notificaciones_service as noti
from services import vacaciones_semanas_service as sem
from services import vacaciones_service as vs
from tests.test_push import _envios, clave_rsa, firebase, push_db  # noqa: F401  (fixtures)
from tests.test_reuniones import emp, reuniones_db  # noqa: F401
from tests.test_seguridad import database  # noqa: F401

D = dt.date
FERIADOS = {D(2026, 11, 23): "Soberanía", D(2027, 2, 8): "Carnaval", D(2027, 2, 9): "Carnaval"}


# --- Semanas y lunes feriado (sin base) ----------------------------------------------------------------

def test_semanas_seguidas_forman_una_tanda_y_el_lunes_feriado_corre_el_inicio():
    tandas = sem.armar_tandas(["2026-11-30", "2026-11-23", "2027-01-04"], FERIADOS)
    assert [(t["inicio"], t["fin"], t["dias"], t["semanas"], t["anio"]) for t in tandas] == [
        (D(2026, 11, 24), D(2026, 12, 7), 14, 2, 2026),  # lunes 23 feriado: martes a lunes, 14 dias corridos
        (D(2027, 1, 4), D(2027, 1, 10), 7, 1, 2027)]
    assert tandas[0]["motivo_inicio"] == "Empieza el martes 24/11 porque el lunes 23/11 es Soberanía."
    carnaval = sem.armar_tandas(["2027-02-08"], FERIADOS)[0]
    assert (carnaval["inicio"], carnaval["fin"]) == (D(2027, 2, 10), D(2027, 2, 16))  # lunes y martes: de miercoles a martes
    fin_de_anio = sem.armar_tandas(["2026-12-28"], {})[0]
    assert (fin_de_anio["fin"], fin_de_anio["anio"]) == (D(2027, 1, 3), 2026)  # descuenta del anio en que empieza


@pytest.mark.parametrize("semanas,mensaje", [
    (["2026-11-24"], "no es lunes"),
    (["2026-11-30", "2026-11-30"], "dos veces"),
    ([], "al menos una"),
    ("2026-11-30", "al menos una"),  # no es una lista
    ([f"2027-{m:02d}-01" for m in (3,)] + ["x"], "inválida"),
])
def test_validaciones_de_semanas(semanas, mensaje):
    with pytest.raises(sem.Error, match=mensaje):
        sem.armar_tandas(semanas, {})


def test_semana_sin_dias_habiles():
    toda = {D(2027, 3, 22) + dt.timedelta(days=i): "Cierre" for i in range(5)}
    with pytest.raises(sem.Error, match="no tiene días hábiles"):
        sem.armar_tandas(["2027-03-22"], toda)


# --- Base ---------------------------------------------------------------------------------------------------

HOY = dt.datetime(2026, 10, 18, 10, 0)


@pytest.fixture
def vac(push_db, monkeypatch):  # noqa: F811
    """Organigrama de la empresa 1: 13 dueno (sin jefe) <- 11 jefe <- 10 <- 12; 14 sin jefe ni reportes; 20 es de la
    empresa 2. 10 tiene 11 anios de antiguedad (28 dias); 12 tiene 2 (14 dias). Feriados: general lunes 23/11/2026
    y carnaval 2027; la sucursal 2 (empleado 12) ademas el lunes 7/12/2026."""
    import repositories.vacacion_repository as legacy_repo
    import repositories.vacaciones_repository as repo
    import web.auth.decorators as auth

    conn = push_db()
    c = conn.cursor()
    for sql in [
        "ALTER TABLE empresas ADD COLUMN razon_social VARCHAR(100) NULL",
        "ALTER TABLE empleados ADD COLUMN reporta_a_empleado_id INT NULL",
        "ALTER TABLE empleados ADD COLUMN fecha_ingreso DATE NULL",
        "ALTER TABLE empleados ADD COLUMN fecha_baja DATE NULL",
        "ALTER TABLE vacaciones ADD COLUMN empresa_id INT NULL",
        "ALTER TABLE vacaciones ADD COLUMN observaciones VARCHAR(255) NULL",
        """CREATE TABLE vacaciones_movimientos (
             id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY, empleado_id INT NOT NULL, empresa_id INT NOT NULL,
             anio SMALLINT NOT NULL, tipo ENUM('tomado','compensatorio','ajuste') NOT NULL, dias DECIMAL(5,2) NOT NULL,
             observacion VARCHAR(255) NULL, fecha_desde DATE NULL, fecha_hasta DATE NULL,
             estado ENUM('pendiente','aprobado','rechazado') NOT NULL DEFAULT 'aprobado', motivo_resolucion VARCHAR(255) NULL,
             resuelto_by INT NULL, resuelto_at DATETIME NULL, origen_movimiento_id BIGINT UNSIGNED NULL,
             revertido_por_movimiento_id BIGINT UNSIGNED NULL,
             created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
             updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP)""",
        """CREATE TABLE IF NOT EXISTS asistencias (id INT AUTO_INCREMENT PRIMARY KEY, empresa_id INT, empleado_id INT,
             fecha DATE, hora_entrada TIME NULL, hora_salida TIME NULL, estado VARCHAR(30) NULL)""",
        """CREATE TABLE IF NOT EXISTS usuarios (id INT PRIMARY KEY, empresa_id INT, empleado_id INT NULL,
             activo TINYINT DEFAULT 1, usuario VARCHAR(60), rol VARCHAR(20))""",
        "UPDATE empleados SET reporta_a_empleado_id = 13 WHERE id = 11",
        "UPDATE empleados SET reporta_a_empleado_id = 11 WHERE id = 10",
        "UPDATE empleados SET reporta_a_empleado_id = 10 WHERE id = 12",
        "UPDATE empleados SET fecha_ingreso = '2010-01-01'",
        "UPDATE empleados SET fecha_ingreso = '2015-03-01' WHERE id = 10",
        "UPDATE empleados SET fecha_ingreso = '2024-01-01' WHERE id = 12",
        "INSERT INTO asistencia_dias_no_laborables (empresa_id, sucursal_id, sector_id, fecha, motivo) VALUES "
        "(0, 0, 0, '2026-11-23', 'Soberanía'), (0, 0, 0, '2027-02-08', 'Carnaval'), (0, 0, 0, '2027-02-09', 'Carnaval'),"
        " (1, 2, 0, '2026-12-07', 'Aniversario Norte')",
    ]:
        try:
            c.execute(sql)
        except Exception as exc:
            if "Duplicate column" not in str(exc):
                raise
    from scripts.migrate_20261018_01_vacaciones_semanas import migrate_cursor
    migrate_cursor(c)
    migrate_cursor(c)  # idempotente
    conn.commit()
    c.close()
    conn.close()
    monkeypatch.setattr(repo, "get_db", push_db)
    monkeypatch.setattr(legacy_repo, "get_db", push_db)
    monkeypatch.setattr(vs, "count_dias_efectivamente_trabajados", lambda **kw: 220)
    monkeypatch.setattr(vs, "_today", lambda: HOY.date())
    monkeypatch.setattr(sem, "now_local", lambda: HOY)
    monkeypatch.setattr(auth, "can_access_module", lambda *a, **k: False)
    return push_db


def _sql(sql, args=()):
    with sem.db.transaction() as c:
        c.execute(sql, args)
        return c.lastrowid


def _filas(sql, args=()):
    with sem.db.transaction(read_only=True) as c:
        return sem.db.all_rows(c, sql, args)


def _pedidos(tipo=None):
    return [dict(e, datos=json.loads(e["datos"])) for e in _envios() if tipo is None or e["tipo"] == tipo]


def _pedir_10():
    """Ana (10) pide 3 semanas no corridas: con el lunes 23/11 feriado y una de enero."""
    return sem.crear_solicitud(10, ["2026-11-23", "2026-11-30", "2027-01-04"], "Viaje")


# --- Pedido del empleado ----------------------------------------------------------------------------------------

def test_solicitud_de_semanas_no_corridas_crea_tandas_y_un_solo_aviso_al_jefe(vac):
    solicitud = _pedir_10()
    assert [(t["fecha_desde"], t["fecha_hasta"], t["dias"], t["semanas"], t["anio"], t["inicio_corrido"])
            for t in solicitud["tandas"]] == [("2026-11-24", "2026-12-07", 14, 2, 2026, True),
                                              ("2027-01-04", "2027-01-10", 7, 1, 2027, False)]
    assert solicitud["estado"] == "pendiente" and solicitud["dias"] == 21 and solicitud["puede_cancelar"]
    filas = _filas("SELECT solicitud_id, estado FROM vacaciones_movimientos ORDER BY id")
    assert {f["solicitud_id"] for f in filas} == {solicitud["id"]} and {f["estado"] for f in filas} == {"pendiente"}
    [aviso] = _pedidos("revision_pendiente")
    assert aviso["empleado_id"] == 11  # el jefe directo (sin usuarios de RR. HH. vinculados)
    assert aviso["cuerpo"] == "Perez Ana pidió 3 semanas: del 24/11 al 07/12 y del 04/01 al 10/01 (21 días)."
    assert aviso["datos"]["ruta"] == f"/equipo/vacaciones/{solicitud['id']}"
    nota = noti.detalle(emp(11), int(aviso["datos"]["notificacion_id"]))
    assert nota["referencia"] == {"tipo": "vacaciones_solicitud", "id": solicitud["id"], "disponible": True}


def test_saldo_en_semanas_completas(vac):
    with pytest.raises(sem.SaldoError, match=r"te quedan 14 días \(2 semanas completas\) y pediste 21"):
        sem.crear_solicitud(12, ["2026-11-02", "2026-11-09", "2026-11-16"])
    _sql("INSERT INTO vacaciones_movimientos (empleado_id, empresa_id, anio, tipo, dias, estado) "
         "VALUES (12, 1, 2026, 'compensatorio', 2, 'aprobado')")
    saldo = sem.semanas(12, 2026)["saldo"]
    assert (saldo["dias_disponibles"], saldo["semanas_disponibles"], saldo["dias_fuera_de_semanas"]) == (16, 2, 2)


def test_semanas_pasadas_y_superpuestas(vac):
    with pytest.raises(sem.Error, match="ya empezó o pasó"):
        sem.crear_solicitud(10, ["2026-10-12"])
    _pedir_10()
    with pytest.raises(sem.Error, match="pedilas juntas"):
        sem.crear_solicitud(10, ["2026-12-07"])  # la tanda corrida termina el lunes 7/12


def test_endpoints_por_fechas_solo_aceptan_semanas_completas(vac):
    assert sem.semanas_de_rango(10, "2026-11-24", "2026-12-07") == ["2026-11-23", "2026-11-30"]
    with pytest.raises(sem.Error, match="Esa semana empieza el martes 24/11"):
        sem.semanas_de_rango(10, "2026-11-23", "2026-11-29")
    with pytest.raises(sem.Error, match="semanas completas"):
        sem.semanas_de_rango(10, "2026-11-02", "2026-11-06")
    resultado = vs.solicitar_vacaciones(empleado_id=10, fecha_desde="2026-11-24", fecha_hasta="2026-12-07")
    assert resultado["dias_solicitados"] == 14 and resultado["solicitud_id"] == resultado["id"]


def test_calendario_de_semanas(vac):
    _pedir_10()
    cal = sem.semanas(10, 2026)
    por_lunes = {s["lunes"]: s for s in cal["semanas"]}
    assert len(cal["semanas"]) == 52 and cal["feriados_cargados"] is True
    assert por_lunes["2026-10-12"]["estado"] == "pasada"
    assert por_lunes["2026-11-23"] == dict(lunes="2026-11-23", domingo="2026-11-29", inicio="2026-11-24", fin="2026-11-30",
                                           feriado_lunes="Soberanía", estado="pendiente",
                                           solicitud_id=por_lunes["2026-11-23"]["solicitud_id"])
    assert por_lunes["2026-12-07"]["estado"] == "pendiente"  # la tanda corrida ocupa el lunes 7/12
    assert por_lunes["2026-12-14"]["estado"] == "disponible"
    assert cal["saldo"]["semanas_disponibles"] == 2  # 28 - 14 pendientes de 2026
    assert sem.semanas(12, 2026)["semanas"][48]["inicio"] == "2026-12-08"  # feriado de su sucursal
    assert sem.semanas(10, 2028)["feriados_cargados"] is False


# --- Mi equipo -------------------------------------------------------------------------------------------------

def test_alcance_de_cada_uno(vac):
    with sem.db.transaction(read_only=True) as c:
        jefe, dueno, solo, otra = (sem.equipo(c, sem._empleado(c, i)) for i in (11, 13, 14, 20))
    assert (jefe["alcance"], jefe["visibles"], jefe["directos"]) == ("equipo", {10, 12}, {10})
    assert (dueno["alcance"], dueno["visibles"], dueno["directos"]) == ("empresa", {10, 11, 12, 14}, {11})
    assert (solo["alcance"], solo["visibles"]) == ("sin_equipo", set())  # sin jefe y sin reportes: no ve a nadie
    assert otra["visibles"] == set()


def test_el_jefe_ve_su_cadena_y_aprueba_solo_a_sus_directos(vac):
    de_12 = sem.crear_solicitud(12, ["2026-11-02"])
    de_10 = _pedir_10()
    equipo = sem.equipo_solicitudes(11)
    assert [s["id"] for s in equipo["items"]] == [de_12["id"], de_10["id"]] and equipo["por_resolver"] == 1
    assert [s["puede_resolver"] for s in equipo["items"]] == [False, True]
    with pytest.raises(sem.SinPermiso):
        sem.aprobar(11, de_12["id"])  # 12 no es directo de 11
    with pytest.raises(sem.NoEncontrada):
        sem.equipo_solicitud(14, de_10["id"])
    assert sem.aprobar(10, de_12["id"])["estado"] == "aprobada"  # su jefe directo si
    saldos = {i["empleado"]["id"]: i for i in sem.equipo_saldos(11, 2026)["items"]}
    assert saldos[10]["semanas_disponibles"] == 2 and saldos[12]["dias_disponibles"] == 7 and saldos[10]["es_directo"]
    cal = sem.equipo_calendario(11, "2026-11")
    assert [(i["empleado"]["id"], i["fecha_desde"], i["estado"]) for i in cal["items"]] == [
        (12, "2026-11-02", "aprobado"), (10, "2026-11-24", "pendiente")]


def test_aprobar_avisa_una_vez_con_quien_aprobo_y_limpia_la_revision(vac):
    solicitud = _pedir_10()
    revision = _pedidos("revision_pendiente")[0]
    resultado = sem.aprobar(11, solicitud["id"])
    assert resultado["estado"] == "aprobada" and {t["resuelto_por"] for t in resultado["tandas"]} == {"Garcia Luis"}
    [aviso] = _pedidos("vacaciones")
    assert aviso["empleado_id"] == 10 and aviso["titulo"] == "Vacaciones aprobadas"
    assert aviso["cuerpo"] == "Tus vacaciones del 24/11 al 07/12 y del 04/01 al 10/01 fueron aprobadas (21 días) por Garcia Luis."
    assert aviso["datos"]["evento"] == "aprobada" and aviso["datos"]["ruta"] == f"/vacaciones/{solicitud['id']}"
    assert not [e for e in _envios() if e["id"] == revision["id"]]  # el push "para revisar" sin enviar se borro
    assert noti.listado(emp(11))["no_leidas"] == 0  # y la notificacion del jefe quedo leida
    assert len(_filas("SELECT id FROM vacaciones WHERE empleado_id = 10")) == 2  # periodos para el reporte mensual


def test_rechazar_pide_motivo_y_lo_avisa(vac):
    solicitud = _pedir_10()
    with pytest.raises(sem.Error, match="motivo"):
        sem.rechazar(11, solicitud["id"], " ")
    sem.rechazar(11, solicitud["id"], "Cierre de año")
    aviso = _pedidos("vacaciones")[0]
    assert aviso["titulo"] == "Vacaciones rechazadas" and aviso["cuerpo"].endswith("por Garcia Luis. Motivo: Cierre de año")


# --- Cancelaciones -----------------------------------------------------------------------------------------------

def test_cancelar_lo_pendiente_no_avisa_al_propio_empleado(vac):
    solicitud = _pedir_10()
    resultado = sem.cancelar(10, solicitud["id"])
    assert resultado["canceladas"] == 2 and resultado["solicitud"]["estado"] == "rechazada"
    assert _pedidos("vacaciones") == [] and noti.listado(emp(11))["no_leidas"] == 0
    assert not [e for e in _envios() if e["estado"] == "pendiente"]


def test_cancelar_lo_aprobado_es_un_pedido_al_jefe(vac):
    solicitud = _pedir_10()
    sem.aprobar(11, solicitud["id"])
    enero = solicitud["tandas"][1]["movimiento_id"]
    pedido = sem.cancelar(10, solicitud["id"], "Se suspendió el viaje", movimiento_id=enero)
    assert pedido["cancelacion_pedida"] == 1 and pedido["solicitud"]["cancelacion_pedida"]
    aviso = [e for e in _pedidos("revision_pendiente") if e["titulo"] == "Cancelación de vacaciones para revisar"][0]
    assert aviso["cuerpo"] == "Perez Ana pidió cancelar sus vacaciones del 04/01 al 10/01. Motivo: Se suspendió el viaje"
    assert sem.equipo_solicitudes(11, estado="pendiente")["items"][0]["puede_resolver_cancelacion"]
    sem.resolver_cancelacion(11, solicitud["id"], True)
    final = sem.mi_solicitud(10, solicitud["id"])
    assert [t["estado"] for t in final["tandas"]] == ["aprobado", "cancelada"] and final["estado"] == "parcial"
    assert [e["titulo"] for e in _pedidos("vacaciones")][-1] == "Vacaciones canceladas"
    assert sem.semanas(10, 2027)["saldo"]["dias_disponibles"] == 28  # los 7 dias de enero volvieron


def test_rechazar_la_cancelacion_mantiene_las_vacaciones(vac):
    solicitud = _pedir_10()
    sem.aprobar(11, solicitud["id"])
    sem.cancelar(10, solicitud["id"], "Cambio de planes")
    sem.resolver_cancelacion(11, solicitud["id"], False, "Ya está cubierto el puesto")
    assert sem.mi_solicitud(10, solicitud["id"])["estado"] == "aprobada"
    assert _pedidos("vacaciones")[-1]["titulo"] == "Tus vacaciones siguen en pie"


def test_lo_que_ya_empezo_no_se_cancela_desde_la_app(vac, monkeypatch):
    solicitud = _pedir_10()
    sem.aprobar(11, solicitud["id"])
    monkeypatch.setattr(sem, "now_local", lambda: dt.datetime(2026, 11, 25, 9, 0))
    with pytest.raises(sem.Error, match="ya empezaron"):
        sem.cancelar(10, solicitud["id"], movimiento_id=solicitud["tandas"][0]["movimiento_id"])


# --- Avisos programados y panel --------------------------------------------------------------------------------

def test_recordatorio_el_dia_habil_anterior_y_escalamiento(vac, monkeypatch):
    solicitud = _pedir_10()
    # Sin resolver a 3 dias de empezar: se escala al jefe del jefe (13), una sola vez.
    assert avisos.vacaciones_sin_resolver(D(2026, 11, 19)) == 0  # faltan 5 dias
    assert avisos.vacaciones_sin_resolver(D(2026, 11, 21)) == 1
    assert avisos.vacaciones_sin_resolver(D(2026, 11, 21)) == 0
    escalada = [e for e in _pedidos("revision_pendiente") if e["titulo"] == "Vacaciones sin resolver"][0]
    assert escalada["empleado_id"] == 13 and "martes 24/11" in escalada["cuerpo"]
    sem.aprobar(11, solicitud["id"])
    # Inicio martes 24/11 (lunes 23 feriado): el dia habil anterior es el viernes 20/11.
    assert avisos.vacaciones_por_empezar(D(2026, 11, 23)) == 0
    assert avisos.vacaciones_por_empezar(D(2026, 11, 20)) == 1
    inicio = _pedidos("vacaciones_inicio")[0]
    assert inicio["empleado_id"] == 10 and inicio["cuerpo"] == "Tus vacaciones empiezan el martes 24/11. Volvés el martes 08/12."
    assert noti.listado(emp(10))["no_leidas"] == 1  # solo push: en la bandeja queda la aprobacion, no el recordatorio
    reglas = {m["clave"]: avisos.reglas_push._defecto(m) for m in avisos.reglas_push.CATALOGO}
    reglas["vacaciones_inicio"]["destinatarios"] = ["empleado", "jefe_directo"]
    monkeypatch.setattr(avisos.reglas_push, "configuracion", lambda empresa_id: (reglas, (None, None)))
    _sql("DELETE FROM push_envios WHERE tipo = 'vacaciones_inicio'")
    assert avisos.vacaciones_por_empezar(D(2026, 11, 20)) == 2
    equipo = _pedidos("vacaciones_equipo")[0]
    assert equipo["empleado_id"] == 11 and equipo["cuerpo"] == "Perez Ana sale de vacaciones el martes 24/11 y vuelve el martes 08/12."


def test_rrhh_carga_vacaciones_y_el_empleado_se_entera(vac):
    vs.crear_movimiento_vacaciones_admin(dict(empleado_id=10, anio=2026, tipo="tomado", estado="aprobado",
                                              fecha_desde="2026-12-14", fecha_hasta="2026-12-16"))
    aviso = _pedidos("vacaciones")[0]
    assert aviso["titulo"] == "Vacaciones cargadas" and aviso["cuerpo"] == "RR. HH. te cargó vacaciones del 14/12 al 16/12 (3 días)."


# --- API --------------------------------------------------------------------------------------------------------

@pytest.fixture
def client(vac, monkeypatch):
    import utils.jwt_guard as jwt_guard
    from routes import vacaciones_semanas_routes

    app = Flask(__name__, template_folder=str(Path(__file__).resolve().parents[1] / "templates"))
    app.register_blueprint(vacaciones_semanas_routes.mobile)
    monkeypatch.setattr(jwt_guard, "verificar_token", lambda token: dict(empleado_id=int(token)))
    return app.test_client()


def test_api_vacaciones_por_semanas_y_equipo(client):
    ana, jefe = {"Authorization": "Bearer 10"}, {"Authorization": "Bearer 11"}
    base = "/api/v1/mobile/me"
    assert client.get(f"{base}/vacaciones/semanas").status_code == 401
    cal = client.get(f"{base}/vacaciones/semanas?anio=2026", headers=ana).json
    assert cal["saldo"]["semanas_disponibles"] == 4
    nuevo = client.post(f"{base}/vacaciones/semanas", headers=ana, json={"semanas": ["2026-11-23", "2026-11-30"]})
    assert nuevo.status_code == 201 and nuevo.json["tandas"][0]["fecha_desde"] == "2026-11-24"
    sid = nuevo.json["id"]
    assert client.post(f"{base}/vacaciones/semanas", headers=ana, json={"semanas": ["2026-11-24"]}).status_code == 400
    sobra = client.post(f"{base}/vacaciones/semanas", headers=ana,
                        json={"semanas": ["2027-03-01", "2027-03-08", "2027-03-15", "2027-03-22", "2027-03-29"]})
    assert sobra.status_code == 409
    assert client.get(f"{base}/vacaciones/solicitudes", headers=ana).json["items"][0]["id"] == sid
    equipo = client.get(f"{base}/equipo/vacaciones?estado=pendiente", headers=jefe).json
    assert equipo["alcance"] == "equipo" and equipo["por_resolver"] == 1
    assert client.post(f"{base}/equipo/vacaciones/solicitudes/{sid}/aprobar", headers=ana).status_code == 404
    assert client.post(f"{base}/equipo/vacaciones/solicitudes/{sid}/rechazar", headers=jefe, json={}).status_code == 400
    aprobada = client.post(f"{base}/equipo/vacaciones/solicitudes/{sid}/aprobar", headers=jefe)
    assert aprobada.status_code == 200 and aprobada.json["estado"] == "aprobada"
    cancelacion = client.post(f"{base}/vacaciones/solicitudes/{sid}/cancelar", headers=ana, json={"motivo": "Cambio"})
    assert cancelacion.json["cancelacion_pedida"] == 1
    assert client.post(f"{base}/equipo/vacaciones/solicitudes/{sid}/cancelacion/aprobar", headers=jefe).json["estado"] == "cancelada"
    assert client.get(f"{base}/equipo/vacaciones/calendario?mes=2026-11", headers=jefe).status_code == 200
    assert client.get(f"{base}/equipo/vacaciones/calendario?mes=11-2026", headers=jefe).status_code == 400
    assert client.get(f"{base}/equipo/vacaciones/saldos?anio=2026", headers=jefe).json["items"][0]["empleado"]["id"] in (10, 12)
