"""Rutas del panel: generador de trivias con IA y Configuración de IA. Sin base ni proveedor real."""
import datetime
import io
import json

import pytest

import app as app_module
import web.auth.decorators as auth
import web.configuracion.ia_config_routes as cfg_routes
import web.trivias.trivia_admin_routes as admin_routes
import web.trivias.trivia_ia_routes as ia_routes
from services import ia_config_service as ia_config
from services import ia_proveedores as prov
from services import trivia_ia_service as gen

TEXTO = ("Todo el personal debe usar casco y calzado de seguridad antes de cruzar la línea amarilla. "
         "El límite de velocidad de los autoelevadores es de 10 km/h. Ante un derrame se debe avisar "
         "al supervisor de turno y señalizar la zona con conos naranjas.")

CFG = {
    "proveedor": "anthropic", "modelo": "claude-opus-5-5", "trivias_activa": True, "configurado": True,
    "disponible": True, "modelos": {"anthropic": "claude-opus-5-5", "openai": "", "gemini": ""},
    "precios": {p: {"entrada": 0.0, "salida": 0.0} for p in prov.PROVEEDORES},
    "max_preguntas": 20, "max_generaciones_dia": 30, "max_caracteres": 60000, "max_archivo_mb": 10,
    "presupuesto_mensual_usd": 0.0,
}

PREGUNTA = {"texto": "¿Velocidad máxima?", "opcion_a": "5 km/h", "opcion_b": "10 km/h",
            "opcion_c": "15 km/h", "opcion_d": "20 km/h", "respuesta_correcta": "B", "puntos": 10}


def _client(monkeypatch, rol="admin", cfg=None):
    monkeypatch.setattr(app_module, "init_db", lambda: None)
    monkeypatch.setattr(auth, "_cached_web_user", lambda *a: {"id": 99, "rol": rol, "activo": 1})
    monkeypatch.setattr(auth, "_cached_user_permissions", lambda *a: {})
    monkeypatch.setattr(admin_routes, "_get_sectores", lambda: [{"id": 1, "nombre": "Depósito"}])
    monkeypatch.setattr(ia_config, "cargar", lambda: dict(cfg or CFG))
    app = app_module.create_app()
    app.config.update(TESTING=True, WTF_CSRF_ENABLED=False)
    client = app.test_client()
    with client.session_transaction() as s:
        s["user_id"] = 99
        s["role"] = rol
    gen._lock_usuarios.clear()
    return client


@pytest.fixture
def client(monkeypatch):
    return _client(monkeypatch)


def _token(client):
    client.get("/admin/trivias/ia/")
    with client.session_transaction() as s:
        return s["trivia_ia_token"]


def _form_guardar(token, preguntas=(PREGUNTA,), **extra):
    data = {"token": token, "titulo": "Seguridad", "fecha_inicio": "2026-12-01T08:00",
            "fecha_fin": "2026-12-05T20:00", "estado": "programada", "anio": "2026",
            "sector_ids": ["1"], "preguntas_json": json.dumps(list(preguntas))}
    data.update(extra)
    return data


# ---------------------------------------------------------------------------
# Pantalla y permisos
# ---------------------------------------------------------------------------

def test_listado_muestra_ambos_botones(client, monkeypatch):
    monkeypatch.setattr(admin_routes.repo, "get_trivias_page", lambda *a, **k: ([], 0))
    html = client.get("/admin/trivias/").get_data(as_text=True)
    assert "Generar con IA" in html and "+ Nueva trivia" in html


def test_pagina_generador_reutiliza_los_campos_de_trivia(client):
    html = client.get("/admin/trivias/ia/").get_data(as_text=True)
    assert 'name="fecha_inicio"' in html and 'name="sector_ids"' in html and "Depósito" in html
    assert "Generar preguntas" in html


def test_alta_manual_sigue_igual(client):
    html = client.get("/admin/trivias/nueva").get_data(as_text=True)
    assert 'name="titulo"' in html and 'name="sector_ids"' in html and "Crear trivia" in html


def test_ia_desactivada_ofrece_crear_manual(monkeypatch):
    client = _client(monkeypatch, cfg={**CFG, "trivias_activa": False, "disponible": False})
    html = client.get("/admin/trivias/ia/").get_data(as_text=True)
    assert "desactivada" in html and "crear la trivia manualmente" in html
    assert 'id="ia-generar"' not in html
    r = client.post("/admin/trivias/ia/generar", data={"texto": TEXTO, "cantidad": "1"})
    assert r.status_code == 409 and r.get_json()["tipo"] == "limite"


@pytest.mark.parametrize("metodo,ruta", [
    ("get", "/admin/trivias/ia/"), ("post", "/admin/trivias/ia/generar"), ("post", "/admin/trivias/ia/guardar"),
    ("get", "/configuracion-ia/"), ("post", "/configuracion-ia/guardar"),
    ("post", "/configuracion-ia/probar"), ("post", "/configuracion-ia/modelos"),
])
def test_empleado_sin_permisos_recibe_403(monkeypatch, metodo, ruta):
    client = _client(monkeypatch, rol="empleado")
    assert getattr(client, metodo)(ruta).status_code == 403


def test_rrhh_usa_el_generador_pero_no_la_configuracion(monkeypatch):
    client = _client(monkeypatch, rol="rrhh")
    assert client.get("/admin/trivias/ia/").status_code == 200
    assert client.get("/configuracion-ia/").status_code == 403


def test_sin_sesion_redirige_al_login(monkeypatch):
    client = _client(monkeypatch)
    with client.session_transaction() as s:
        s.clear()
    assert client.get("/admin/trivias/ia/").status_code == 302


# ---------------------------------------------------------------------------
# Generar
# ---------------------------------------------------------------------------

def test_generar_desde_texto(client, monkeypatch):
    llamadas = []

    def generar(cfg, contenido, **kw):
        llamadas.append((contenido.origen, kw))
        return {"preguntas": [PREGUNTA], "pedidas": 1, "descartadas": 0, "origen": contenido.origen}
    monkeypatch.setattr(gen, "generar", generar)
    r = client.post("/admin/trivias/ia/generar", data={
        "modo": "texto", "texto": TEXTO, "cantidad": "1", "dificultad": "facil", "titulo": "T",
        "operacion": "regenerar", "evitar": json.dumps(["Otra"])})
    assert r.status_code == 200 and r.get_json()["preguntas"] == [PREGUNTA]
    origen, kw = llamadas[0]
    assert origen == "texto" and kw["cantidad"] == 1 and kw["dificultad"] == "facil"
    assert kw["operacion"] == "regenerar" and kw["evitar"] == ["Otra"] and kw["usuario_id"] == 99


@pytest.mark.parametrize("nombre,data,origen", [
    ("proc.txt", TEXTO.encode(), "txt"),
])
def test_generar_desde_archivo(client, monkeypatch, nombre, data, origen):
    monkeypatch.setattr(gen, "generar", lambda cfg, c, **kw: {"preguntas": [PREGUNTA], "pedidas": 1,
                                                             "descartadas": 0, "origen": c.origen})
    r = client.post("/admin/trivias/ia/generar", content_type="multipart/form-data",
                    data={"modo": "archivo", "cantidad": "1", "archivo": (io.BytesIO(data), nombre)})
    assert r.status_code == 200 and r.get_json()["origen"] == origen


@pytest.mark.parametrize("data,mensaje", [
    ({"modo": "texto", "texto": "corto", "cantidad": "1"}, "demasiado corto"),
    ({"modo": "texto", "texto": TEXTO, "cantidad": "0"}, "entre 1 y 20"),
    ({"modo": "texto", "texto": TEXTO, "cantidad": "99"}, "entre 1 y 20"),
    ({"modo": "texto", "texto": TEXTO, "cantidad": "x"}, "entre 1 y 20"),
    ({"modo": "archivo", "cantidad": "1"}, "Seleccioná un archivo"),
])
def test_generar_valida_la_entrada(client, monkeypatch, data, mensaje):
    monkeypatch.setattr(gen, "generar", lambda *a, **k: pytest.fail("no debe generar"))
    r = client.post("/admin/trivias/ia/generar", data=data)
    assert r.status_code == 400 and mensaje in r.get_json()["error"]


def test_generar_rechaza_doc(client, monkeypatch):
    monkeypatch.setattr(gen, "generar", lambda *a, **k: pytest.fail("no debe generar"))
    r = client.post("/admin/trivias/ia/generar", content_type="multipart/form-data",
                    data={"modo": "archivo", "cantidad": "1", "archivo": (io.BytesIO(b"\xd0\xcf\x11\xe0" * 100), "viejo.doc")})
    assert r.status_code == 400 and ".docx" in r.get_json()["error"]


@pytest.mark.parametrize("error,status,tipo", [
    (prov.IAError("cuota"), 502, "cuota"),
    (prov.IAError("auth"), 502, "auth"),
    (ia_config.LimiteIAError("límite"), 409, "limite"),
    (gen.GeneracionEnCursoError("en curso"), 409, "duplicada"),
    (RuntimeError("detalle interno"), 500, "interno"),
])
def test_generar_traduce_errores_sin_romper(client, monkeypatch, error, status, tipo):
    def falla(*a, **k):
        raise error
    monkeypatch.setattr(gen, "generar", falla)
    r = client.post("/admin/trivias/ia/generar", data={"modo": "texto", "texto": TEXTO, "cantidad": "1"})
    body = r.get_json()
    assert r.status_code == status and body["tipo"] == tipo and "detalle interno" not in body["error"]


# ---------------------------------------------------------------------------
# Guardar
# ---------------------------------------------------------------------------

def test_guardar_crea_trivia_con_preguntas_en_las_tablas_existentes(client, monkeypatch):
    guardado = {}

    def crear(data, preguntas):
        guardado.update(data=data, preguntas=preguntas)
        return 55
    monkeypatch.setattr(ia_routes.repo, "create_trivia_con_preguntas", crear)
    monkeypatch.setattr(ia_routes, "log_audit", lambda *a: None)
    r = client.post("/admin/trivias/ia/guardar", data=_form_guardar(_token(client)))
    assert r.status_code == 302 and r.headers["Location"].endswith("/admin/trivias/55")
    data = guardado["data"]
    assert data["titulo"] == "Seguridad" and data["estado"] == "programada" and data["sector_ids"] == [1]
    assert data["fecha_inicio"] == datetime.datetime(2026, 12, 1, 8, 0) and data["anio"] == 2026
    assert guardado["preguntas"] == [{**PREGUNTA, "activa": 1, "orden": 0}]


def test_guardar_dos_veces_el_mismo_formulario_no_duplica(client, monkeypatch):
    creadas = []
    monkeypatch.setattr(ia_routes.repo, "create_trivia_con_preguntas", lambda d, p: creadas.append(1) or 55)
    monkeypatch.setattr(ia_routes, "log_audit", lambda *a: None)
    form = _form_guardar(_token(client))
    client.post("/admin/trivias/ia/guardar", data=form)
    r = client.post("/admin/trivias/ia/guardar", data=form)
    assert r.status_code == 302 and r.headers["Location"].endswith("/admin/trivias/") and creadas == [1]


def test_guardar_sin_token_no_crea(client, monkeypatch):
    monkeypatch.setattr(ia_routes.repo, "create_trivia_con_preguntas", lambda *a: pytest.fail("no debe crear"))
    assert client.post("/admin/trivias/ia/guardar", data=_form_guardar("falso")).status_code == 302


@pytest.mark.parametrize("cambios,mensaje", [
    ({"titulo": ""}, "El título es obligatorio."),
    ({"fecha_fin": "2026-11-30T08:00"}, "posterior a la de inicio"),
    ({"preguntas_json": "[]"}, "al menos una pregunta"),
    ({"preguntas_json": "no-json"}, "al menos una pregunta"),
    ({"preguntas_json": json.dumps([{**PREGUNTA, "respuesta_correcta": "E"}])}, "A, B, C o D"),
    ({"anio": "abc"}, "Revisá los datos"),
])
def test_guardar_aplica_las_validaciones_del_alta_manual(client, monkeypatch, cambios, mensaje):
    monkeypatch.setattr(ia_routes.repo, "create_trivia_con_preguntas", lambda *a: pytest.fail("no debe crear"))
    r = client.post("/admin/trivias/ia/guardar", data=_form_guardar(_token(client), **cambios))
    html = r.get_data(as_text=True)
    assert r.status_code == 400 and mensaje in html
    assert 'name="token"' in html  # puede corregir y volver a enviar


def test_guardar_si_falla_la_base_conserva_el_borrador(client, monkeypatch):
    def falla(*a):
        raise RuntimeError("sin conexión")
    monkeypatch.setattr(ia_routes.repo, "create_trivia_con_preguntas", falla)
    r = client.post("/admin/trivias/ia/guardar", data=_form_guardar(_token(client)))
    html = r.get_data(as_text=True)
    assert r.status_code == 400 and "Error al guardar" in html and "Velocidad m" in html and "10 km/h" in html


# ---------------------------------------------------------------------------
# Regresión: alta y edición manual de preguntas usan la validación compartida
# ---------------------------------------------------------------------------

def test_agregar_pregunta_manual_igual_que_antes(client, monkeypatch):
    creadas = []
    monkeypatch.setattr(admin_routes.repo, "get_trivia_by_id", lambda tid: {"id": tid, "estado": "programada"})
    monkeypatch.setattr(admin_routes.repo, "create_pregunta", lambda tid, d: creadas.append((tid, d)))
    monkeypatch.setattr(admin_routes, "log_audit", lambda *a: None)
    client.post("/admin/trivias/3/preguntas", data={**PREGUNTA, "texto": "  Hola  ", "respuesta_correcta": "c",
                                                    "puntos": "", "orden": "2"})
    assert creadas == [(3, {"texto": "Hola", "opcion_a": "5 km/h", "opcion_b": "10 km/h", "opcion_c": "15 km/h",
                            "opcion_d": "20 km/h", "respuesta_correcta": "C", "puntos": 10, "activa": 1, "orden": 2})]
    r = client.post("/admin/trivias/3/preguntas", data={**PREGUNTA, "opcion_d": ""}, follow_redirects=True)
    assert "Todas las opciones (A, B, C, D) son obligatorias." in r.get_data(as_text=True) and len(creadas) == 1


def test_editar_pregunta_manual_igual_que_antes(client, monkeypatch):
    cambios = []
    monkeypatch.setattr(admin_routes.repo, "get_pregunta_by_id", lambda pid: {"id": pid, "trivia_id": 3})
    monkeypatch.setattr(admin_routes.repo, "update_pregunta", lambda pid, d: cambios.append((pid, d)))
    monkeypatch.setattr(admin_routes, "log_audit", lambda *a: None)
    client.post("/admin/trivias/3/preguntas/8/editar", data={**PREGUNTA, "activa": "0", "orden": "1"})
    assert cambios == [(8, {**PREGUNTA, "activa": 0, "orden": 1})]
    r = client.post("/admin/trivias/3/preguntas/8/editar", data={**PREGUNTA, "respuesta_correcta": "Z"},
                    follow_redirects=True)
    assert "La respuesta correcta debe ser A, B, C o D." in r.get_data(as_text=True) and len(cambios) == 1


# ---------------------------------------------------------------------------
# Configuración de IA
# ---------------------------------------------------------------------------

def test_configuracion_no_muestra_claves(client, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-super-secreta")
    monkeypatch.setattr(ia_config, "panel", lambda: {"cfg": CFG, "proveedores": ia_config.estado_proveedores(),
                                                     "uso": None, "ultimos": []})
    html = client.get("/configuracion-ia/").get_data(as_text=True)
    assert "sk-ant" not in html and "Configurado" in html and "Probar conexión" in html
    assert "Configuración de IA" in html


def test_configuracion_guardar(client, monkeypatch):
    monkeypatch.setattr(ia_config, "guardar", lambda form: [])
    monkeypatch.setattr(cfg_routes, "log_audit", lambda *a: None)
    assert client.post("/configuracion-ia/guardar", data={"proveedor": "anthropic"}).status_code == 302
    monkeypatch.setattr(ia_config, "guardar", lambda form: ["Falta la clave"])
    monkeypatch.setattr(ia_config, "panel", lambda: {"cfg": CFG, "proveedores": [], "uso": None, "ultimos": []})
    r = client.post("/configuracion-ia/guardar", data={})
    assert r.status_code == 400 and "Falta la clave" in r.get_data(as_text=True)


def test_probar_conexion_endpoint(client, monkeypatch):
    llamadas = []
    monkeypatch.setattr(ia_config, "probar_conexion",
                        lambda cfg, p, m, u: llamadas.append((p, m)) or {"ok": False, "tipo": "auth", "mensaje": "x"})
    assert client.post("/configuracion-ia/probar", data={"proveedor": "anthropic"}).get_json()["tipo"] == "auth"
    assert llamadas == [("anthropic", "claude-opus-5-5")]
    assert client.post("/configuracion-ia/probar", data={"proveedor": "otro"}).status_code == 400


def test_listar_modelos_endpoint(client, monkeypatch):
    monkeypatch.setattr(prov, "listar_modelos", lambda p: ["m1", "m2"])
    assert client.post("/configuracion-ia/modelos", data={"proveedor": "openai"}).get_json()["modelos"] == ["m1", "m2"]
