"""Mis reuniones: proximas ampliadas, calendario mensual, dashboard y evolucion (mismas reglas en todo).

Usan MySQL real (SH_TEST_DB_PORT), como el resto de Reuniones."""
import datetime as dt

import pytest

from services import reunion_service as svc
from tests.test_reuniones import ADMIN, AHORA, _no_laborable, client, crear, emp, reuniones_db  # noqa: F401
from tests.test_seguridad import database  # noqa: F401

D = dt.date


def _cuando(*args):
    AHORA["valor"] = dt.datetime(*args)


def _qr(rid):
    with svc.db.transaction(read_only=True) as c:
        return svc.qr_fijo(svc.sede_de_empleado(c, svc.obtener(c, ADMIN, rid), emp(10)))


@pytest.fixture
def octubre(reuniones_db):
    """Lunes y miercoles 09:00 (60 min), creada el 1/10. Al 22/10 12:00 el empleado 10 tiene:
    5/10 presente, 7/10 tarde, 12/10 ausente (cerrada), 14/10 justificado (vacaciones), 19/10 cancelada,
    21/10 ausencia provisoria (sin cerrar todavia), 26/10 y 28/10 pendientes."""
    _cuando(2026, 10, 1, 8, 0)
    rid = crear(nombre="Daily", dias_semana=["0", "2"])
    qr = _qr(rid)
    _cuando(2026, 10, 5, 8, 50)
    assert svc.registrar_qr(emp(10), qr)["estado"] == "presente"
    _cuando(2026, 10, 7, 9, 20)
    assert svc.registrar_qr(emp(10), qr)["estado"] == "tarde"
    with svc.db.transaction() as c:
        c.execute("INSERT INTO vacaciones (empleado_id, fecha_desde, fecha_hasta) VALUES (10, '2026-10-14', '2026-10-14')")
    _cuando(2026, 10, 16, 8, 0)
    svc.cancelar_ocurrencia(ADMIN, rid, D(2026, 10, 19), "Inventario")
    svc.cerrar_ocurrencias(ahora=dt.datetime(2026, 10, 20, 23, 0), dias_atras=30)
    _cuando(2026, 10, 22, 12, 0)
    return rid


# --- Calendario ----------------------------------------------------------------------------------------

def test_calendario_del_mes_con_todos_los_estados(octubre):
    cal = svc.calendario_mes(emp(10), "2026-10")
    assert cal["periodo"] == {"mes": "2026-10", "desde": "2026-10-01", "hasta": "2026-10-31"}
    assert cal["zona_horaria"] == "America/Argentina/Buenos_Aires" and cal["calculado_at"] == "2026-10-22T12:00:00-03:00"
    estados = [(i["fecha"], i["estado"], i["definitivo"]) for i in cal["items"]]
    assert estados == [
        ("2026-10-05", "presente", True), ("2026-10-07", "tarde", True), ("2026-10-12", "ausente", True),
        ("2026-10-14", "justificado", True), ("2026-10-19", "cancelada", True), ("2026-10-21", "ausente", False),
        ("2026-10-26", "pendiente", False), ("2026-10-28", "pendiente", False)]
    assert cal["total"] == 8
    primero = cal["items"][0]
    assert primero["id"] == f"{octubre}-0-2026-10-05" and primero["ocurrencia_id"]
    assert (primero["inicio"], primero["fin"], primero["duracion_min"]) == (
        "2026-10-05T09:00:00-03:00", "2026-10-05T10:00:00-03:00", 60)
    assert cal["items"][3]["observaciones"] == "Vacaciones"
    cancelada = cal["items"][4]
    assert cancelada["cancelada"] and cancelada["motivo_cancelacion"] == "Inventario"
    pendiente = cal["items"][-1]
    assert pendiente["ocurrencia_id"] is None and pendiente["id"] == f"{octubre}-0-2026-10-28"  # id estable sin fila
    assert pendiente["ventana_desde"] == "2026-10-28T08:45:00-03:00" and not pendiente["puede_registrar"]


def test_registro_abierto_se_puede_registrar(octubre):
    _cuando(2026, 10, 26, 8, 50)
    item = next(i for i in svc.calendario_mes(emp(10), "2026-10")["items"] if i["fecha"] == "2026-10-26")
    assert item["estado"] == "abierta" and item["puede_registrar"] is True and item["definitivo"] is False


def test_meses_vacios_y_cambio_de_anio(reuniones_db):
    _cuando(2026, 12, 20, 8, 0)
    vacio = svc.calendario_mes(emp(10), "2027-01")
    assert vacio["items"] == [] and vacio["resumen"]["planificadas"] == 0
    assert vacio["resumen"]["asistencia_pct"] is None and vacio["resumen"]["puntualidad_pct"] is None
    crear(nombre="Mensual", frecuencia="mensual", mensual_tipo="dia", dia_mes="31", dias_semana=[])
    serie = svc.evolucion(emp(10), "2026-11", "2027-02")
    assert [m["mes"] for m in serie["meses"]] == ["2026-11", "2026-12", "2027-01", "2027-02"]
    # Creada el 20/12: noviembre vacio; diciembre 31/12, enero 31/01 y febrero 28/02 (el ultimo dia del mes).
    assert [m["planificadas"] for m in serie["meses"]] == [0, 1, 1, 1]
    assert serie["meses"][0]["asistencia_pct"] is None and serie["meses"][0]["estado_periodo"] == "pasado"
    assert [i["fecha"] for i in svc.calendario_mes(emp(10), "2027-02")["items"]] == ["2027-02-28"]
    for malo in ("2026-13", "26-10", "2026/10", ""):
        with pytest.raises(svc.Error, match="AAAA-MM"):
            svc.calendario_mes(emp(10), malo)


def test_dia_no_laborable_pospone_entre_meses_sin_duplicar(reuniones_db):
    _cuando(2026, 10, 1, 8, 0)
    crear(nombre="Viernes", dias_semana=["4"])  # viernes 30/10 no laborable -> lunes 2/11
    _no_laborable(1, 0, 0, "2026-10-30", "Puente")
    octubre_fechas = [i["fecha"] for i in svc.calendario_mes(emp(10), "2026-10")["items"]]
    noviembre = svc.calendario_mes(emp(10), "2026-11")["items"]
    assert "2026-10-30" not in octubre_fechas and octubre_fechas[-1] == "2026-10-23"
    assert [(i["fecha"], i["fecha_original"]) for i in noviembre[:2]] == [("2026-11-02", "2026-10-30"), ("2026-11-06", None)]
    assert noviembre[0]["motivo_cambio"] == "Pospuesta del viernes 30/10 por día no laborable (Puente)."
    assert len({i["id"] for i in noviembre}) == len(noviembre)


def test_horario_cambiado_no_duplica(octubre):
    svc.reprogramar_ocurrencia(ADMIN, octubre, D(2026, 10, 26), "11:00", "Visita")
    del_dia = [i for i in svc.calendario_mes(emp(10), "2026-10")["items"] if i["fecha"] == "2026-10-26"]
    assert len(del_dia) == 1 and del_dia[0]["reprogramada"] is True
    assert del_dia[0]["inicio"] == "2026-10-26T11:00:00-03:00" and del_dia[0]["duracion_min"] == 60
    assert del_dia[0]["motivo_cambio"] == "Horario cambiado a las 11:00 (habitual 09:00): Visita"


# --- Dashboard ---------------------------------------------------------------------------------------------

def test_dashboard_del_mes_horas_y_porcentajes(octubre):
    tablero = svc.estadisticas_mes(emp(10), "2026-10")
    t = tablero["totales"]
    assert (t["planificadas"], t["realizadas"], t["proximas"], t["canceladas"]) == (7, 5, 2, 1)
    assert (t["asistidas"], t["presentes"], t["tarde"]) == (2, 1, 1)
    assert (t["ausentes"], t["ausentes_provisionales"], t["justificados"], t["convocatorias"]) == (1, 1, 1, 4)
    # Las justificadas, las futuras y la ausencia provisoria no entran: 2 / (4 - 1).
    assert (t["asistencia_pct"], t["puntualidad_pct"]) == (66.7, 50.0)
    assert (t["minutos_planificados"], t["minutos_realizados"], t["minutos_asistidos"]) == (420, 300, 120)
    assert (t["horas_planificadas"], t["horas_realizadas"], t["horas_asistidas"]) == (7.0, 5.0, 2.0)
    assert t["provisionales"] == 3 and tablero["provisional"] is True and tablero["estado_periodo"] == "en_curso"
    assert tablero["graficos"]["minutos"] == {"planificados": 420, "realizados": 300, "asistidos": 120, "por_realizar": 120}
    assert {g["estado"]: g["cantidad"] for g in tablero["graficos"]["estados"]} == {
        "presente": 1, "tarde": 1, "ausente": 1, "ausente_provisional": 1, "justificado": 1}
    assert [(r["nombre"], r["asistidas"], r["minutos_asistidos"]) for r in tablero["por_reunion"]] == [("Daily", 2, 120)]
    assert "asistencia_pct" in tablero["definiciones"]


def test_tarde_cuenta_la_duracion_completa(octubre):
    t = svc.estadisticas_mes(emp(10), "2026-10")["totales"]
    tarde = next(i for i in svc.calendario_mes(emp(10), "2026-10")["items"] if i["estado"] == "tarde")
    assert tarde["duracion_min"] == 60 and t["minutos_asistidos"] == 2 * 60  # sin descontar la demora


def test_calendario_dashboard_y_estadisticas_por_fechas_coinciden(octubre):
    cal = svc.calendario_mes(emp(10), "2026-10")
    tablero = svc.estadisticas_mes(emp(10), "2026-10")
    assert cal["resumen"] == tablero["totales"]
    historico = svc.estadisticas_empleado(emp(10), D(2026, 10, 1), D(2026, 10, 31))["totales"]
    for clave in ("convocatorias", "presentes", "tarde", "ausentes", "justificados", "asistidas", "asistencia_pct",
                  "puntualidad_pct", "minutos_asistidos", "horas_asistidas"):
        assert tablero["totales"][clave] == historico[clave], clave
    detalle = svc.proximas_ocurrencias(emp(10), octubre)
    assert [i["fecha"] for i in detalle] == ["2026-10-26", "2026-10-28", "2026-11-02", "2026-11-04", "2026-11-09", "2026-11-11"]
    assert all(i in cal["items"] for i in detalle[:2])


def test_al_cerrar_la_ausencia_provisoria_pasa_a_definitiva(octubre):
    svc.cerrar_ocurrencias(ahora=dt.datetime(2026, 10, 22, 12, 0), dias_atras=30)
    t = svc.estadisticas_mes(emp(10), "2026-10")["totales"]
    assert (t["ausentes"], t["ausentes_provisionales"], t["convocatorias"], t["asistencia_pct"]) == (2, 0, 5, 50.0)


def test_reunion_desactivada_conserva_su_historia(octubre):
    with svc.db.transaction() as c:
        c.execute("UPDATE reuniones SET activa=0 WHERE id=%s", (octubre,))
    cal = svc.calendario_mes(emp(10), "2026-10")
    assert [i["fecha"] for i in cal["items"]] == ["2026-10-05", "2026-10-07", "2026-10-12", "2026-10-14"]
    assert cal["resumen"]["asistidas"] == 2 and cal["resumen"]["proximas"] == 0


# --- Evolucion ---------------------------------------------------------------------------------------------

def test_evolucion_con_meses_sin_actividad_y_futuros(octubre):
    serie = svc.evolucion(emp(10), "2026-09", "2026-11")
    septiembre, octubre_mes, noviembre = serie["meses"]
    assert septiembre["planificadas"] == 0 and septiembre["asistencia_pct"] is None
    assert octubre_mes == dict(mes="2026-10", estado_periodo="en_curso", **svc.estadisticas_mes(emp(10), "2026-10")["totales"])
    assert noviembre["estado_periodo"] == "futuro" and noviembre["realizadas"] == 0 and noviembre["asistencia_pct"] is None
    assert noviembre["planificadas"] == 9 and noviembre["minutos_planificados"] == 540  # lunes y miercoles de noviembre
    assert serie["totales"]["asistidas"] == 2 and serie["limites"] == {"max_meses": 12}
    assert serie["por_reunion"][0]["planificadas"] == 7 + 9
    with pytest.raises(svc.Error, match="12 meses"):
        svc.evolucion(emp(10), "2025-10", "2026-10")
    with pytest.raises(svc.Error, match="posterior"):
        svc.evolucion(emp(10), "2026-11", "2026-10")
    assert [m["mes"] for m in svc.evolucion(emp(10))["meses"]] == ["2026-05", "2026-06", "2026-07", "2026-08",
                                                                  "2026-09", "2026-10"]


# --- Proximas ------------------------------------------------------------------------------------------------

def test_proximas_semanas_siguientes_y_sin_reuniones(reuniones_db):
    _cuando(2026, 10, 13, 8, 0)
    assert svc.proximas(emp(10), 7)["hay_proximas"] is False  # no hay ninguna reunion
    crear(nombre="Mensual", frecuencia="mensual", mensual_tipo="dia", dia_mes="5", dias_semana=[])
    semana = svc.proximas(emp(10), 7, desde=D(2026, 10, 12))
    assert semana["items"] == [] and semana["hay_proximas"] is True  # no hay esta semana, pero si mas adelante
    assert semana["proxima"]["fecha"] == "2026-11-05" and semana["zona_horaria"] == "America/Argentina/Buenos_Aires"
    cuatro = svc.proximas(emp(10), 28, desde=D(2026, 10, 12))
    assert [i["fecha"] for i in cuatro["items"]] == ["2026-11-05"] and cuatro["hasta"] == "2026-11-08"
    assert svc.proximas(emp(10), 500)["periodo"]["dias"] == svc.PROXIMAS_MAX_DIAS  # acotado


def test_aislamiento_entre_empleados_y_empresas(octubre):
    assert svc.calendario_mes(emp(14), "2026-10")["items"] == []  # misma empresa, no convocado
    assert svc.calendario_mes(emp(20), "2026-10")["items"] == []  # otra empresa
    assert svc.estadisticas_mes(emp(20), "2026-10")["totales"]["convocatorias"] == 0
    assert svc.proximas_ocurrencias(emp(14), octubre) == []


# --- API -------------------------------------------------------------------------------------------------------

def test_api_nuevas_rutas_y_compatibilidad(octubre, client):
    yo = {"Authorization": "Bearer 10"}
    base = "/api/v1/mobile/reuniones"
    cal = client.get(f"{base}/calendario?mes=2026-10", headers=yo)
    assert cal.status_code == 200 and cal.json["total"] == 8
    assert client.get(f"{base}/calendario?mes=2026-13", headers=yo).status_code == 400
    tablero = client.get(f"{base}/estadisticas?mes=2026-10", headers=yo).json
    assert tablero["totales"]["asistencia_pct"] == 66.7
    assert client.get(f"{base}/estadisticas?mes=2026-10&desde=2026-10-01", headers=yo).status_code == 400
    # Sin mes: el formato historico, igual que antes.
    historico = client.get(f"{base}/estadisticas?desde=2026-10-01&hasta=2026-10-31", headers=yo).json
    assert set(historico) == {"periodo", "totales", "por_reunion"} and historico["totales"]["horas_asistidas"] == 2.0
    evo = client.get(f"{base}/estadisticas/evolucion?desde_mes=2026-09&hasta_mes=2026-10", headers=yo).json
    assert [m["mes"] for m in evo["meses"]] == ["2026-09", "2026-10"]
    assert client.get(f"{base}/estadisticas/evolucion?desde_mes=2025-01&hasta_mes=2026-10", headers=yo).status_code == 400
    semana = client.get(f"{base}/proximas?semana=actual", headers=yo).json
    assert semana["desde"] == "2026-10-19" and semana["hasta"] == "2026-10-25"
    viejos = {"reunion_id", "nombre", "lugar", "descripcion", "sucursal_id", "sucursal_nombre", "fecha", "inicio", "fin",
              "ventana_desde", "ventana_hasta", "tarde_desde", "estado", "cancelada", "motivo_cancelacion",
              "registrado_at", "qr_modo", "fecha_original", "motivo_cambio", "superpuesta_con"}
    assert viejos <= set(semana["items"][0]) and set(semana["resumen"]) >= {"reuniones", "horas", "registradas"}
    dos = client.get(f"{base}/proximas?semanas=2", headers=yo).json
    assert (dos["desde"], dos["hasta"]) == ("2026-10-19", "2026-11-01")
    assert client.get(f"{base}/proximas?semanas=9", headers=yo).status_code == 400
    assert client.get(f"{base}/proximas?dias=0", headers=yo).status_code == 400
    detalle = client.get(f"{base}/{octubre}", headers=yo).json
    assert detalle["proximas_ocurrencias"][0]["fecha"] == "2026-10-26" and "proximas_fechas" in detalle
    assert client.get(f"{base}/calendario?mes=2026-10").status_code == 401
