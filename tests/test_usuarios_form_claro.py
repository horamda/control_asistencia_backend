"""Usuarios del panel: el formulario y el listado dicen claramente que admin tiene acceso total (los permisos no se
aplican) y cuando un usuario usa los permisos por defecto de su rol. No cambia como se guardan ni como se aplican."""
import app as app_module
import web.auth.decorators as auth_decorators
import web.usuarios.usuarios_routes as rutas


def _client(monkeypatch, usuario=None, guardados=None):
    monkeypatch.setattr(app_module, "init_db", lambda: None)
    monkeypatch.setattr(auth_decorators, "has_role", lambda actor_id, role: True)
    monkeypatch.setattr(rutas, "get_empresas", lambda include_inactive=True: [{"id": 1, "razon_social": "Empresa"}])
    monkeypatch.setattr(rutas, "_empleados_para_vincular", lambda: [])
    monkeypatch.setattr(rutas, "get_by_id", lambda uid: usuario)
    monkeypatch.setattr(rutas, "get_user_permissions", lambda uid: guardados or {})
    app = app_module.create_app()
    app.config["TESTING"] = True
    app.config["WTF_CSRF_ENABLED"] = False
    client = app.test_client()
    with client.session_transaction() as sess:
        sess["user_id"] = 99
    return client


def _usuario(rol):
    return dict(id=5, usuario="roman", empresa_id=1, rol=rol, activo=1, empleado_id=None)


def _visible(html, marcador):
    """True si el bloque con ese data-permisos-aviso no esta oculto."""
    i = html.index(f'data-permisos-aviso="{marcador}"')
    return "hidden" not in html[i:html.index(">", i)]


def test_admin_avisa_acceso_total_y_atenua_la_grilla(monkeypatch):
    html = _client(monkeypatch, _usuario("admin")).get("/usuarios/editar/5").get_data(as_text=True)
    assert _visible(html, "admin") and not _visible(html, "rol")
    assert "Administrador: acceso total." in html
    assert "data-permisos-grilla inert" in html
    assert "no tiene permisos guardados" not in html
    assert ">admin (acceso total)</option>" in html
    assert "js/usuario-permisos.js" in html


def test_rrhh_con_permisos_guardados(monkeypatch):
    guardados = {"asistencias": {a: True for a in rutas.PERMISSION_ACTIONS}}
    html = _client(monkeypatch, _usuario("rrhh"), guardados).get("/usuarios/editar/5").get_data(as_text=True)
    assert _visible(html, "rol") and not _visible(html, "admin")
    assert "data-permisos-grilla inert" not in html
    assert "no tiene permisos guardados" not in html
    # Las casillas reflejan lo guardado: solo asistencias marcada.
    assert 'name="perm_asistencias_ver"\n                    value="1"\n                    checked' in html.replace("\r\n", "\n")
    assert html.count("checked") == 7  # 6 acciones de asistencias + Activo


def test_rrhh_sin_permisos_guardados_lo_dice(monkeypatch):
    html = _client(monkeypatch, _usuario("rrhh")).get("/usuarios/editar/5").get_data(as_text=True)
    assert "Este usuario no tiene permisos guardados:" in html
    assert "hoy usa los del rol rrhh" in html


def test_nuevo_usuario_sin_rol_no_muestra_el_aviso_de_admin(monkeypatch):
    html = _client(monkeypatch).get("/usuarios/nuevo").get_data(as_text=True)
    assert not _visible(html, "admin") and _visible(html, "rol")
    assert "no tiene permisos guardados" not in html


def test_listado_muestra_el_tipo_de_acceso(monkeypatch):
    client = _client(monkeypatch)
    usuarios = [dict(_usuario("admin"), id=1, usuario="jefe"), dict(_usuario("rrhh"), id=2, usuario="roman"),
                dict(_usuario("supervisor"), id=3, usuario="sup")]
    monkeypatch.setattr(rutas, "get_page", lambda *a, **k: ([dict(u) for u in usuarios], 3))
    monkeypatch.setattr(rutas, "modulos_visibles_por_usuario", lambda ids: {2: 4})
    html = client.get("/usuarios/").get_data(as_text=True)
    assert html.count(">Acceso total</span>") == 1
    assert "Permisos propios: 4 módulos" in html
    assert "Permisos por defecto del rol" in html

    def falla(ids):
        raise RuntimeError("sin base")

    monkeypatch.setattr(rutas, "modulos_visibles_por_usuario", falla)
    html = client.get("/usuarios/").get_data(as_text=True)
    assert html.count(">Acceso total</span>") == 1  # si falla el conteo, el listado se ve igual
    assert "Permisos propios" not in html and "por defecto del rol" not in html


def test_volver_arriba_en_todas_las_paginas_del_panel(monkeypatch):
    html = _client(monkeypatch).get("/usuarios/nuevo").get_data(as_text=True)
    assert "js/volver-arriba.js" in html and "css/volver-arriba.css" in html


# --- MySQL real (SH_TEST_DB_PORT) -------------------------------------------------------------------------------
from tests.test_seguridad import database  # noqa: E402,F401  (fixture)


def test_modulos_visibles_por_usuario_en_la_base(database, monkeypatch):  # noqa: F811
    import repositories.web_permission_repository as repo

    monkeypatch.setattr(repo, "get_db", database)
    conn = database()
    c = conn.cursor()
    c.execute("""CREATE TABLE usuario_modulo_permisos (id INT AUTO_INCREMENT PRIMARY KEY, usuario_id INT NOT NULL,
                 modulo VARCHAR(80) NOT NULL, puede_ver TINYINT(1) NOT NULL DEFAULT 0, puede_crear TINYINT(1) NOT NULL DEFAULT 0,
                 puede_editar TINYINT(1) NOT NULL DEFAULT 0, puede_eliminar TINYINT(1) NOT NULL DEFAULT 0,
                 puede_aprobar TINYINT(1) NOT NULL DEFAULT 0, puede_exportar TINYINT(1) NOT NULL DEFAULT 0,
                 UNIQUE KEY uq (usuario_id, modulo))""")
    conn.commit()
    c.close()
    conn.close()
    repo.set_user_permissions(2, {"asistencias": {"ver": True}, "vacaciones": {"ver": True, "aprobar": True},
                                  "epp": {"ver": False}})
    repo.set_user_permissions(3, {"epp": {"ver": False}})  # guardado, pero sin ningun modulo visible
    assert repo.modulos_visibles_por_usuario([1, 2, 3, 2]) == {2: 2, 3: 0}  # 1 no tiene permisos guardados
    assert repo.modulos_visibles_por_usuario([]) == {}
