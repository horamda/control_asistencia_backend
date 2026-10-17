"""Bandeja de notificaciones del empleado (campana): alta junto al push, deduplicacion, lecturas y API mobile.

Las pruebas con base usan MySQL real (SH_TEST_DB_PORT, como el resto de push y comunicados); las de logica pura no."""
import datetime as dt
import json
from pathlib import Path

import pytest
from flask import Flask

from services import comunicado_service as com
from services import notificaciones_service as noti
from services import push_service as push
from services import reunion_service as svc
from tests.test_avisos_comunicados import base  # noqa: F401  (fixture)
from tests.test_push import _envios, clave_rsa, firebase, push_db  # noqa: F401  (fixtures)
from tests.test_reuniones import ADMIN, emp, reuniones_db  # noqa: F401
from tests.test_seguridad import database  # noqa: F401

ADELANTO = ("adelanto", "Adelanto aprobado", "Tu pedido de adelanto de octubre fue aprobado.")


def _avisar(eid, n=1, tipo=ADELANTO, empresa_id=1, **extra):
    """Un evento de adelanto resuelto (id n) para el empleado eid, por el mismo camino que usan los modulos."""
    datos = {"adelanto_id": n, "estado": "aprobado", "ruta": "/adelantos"}
    return push.encolar_ahora(empresa_id, [eid], tipo[0], tipo[1], tipo[2], datos, f"adelanto:{n}:aprobado", **extra)


def _notas(eid=None):
    with svc.db.transaction(read_only=True) as c:
        sql = "SELECT * FROM empleado_notificaciones" + (" WHERE empleado_id=%s" if eid else "") + " ORDER BY id"
        return svc.db.all_rows(c, sql, (eid,) if eid else ())


def _sql(sql, args=()):
    with svc.db.transaction() as c:
        c.execute(sql, args)
        return c.lastrowid


# --- Alta: una notificacion por evento, con o sin push ------------------------------------------------

def test_evento_crea_la_notificacion_y_el_push_lleva_su_id(base):
    assert _avisar(10, 5) == 1
    [nota] = _notas(10)
    assert (nota["empresa_id"], nota["tipo"], nota["modulo"], nota["titulo"]) == (1, "adelanto", "adelantos", "Adelanto aprobado")
    assert (nota["referencia_tipo"], nota["referencia_id"], nota["ruta"], nota["leido_at"]) == ("adelanto", 5, "/adelantos", None)
    assert nota["clave"] == "adelanto:5:aprobado"
    [envio] = _envios()
    assert json.loads(envio["datos"])["notificacion_id"] == str(nota["id"])


def test_mismo_evento_y_reintentos_del_push_no_duplican(base):
    assert _avisar(10, 5) == 1
    assert _avisar(10, 5) == 0  # el modulo avisa dos veces el mismo evento
    fallos = []

    def falla(cred, token, titulo, cuerpo, datos):
        fallos.append(datos["notificacion_id"])
        return False, "503 UNAVAILABLE", False

    for _ in range(push.MAX_INTENTOS + 1):
        push.procesar_cola(enviar=falla)
    assert [e["estado"] for e in _envios()] == ["error"] and len(fallos) == push.MAX_INTENTOS
    # El push fallo del todo: la notificacion sigue ahi, una sola y sin leer.
    bandeja = noti.listado(emp(10))
    assert len(bandeja["items"]) == 1 and bandeja["no_leidas"] == 1 and len(_notas()) == 1


def test_sin_firebase_la_bandeja_funciona_igual(base, monkeypatch):
    monkeypatch.delenv("FIREBASE_SERVICE_ACCOUNT")
    assert _avisar(10, 5) == 1
    assert _envios() == []
    assert noti.resumen(emp(10)) == {"no_leidas": 1, "por_modulo": {"adelantos": 1}, "ultima_id": _notas(10)[0]["id"]}


def test_empleado_sin_dispositivo_igual_tiene_la_notificacion(base):
    assert _avisar(14, 5) == 1  # el 14 no tiene la app con notificaciones
    assert push.procesar_cola()["sin_dispositivo"] == 1
    assert noti.listado(emp(14))["no_leidas"] == 1


def test_regla_desactivada_por_la_empresa_no_crea_nada(base, monkeypatch):
    monkeypatch.setattr(push.reglas_push, "planificar", lambda empresa_id, clave: (False, None, None))
    assert _avisar(10, 5) == 0
    assert _notas() == [] and _envios() == []


def test_silencio_demora_el_push_pero_no_la_bandeja(base, monkeypatch):
    despues = dt.datetime.now() + dt.timedelta(hours=8)
    monkeypatch.setattr(push.reglas_push, "planificar", lambda empresa_id, clave: (True, despues, None))
    assert _avisar(10, 5) == 1
    assert noti.listado(emp(10))["no_leidas"] == 1
    assert push.procesar_cola() == {"enviados": 0, "errores": 0, "sin_dispositivo": 0}  # todavia no es la hora


def test_recordatorios_salen_solo_por_push(base):
    with svc.db.transaction() as c:
        push.encolar(c, 1, [10], "recordatorio", "Reunión a las 11", "Empieza en 15 min", {"reunion_id": 1}, "rec:1")
        push.encolar(c, 1, [10], "seguridad_accion", "Acción por vencer", "Vence mañana", {"accion_id": 1}, "sh:1:vence",
                     bandeja=False)
    assert _notas() == []
    assert [json.loads(e["datos"]).get("notificacion_id") for e in _envios()] == [None, None]


def test_resumen_de_varios_avisos_no_lleva_un_solo_notificacion_id():
    envios = [dict(tipo="revision_pendiente", titulo="Vacaciones para revisar", cuerpo="Ana", lote="l", empleado_id=10,
                   datos=json.dumps({"notificacion_id": "7", "ruta": "/revisiones/vacaciones"})),
              dict(tipo="revision_pendiente", titulo="Justificación para revisar", cuerpo="Luis", lote="l", empleado_id=10,
                   datos=json.dumps({"notificacion_id": "8", "ruta": "/revisiones/justificaciones"}))]
    titulo, _, datos = push._contenido(envios)
    assert titulo == "Tenés 2 solicitudes para revisar" and "notificacion_id" not in datos and datos["cantidad"] == 2
    assert push._contenido(envios[:1])[2]["notificacion_id"] == "7"


def test_catalogo_de_eventos():
    assert noti.en_bandeja("comunicado") and noti.en_bandeja("feedback_resuelto") and noti.en_bandeja("reunion_cambio")
    for tipo in ("recordatorio", "salida_pendiente", "trivia_recordatorio", "reintegro_recordatorio", "prueba", "desconocido"):
        assert not noti.en_bandeja(tipo)
    assert noti._referencia("revision_pendiente", {"modulo": "pedidos_empleados", "registro_id": "4"},
                            "revision:adelanto:4") == ("revisiones", "adelanto", 4)
    assert noti._referencia("revision_pendiente", {"modulo": "pedidos_empleados", "registro_id": "4"},
                            "revision:mercaderia:4") == ("revisiones", "pedido_mercaderia", 4)
    assert noti._referencia("feedback_asignado", {"ruta": "/feedback/3"}, "x") == ("feedback", None, None)


# --- Aislamiento -------------------------------------------------------------------------------------------

def test_cada_empleado_ve_y_lee_solo_lo_suyo(base):
    _avisar(10, 1)
    _avisar(11, 2)
    _avisar(20, 3, empresa_id=2)  # otra empresa
    propia, ajena = _notas(10)[0]["id"], _notas(11)[0]["id"]
    assert [i["id"] for i in noti.listado(emp(10))["items"]] == [propia]
    for accion in (noti.detalle, noti.leer):
        with pytest.raises(noti.Error) as error:
            accion(emp(10), ajena)
        assert error.value.status == 404
    assert noti.leer_todas(emp(10), 10**9)["marcadas"] == 1
    assert noti.listado(emp(11))["no_leidas"] == 1 and noti.listado(emp(20))["no_leidas"] == 1
    # Una fila con la empresa equivocada no aparece aunque coincida el empleado (empresa y empleado salen del token).
    _sql("""INSERT INTO empleado_notificaciones (empresa_id, empleado_id, tipo, modulo, titulo, mensaje, clave, creado_at)
            VALUES (1, 20, 'adelanto', 'adelantos', 'x', 'x', 'otra-empresa', NOW())""")
    assert noti.listado(emp(20))["no_leidas"] == 1


# --- Lecturas -------------------------------------------------------------------------------------------

def test_lectura_individual_idempotente_y_compartida_entre_dispositivos(base):
    _avisar(10, 1)
    _avisar(10, 2)
    primera = noti.listado(emp(10))["items"][0]
    leida = noti.leer(emp(10), primera["id"])
    assert leida["leida"] is True and leida["no_leidas"] == 1
    otra_vez = noti.leer(emp(10), primera["id"])  # el otro celular, o un doble toque
    assert otra_vez["leido_at"] == leida["leido_at"] and otra_vez["no_leidas"] == 1
    # El otro dispositivo (o la web) consulta despues: ve la misma lectura, porque vive en el servidor.
    desde_otro = noti.listado(emp(10))
    assert desde_otro["no_leidas"] == 1 and [i["leida"] for i in desde_otro["items"]] == [True, False]


def test_leer_todas_respeta_el_corte_si_llega_una_nueva_en_el_medio(base):
    _avisar(10, 1)
    _avisar(10, 2)
    listado = noti.listado(emp(10))
    assert listado["corte"] == listado["items"][0]["id"]
    _avisar(10, 3)  # llega mientras el empleado mira la bandeja
    resultado = noti.leer_todas(emp(10), listado["corte"])
    assert resultado == {"marcadas": 2, "no_leidas": 1, "hasta_id": listado["corte"]}
    assert noti.leer_todas(emp(10), listado["corte"])["marcadas"] == 0  # idempotente
    assert [i["leida"] for i in noti.listado(emp(10))["items"]] == [False, True, True]
    with pytest.raises(noti.Error, match="hasta_id"):
        noti.leer_todas(emp(10), None)


def test_listado_paginado_con_filtros_no_marca_nada(base):
    for n in range(1, 4):
        _avisar(10, n)
    with svc.db.transaction() as c:
        push.encolar(c, 1, [10], "feedback_resuelto", "Feedback resuelto", "Tu feedback 12 fue resuelto.",
                     {"feedback_id": 12, "ruta": "/feedback/12"}, "feedback:12:resuelto")
    pagina = noti.listado(emp(10), limite=2)
    assert len(pagina["items"]) == 2 and pagina["siguiente"] == pagina["items"][-1]["id"]
    resto = noti.listado(emp(10), limite=2, antes_de=pagina["siguiente"])
    assert len(resto["items"]) == 2 and resto["siguiente"] is None
    ids = [i["id"] for i in pagina["items"] + resto["items"]]
    assert ids == sorted(ids, reverse=True)  # de la mas nueva a la mas vieja, sin repetir
    assert [i["modulo"] for i in noti.listado(emp(10), modulo="feedback")["items"]] == ["feedback"]
    assert noti.listado(emp(10), estado="leidas")["items"] == []
    assert noti.listado(emp(10))["no_leidas"] == 4  # consultar no marca como leido
    with pytest.raises(noti.Error, match="Módulo"):
        noti.listado(emp(10), modulo="fichadas")


def test_detalle_avisa_si_el_tramite_ya_no_esta(base):
    adelanto = _sql("INSERT INTO adelantos (empresa_id, empleado_id, estado, periodo_month) VALUES (1, 10, 'aprobado', 10)")
    _avisar(10, adelanto)
    nota = _notas(10)[0]
    detalle = noti.detalle(emp(10), nota["id"])
    assert detalle["referencia"] == {"tipo": "adelanto", "id": adelanto, "disponible": True}
    assert detalle["leida"] is False  # ver el detalle no marca como leido
    _sql("DELETE FROM adelantos WHERE id=%s", (adelanto,))
    detalle = noti.detalle(emp(10), nota["id"])
    assert detalle["referencia"]["disponible"] is False and detalle["titulo"] == "Adelanto aprobado"
    # Leer la notificacion no cambia el tramite: solo la marca.
    _sql("INSERT INTO adelantos (id, empresa_id, empleado_id, estado, periodo_month) VALUES (%s, 1, 11, 'aprobado', 10)",
         (adelanto,))
    assert noti.detalle(emp(10), nota["id"])["referencia"]["disponible"] is False  # ahora es de otro empleado
    noti.leer(emp(10), nota["id"])
    with svc.db.transaction(read_only=True) as c:
        assert svc.db.one(c, "SELECT estado FROM adelantos WHERE id=%s", (adelanto,))["estado"] == "aprobado"


# --- Comunicados: compatibilidad y lecturas -------------------------------------------------------------

def test_comunicados_sincronizan_lectura_en_los_dos_sentidos(base):
    cid, total = com.enviar(ADMIN, dict(titulo="Corte de luz", mensaje="El jueves no hay luz.", reglas=["todos"]))
    assert total == 5
    assert sorted(n["empleado_id"] for n in _notas() if n["referencia_tipo"] == "comunicado") == [10, 11, 12, 13, 14]
    # Endpoint viejo (GET /comunicados/{id}) -> leida en la bandeja.
    com.leer(emp(10), cid)
    assert _notas(10)[0]["leido_at"] is not None
    # Bandeja nueva -> leido en Comunicados.
    noti.leer(emp(11), _notas(11)[0]["id"])
    assert com.mis_comunicados(emp(11))["no_leidos"] == 0
    # Leer todas en la bandeja nueva marca el comunicado; leer-todos de comunicados marca la bandeja.
    noti.leer_todas(emp(12), noti.listado(emp(12))["corte"])
    assert com.mis_comunicados(emp(12))["no_leidos"] == 0
    assert com.leer_todos(emp(13)) == 1 and noti.listado(emp(13))["no_leidas"] == 0
    # Borrar el comunicado desde el panel lo saca tambien de la campana.
    com.eliminar(ADMIN, cid)
    assert [n for n in _notas() if n["referencia_tipo"] == "comunicado"] == []


def test_migracion_copia_comunicados_con_su_lectura_sin_push_ni_tramites(base):
    cid = _sql("""INSERT INTO comunicados (empresa_id, titulo, mensaje, alcance, destinatarios, creado_at)
                  VALUES (1, 'Uniforme', %s, 'Toda la empresa', 2, '2026-10-16 10:00:00')""", ("x" * 300,))
    _sql("INSERT INTO comunicado_destinatarios (comunicado_id, empleado_id, leido_at) VALUES (%s, 10, '2026-10-16 11:00:00')", (cid,))
    _sql("INSERT INTO comunicado_destinatarios (comunicado_id, empleado_id) VALUES (%s, 11)", (cid,))
    _sql("INSERT INTO adelantos (empresa_id, empleado_id, estado, periodo_month) VALUES (1, 10, 'aprobado', 10)")
    from scripts.migrate_20261017_02_notificaciones import migrate_cursor
    for _ in range(2):  # idempotente
        with svc.db.transaction() as c:
            migrate_cursor(c)
    notas = _notas()
    assert [(n["empleado_id"], n["tipo"], n["referencia_id"]) for n in notas] == [(10, "comunicado", cid), (11, "comunicado", cid)]
    assert str(notas[0]["leido_at"]) == "2026-10-16 11:00:00" and notas[1]["leido_at"] is None
    assert str(notas[0]["creado_at"]) == "2026-10-16 10:00:00" and len(notas[0]["mensaje"]) == 178
    assert _envios() == []  # sin push masivo
    # Despues de migrar, un push nuevo del mismo comunicado no duplica la entrada.
    with svc.db.transaction() as c:
        push.encolar(c, 1, [10, 11], "comunicado", "Uniforme", "x", {"comunicado_id": cid}, f"comunicado:{cid}")
    assert len(_notas()) == 2


# --- API mobile -----------------------------------------------------------------------------------------

@pytest.fixture
def client(base, monkeypatch):
    import routes.carga_routes as carga_routes
    import utils.jwt_guard as jwt_guard
    from routes import notificaciones_routes

    app = Flask(__name__, template_folder=str(Path(__file__).resolve().parents[1] / "templates"))
    app.register_blueprint(notificaciones_routes.mobile)
    monkeypatch.setattr(jwt_guard, "verificar_token", lambda token: dict(empleado_id=int(token)))
    monkeypatch.setattr(carga_routes, "get_by_id", emp)
    return app.test_client()


def test_api_mobile(client):
    _avisar(10, 1)
    _avisar(10, 2)
    _avisar(11, 3)
    yo, otro = {"Authorization": "Bearer 10"}, {"Authorization": "Bearer 11"}
    url = "/api/v1/mobile/me/notificaciones"
    assert client.get(url).status_code == 401
    listado = client.get(url, headers=yo).json
    assert listado["no_leidas"] == 2 and len(listado["items"]) == 2
    item = listado["items"][0]
    assert set(item) == {"id", "tipo", "modulo", "titulo", "mensaje", "creado_at", "leida", "leido_at", "referencia", "destino"}
    assert item["destino"] == {"ruta": "/adelantos", "parametros": {"adelanto_id": "2", "estado": "aprobado"}}
    assert client.get(f"{url}/resumen", headers=yo).json["no_leidas"] == 2
    assert client.get(f"{url}/{item['id']}", headers=otro).status_code == 404
    assert client.get(f"{url}/{item['id']}", headers=yo).json["referencia"]["disponible"] is False  # sin la fila del adelanto
    leida = client.post(f"{url}/{item['id']}/leer", headers=yo).json
    assert leida["leida"] is True and leida["no_leidas"] == 1
    assert client.post(f"{url}/leer-todas", headers=yo, json={}).status_code == 400
    todas = client.post(f"{url}/leer-todas", headers=yo, json={"hasta_id": listado["corte"]}).json
    assert todas == {"marcadas": 1, "no_leidas": 0, "hasta_id": listado["corte"]}
    assert client.get(f"{url}?estado=no_leidas", headers=otro).json["no_leidas"] == 1
    assert client.get(f"{url}?estado=raro", headers=yo).status_code == 400
