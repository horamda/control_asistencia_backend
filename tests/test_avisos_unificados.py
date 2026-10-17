"""Avisos push de justificaciones, vacaciones, feedback y trivias (sin MySQL)."""
import datetime as dt
from contextlib import contextmanager
from decimal import Decimal

import pytest

from services import avisos_push as avisos
from services import push_service


@pytest.fixture
def cola(monkeypatch):
    """Firebase activo, base falsa con la fila de cada prueba y cola capturada."""
    encolados = []
    estado = {"fila": None}

    @contextmanager
    def transaction(read_only=False):
        yield None

    monkeypatch.setattr(push_service, "activo", lambda: True)
    monkeypatch.setattr(avisos.db, "transaction", transaction)
    monkeypatch.setattr(avisos.db, "one", lambda c, sql, args: estado["fila"])
    monkeypatch.setattr(push_service, "encolar_ahora",
                        lambda empresa_id, ids, tipo, titulo, cuerpo, datos=None, clave=None:
                        encolados.append(dict(empresa_id=empresa_id, ids=list(ids), tipo=tipo, titulo=titulo,
                                              cuerpo=cuerpo, datos=datos, clave=clave)) or len(ids))
    return estado, encolados


def test_justificacion_rechazada_con_motivo(cola):
    estado, encolados = cola
    estado["fila"] = dict(id=9, empleado_id=10, empresa_id=1, estado="rechazada", fecha=None,
                          fecha_desde=dt.date(2026, 10, 1), fecha_hasta=dt.date(2026, 10, 3), motivo_rechazo="Falta certificado")
    assert avisos.justificacion_resuelta(9) == 1
    aviso = encolados[0]
    assert aviso["tipo"] == "justificacion" and aviso["ids"] == [10]
    assert aviso["titulo"] == "Justificación rechazada"
    assert aviso["cuerpo"] == "Tu justificación del 01/10 al 03/10 fue rechazada. Motivo: Falta certificado"
    assert aviso["clave"] == "justificacion:9:rechazada" and aviso["datos"]["ruta"] == "/justificaciones"


def test_justificacion_pendiente_no_avisa(cola):
    estado, encolados = cola
    estado["fila"] = dict(id=9, empleado_id=10, empresa_id=1, estado="pendiente", fecha=dt.date(2026, 10, 1),
                          fecha_desde=None, fecha_hasta=None, motivo_rechazo=None)
    assert avisos.justificacion_resuelta(9) == 0 and encolados == []


def test_vacaciones_aprobadas(cola):
    estado, encolados = cola
    estado["fila"] = dict(id=4, empresa_id=1, empleado_id=10, tipo="tomado", estado="aprobado", dias=Decimal("5.00"),
                          fecha_desde=dt.date(2026, 12, 1), fecha_hasta=dt.date(2026, 12, 5), motivo_resolucion=None)
    avisos.vacaciones_resueltas(4)
    assert encolados[0]["titulo"] == "Vacaciones aprobadas"
    assert encolados[0]["cuerpo"] == "Tus vacaciones del 01/12 al 05/12 (5 días) fueron aprobadas."
    assert encolados[0]["clave"] == "vacaciones:4:aprobado"


def test_compensatorio_rechazado(cola):
    estado, encolados = cola
    estado["fila"] = dict(id=5, empresa_id=1, empleado_id=10, tipo="compensatorio", estado="rechazado", dias=Decimal("1.5"),
                          fecha_desde=None, fecha_hasta=None, motivo_resolucion="Sin saldo")
    avisos.vacaciones_resueltas(5)
    assert encolados[0]["titulo"] == "Pedido de días compensatorios rechazado"
    assert encolados[0]["cuerpo"] == "Tu pedido de días compensatorios (1,5 días) fue rechazado. Motivo: Sin saldo"


def test_feedback_asignado_al_responsable(cola):
    estado, encolados = cola
    estado["fila"] = dict(id=3, numero="FB-00000003", empresa_id=1, empleado_id=10, responsable_id=20, jefe_directo_id=20,
                          estado="pendiente", resolucion_descripcion=None, motivo="Faltante", cliente="Almacén Sol")
    avisos.feedback_asignado(3)
    assert encolados[0]["ids"] == [20] and encolados[0]["tipo"] == "feedback_asignado"
    assert encolados[0]["titulo"] == "Nuevo feedback para resolver (FB-00000003)"
    assert encolados[0]["cuerpo"] == "Faltante · Almacén Sol"


def test_feedback_propio_no_se_avisa_a_si_mismo(cola):
    estado, encolados = cola
    estado["fila"] = dict(id=3, numero="FB-00000003", empresa_id=1, empleado_id=20, responsable_id=20, jefe_directo_id=20,
                          estado="pendiente", resolucion_descripcion=None, motivo="Faltante", cliente=None)
    assert avisos.feedback_asignado(3) == 0 and encolados == []


def test_feedback_resuelto_al_que_lo_cargo(cola):
    estado, encolados = cola
    estado["fila"] = dict(id=3, numero="FB-00000003", empresa_id=1, empleado_id=10, responsable_id=20, jefe_directo_id=20,
                          estado="resuelto", resolucion_descripcion="Se repuso la mercadería.", motivo="Faltante",
                          cliente="Almacén Sol")
    avisos.feedback_resuelto(3)
    assert encolados[0]["ids"] == [10]
    assert encolados[0]["cuerpo"] == "Tu feedback FB-00000003 sobre Almacén Sol fue resuelto. Se repuso la mercadería."


def test_trivia_agrupa_por_empresa(cola):
    _, encolados = cola
    empleados = [dict(empleado_id=10, empresa_id=1), dict(empleado_id=11, empresa_id=1), dict(empleado_id=30, empresa_id=2)]
    assert avisos.trivia({"id": 7, "titulo": "Seguridad vial"}, empleados, "recordatorio_2h") == 3
    assert {(a["empresa_id"], tuple(a["ids"])) for a in encolados} == {(1, (10, 11)), (2, (30,))}
    assert all(a["tipo"] == "trivia_recordatorio" and a["clave"] == "trivia:7:recordatorio_2h" for a in encolados)
    assert encolados[0]["cuerpo"] == "¡Quedan 2 horas para participar en «Seguridad vial»!"


def test_sin_firebase_no_consulta_nada(monkeypatch):
    monkeypatch.setattr(push_service, "activo", lambda: False)
    monkeypatch.setattr(avisos.db, "transaction", lambda **k: (_ for _ in ()).throw(AssertionError("no debe consultar")))
    assert avisos.justificacion_resuelta(1) == 0


# --- Trivia: que aviso corresponde en cada momento ---------------------------------------------------

@pytest.mark.parametrize("inicio_hace,fin_en,esperado,guarda_bandeja", [
    (dt.timedelta(hours=1), dt.timedelta(days=3), "nueva", False),            # recien abierta
    (dt.timedelta(days=2), dt.timedelta(days=3), None, False),                # ni nueva ni por cerrar
    (dt.timedelta(days=2), dt.timedelta(hours=20), "recordatorio_24h", True),
    (dt.timedelta(hours=1), dt.timedelta(hours=1), "recordatorio_2h", True),  # corta: solo el mas urgente
])
def test_momento_del_aviso_de_trivia(monkeypatch, inicio_hace, fin_en, esperado, guarda_bandeja):
    from services import trivia_service as svc

    ahora = dt.datetime(2026, 10, 16, 12, 0)
    monkeypatch.setattr(svc, "_now", lambda: ahora)
    monkeypatch.setattr(svc.repo, "get_trivia_by_id", lambda tid: {
        "id": tid, "titulo": "Seguridad vial", "estado": "activa",
        "fecha_inicio": ahora - inicio_hace, "fecha_fin": ahora + fin_en})
    monkeypatch.setattr(svc.repo, "get_empleados_sin_participar",
                        lambda tid: [{"empleado_id": 10, "empleado_dni": "1", "empresa_id": 1}])
    guardadas, avisados = [], []
    monkeypatch.setattr(svc.repo, "save_notificaciones_batch", lambda filas: guardadas.extend(filas))
    monkeypatch.setattr(svc.avisos_push, "trivia", lambda t, emps, momento: avisados.append(momento))

    svc.generar_notificaciones(7)

    assert avisados == ([esperado] if esperado else [])
    assert bool(guardadas) == guarda_bandeja


# --- Para RR. HH.: solicitudes para revisar -----------------------------------------------------------

@pytest.fixture
def revisores(cola, monkeypatch):
    """Usuarios del panel: 1 (empleado 50) aprueba, 2 (empleado 51) no, 3 (empleado 10) es el que pide."""
    import web.auth.decorators as auth

    monkeypatch.setattr(avisos.db, "all_rows", lambda c, sql, args: [
        {"usuario_id": 1, "empleado_id": 50}, {"usuario_id": 2, "empleado_id": 51}, {"usuario_id": 3, "empleado_id": 10}])
    monkeypatch.setattr(auth, "can_access_module", lambda uid, modulo, accion: uid in (1, 3) and accion == "aprobar")
    return cola


def test_justificacion_para_revisar_va_a_quien_aprueba_y_no_al_que_pide(revisores):
    estado, encolados = revisores
    estado["fila"] = dict(id=9, empleado_id=10, empresa_id=1, apellido="Perez", nombre="Ana", estado="pendiente",
                          fecha=None, fecha_desde=dt.date(2026, 10, 1), fecha_hasta=dt.date(2026, 10, 1), motivo="Turno médico")
    assert avisos.revision_justificacion(9) == 1
    aviso = encolados[0]
    assert aviso["ids"] == [50] and aviso["tipo"] == "revision_pendiente"
    assert aviso["titulo"] == "Justificación para revisar"
    assert aviso["cuerpo"] == "Perez Ana del 01/10 · Turno médico"
    assert aviso["datos"]["modulo"] == "justificaciones" and aviso["clave"] == "revision:justificaciones:9"


def test_epp_en_borrador_no_avisa(revisores):
    estado, encolados = revisores
    estado["fila"] = dict(id=4, empresa_id=1, empleado_id=10, apellido="Perez", nombre="Ana", estado="borrador", revision=1)
    assert avisos.revision_epp(4) == 0 and encolados == []


def test_viaticos_reenviados_avisan_de_nuevo(revisores):
    estado, encolados = revisores
    fila = dict(id=8, empresa_id=1, empleado_id=10, apellido="Perez", nombre="Ana", estado="pendiente",
                total_solicitado=Decimal("15300.5"))
    for revision in (1, 2):
        estado["fila"] = dict(fila, revision=revision)
        avisos.revision_reintegro(8)
    assert [a["clave"] for a in encolados] == ["revision:reintegros:8:r1", "revision:reintegros:8:r2"]
    assert encolados[0]["cuerpo"] == "Perez Ana · rendición N° 8 por $ 15.300,50"


def test_sin_revisores_no_encola(revisores, monkeypatch):
    import web.auth.decorators as auth

    estado, encolados = revisores
    monkeypatch.setattr(auth, "can_access_module", lambda *a: False)
    estado["fila"] = dict(id=3, empresa_id=1, empleado_id=10, apellido="Perez", nombre="Ana", estado="pendiente",
                          periodo_month=10)
    assert avisos.revision_adelanto(3) == 0 and encolados == []
