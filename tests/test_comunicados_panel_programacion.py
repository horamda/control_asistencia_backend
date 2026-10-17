"""Panel: programar desde Nuevo comunicado, pestaña Programados y Configuración de avisos (sin MySQL)."""
import datetime as dt

import pytest

import app as app_module
import web.auth.decorators as auth_decorators
import web.comunicados.routes as rutas

USUARIO = {"id": 9, "empresa_id": 1, "activo": 1, "rol": "admin"}


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(app_module, "init_db", lambda: None)
    app = app_module.create_app()
    app.config.update(TESTING=True, WTF_CSRF_ENABLED=False)
    client = app.test_client()
    with client.session_transaction() as sess:
        sess["user_id"] = 9
    monkeypatch.setattr(auth_decorators, "can_access_module", lambda *a, **k: True)
    monkeypatch.setattr(auth_decorators, "has_role", lambda *a, **k: True)
    monkeypatch.setattr(auth_decorators, "_cached_web_user", lambda user_id: USUARIO)
    monkeypatch.setattr(rutas, "_cached_web_user", lambda user_id: USUARIO)
    monkeypatch.setattr(rutas, "log_audit", lambda *a, **k: None)
    monkeypatch.setattr(rutas, "_contexto_destinatarios", lambda actor, data=None: dict(
        sucursales=[], eligibility=dict(sectores=[], cualquier_sector=[]), empleados=[], marcados=set(),
        todos=False, cobertura=[]))
    return client


def test_formulario_tiene_la_opcion_de_programar(client):
    html = client.get("/comunicados/nuevo").get_data(as_text=True)
    assert 'name="cuando" value="programar"' in html and 'name="frecuencia"' in html
    assert "Programados" in html and "Configuración de avisos" in html


def test_programar_redirige_a_programados(client, monkeypatch):
    pedido = {}

    def programar(actor, data, form, imagen, base_url=None):
        pedido.update(actor=actor, frecuencia=form.get("frecuencia"), dias=form.getlist("dias_semana"), base_url=base_url)
        return 5, dt.datetime(2026, 10, 19, 9, 0)

    monkeypatch.setattr(rutas.programados, "programar", programar)
    resp = client.post("/comunicados/nuevo", data={"titulo": "Pausa", "mensaje": "A las 10", "regla": "todos",
                                                   "cuando": "programar", "frecuencia": "semanal", "hora": "09:00",
                                                   "dias_semana": ["1", "4"]})
    assert resp.status_code == 302 and resp.headers["Location"].endswith("/comunicados/programados")
    assert pedido["frecuencia"] == "semanal" and pedido["dias"] == ["1", "4"]
    assert pedido["base_url"].startswith("http://localhost")
    with client.session_transaction() as sess:
        assert ("success", "Comunicado programado. Primer envío: 19/10/2026 a las 09:00.") in sess["_flashes"]


def test_error_al_programar_vuelve_al_formulario_con_lo_cargado(client, monkeypatch):
    def programar(*a, **k):
        raise rutas.s.Error("Elegí al menos un día de la semana.")

    monkeypatch.setattr(rutas.programados, "programar", programar)
    resp = client.post("/comunicados/nuevo", data={"titulo": "Pausa", "mensaje": "A las 10", "regla": "todos",
                                                   "cuando": "programar", "frecuencia": "semanal", "hora": "07:45"})
    html = resp.get_data(as_text=True)
    assert resp.status_code == 400
    assert 'value="programar" data-com-cuando-opcion checked' in html and 'value="07:45"' in html


def test_pagina_de_programados(client, monkeypatch):
    monkeypatch.setattr(rutas.programados, "listado", lambda who: dict(programados=[dict(
        id=1, titulo="Pausa activa", mensaje="A las 10", alcance="Toda la empresa", descripcion="Todos los días a las 10:00",
        envios=2, proximo_envio=dt.datetime(2026, 10, 18, 10, 0), ultimo_envio=None, estado="activo", tiene_imagen=False)]))
    html = client.get("/comunicados/programados").get_data(as_text=True)
    assert "Pausa activa" in html and "18/10/2026 10:00" in html and "Pausar" in html


def test_configuracion_se_muestra_y_se_guarda(client, monkeypatch):
    reglas = rutas.reglas_push
    monkeypatch.setattr(reglas, "_leer", lambda empresa_id: (
        {m["clave"]: reglas._defecto(m) for m in reglas.CATALOGO}, (None, None)))
    monkeypatch.setattr(rutas.avisos_push, "cobertura", lambda empresa_id: dict(
        empleados=3, sin_jefe=[dict(id=12, nombre="Sosa Juan", legajo="12", motivo=None)], jefes=1, jefes_sin_app=[],
        aprobadores=1, sin_vincular=[dict(id=1, usuario="rrhh", modulos=["Vacaciones"], motivo=None)], aprobadores_sin_app=[]))
    html = client.get("/comunicados/configuracion").get_data(as_text=True)
    assert "Solicitudes para revisar" in html and "Responsable de Seguridad e Higiene" in html
    assert "¿Llegan los avisos?" in html and "Sosa Juan" in html and "/empleados/editar/12" in html
    assert "/usuarios/editar/1" in html and "Todos los jefes tienen la app" in html
    assert 'name="parametro:salida_pendiente" value="30"' in html

    guardado = {}
    monkeypatch.setattr(reglas, "guardar", lambda actor, form: guardado.update(form=form) or 1)
    resp = client.post("/comunicados/configuracion", data={"silencio_desde": "22:00", "silencio_hasta": "07:00"})
    assert resp.status_code == 302 and guardado["form"]["silencio_desde"] == "22:00"


def test_configuracion_se_muestra_aunque_falle_la_cobertura(client, monkeypatch):
    reglas = rutas.reglas_push
    monkeypatch.setattr(reglas, "_leer", lambda empresa_id: (
        {m["clave"]: reglas._defecto(m) for m in reglas.CATALOGO}, (None, None)))
    monkeypatch.setattr(rutas.avisos_push, "cobertura", lambda empresa_id: 1 / 0)
    resp = client.get("/comunicados/configuracion")
    assert resp.status_code == 200 and "¿Llegan los avisos?" not in resp.get_data(as_text=True)
