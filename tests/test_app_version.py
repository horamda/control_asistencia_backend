"""
Tests del sistema de versiones de la app mobile.

Flujo completo:
  1. La app mobile llama GET /api/v1/mobile/version?platform=android (o ios).
  2. El servidor devuelve version_minima y version_recomendada.
  3. La app compara su propia versión con esos valores:
       app_version < version_minima      → bloquear acceso (actualización obligatoria)
       app_version < version_recomendada → aviso suave (actualización recomendada)
       app_version >= version_recomendada → OK, sin aviso
  4. El panel web /app-version/ (solo admin) permite cambiar esos valores en caliente.
"""

import app as app_module
import routes.mobile_v1_routes as mobile_routes
import web.app_version.app_version_routes as app_version_routes
import web.auth.decorators as auth_decorators


# ── helpers ──────────────────────────────────────────────────────────────────

def _build_client(monkeypatch):
    monkeypatch.setattr(app_module, "init_db", lambda: None)
    monkeypatch.setattr(mobile_routes, "get_profile_photo_version_by_dni", lambda dni: None)
    application = app_module.create_app()
    application.config["TESTING"] = True
    application.config["WTF_CSRF_ENABLED"] = False
    return application.test_client()


def _login_admin(client):
    with client.session_transaction() as sess:
        sess["user_id"] = 1
        sess["user_role"] = "admin"
        sess["rol"] = "admin"


def _fake_config(platform="android", version_minima="2.0.0", version_recomendada="2.3.0",
                 url_descarga=None, mensaje=None):
    return {
        "platform": platform,
        "version_minima": version_minima,
        "version_recomendada": version_recomendada,
        "url_descarga": url_descarga,
        "mensaje": mensaje,
    }


# ── Mobile API: GET /api/v1/mobile/version ────────────────────────────────────

class TestVersionEndpointPublico:
    """El endpoint es público: la app lo llama antes de autenticarse."""

    def test_accesible_sin_autenticacion(self, monkeypatch):
        client = _build_client(monkeypatch)
        monkeypatch.setattr(mobile_routes, "get_version_config", lambda p: None)
        resp = client.get("/api/v1/mobile/version")
        assert resp.status_code == 200

    def test_devuelve_ok_true(self, monkeypatch):
        client = _build_client(monkeypatch)
        monkeypatch.setattr(mobile_routes, "get_version_config", lambda p: None)
        body = client.get("/api/v1/mobile/version").get_json()
        assert body["ok"] is True

    def test_fallback_cuando_no_hay_config_en_db(self, monkeypatch):
        """Sin filas en DB, devuelve 1.0.0 para no bloquear ninguna versión."""
        client = _build_client(monkeypatch)
        monkeypatch.setattr(mobile_routes, "get_version_config", lambda p: None)
        body = client.get("/api/v1/mobile/version?platform=android").get_json()
        assert body["version_minima"] == "1.0.0"
        assert body["version_recomendada"] == "1.0.0"
        assert body["url_descarga"] is None
        assert body["mensaje"] is None

    def test_devuelve_config_de_db(self, monkeypatch):
        client = _build_client(monkeypatch)
        monkeypatch.setattr(
            mobile_routes, "get_version_config",
            lambda p: _fake_config(
                version_minima="2.0.0",
                version_recomendada="2.3.0",
                url_descarga="https://play.google.com/store/apps/details?id=com.app",
                mensaje="Hay una nueva versión disponible.",
            ),
        )
        body = client.get("/api/v1/mobile/version?platform=android").get_json()
        assert body["version_minima"] == "2.0.0"
        assert body["version_recomendada"] == "2.3.0"
        assert "play.google.com" in body["url_descarga"]
        assert body["mensaje"] == "Hay una nueva versión disponible."


class TestVersionEndpointPlataformas:
    def test_android_es_el_default_cuando_falta_param(self, monkeypatch):
        client = _build_client(monkeypatch)
        captured = {}

        def _spy(platform):
            captured["platform"] = platform
            return None

        monkeypatch.setattr(mobile_routes, "get_version_config", _spy)
        body = client.get("/api/v1/mobile/version").get_json()
        assert captured["platform"] == "android"
        assert body["platform"] == "android"

    def test_android_es_el_default_para_plataforma_invalida(self, monkeypatch):
        client = _build_client(monkeypatch)
        captured = {}

        def _spy(platform):
            captured["platform"] = platform
            return None

        monkeypatch.setattr(mobile_routes, "get_version_config", _spy)
        body = client.get("/api/v1/mobile/version?platform=windows").get_json()
        assert captured["platform"] == "android"
        assert body["platform"] == "android"

    def test_ios_es_consultado_correctamente(self, monkeypatch):
        client = _build_client(monkeypatch)
        captured = {}

        def _spy(platform):
            captured["platform"] = platform
            return _fake_config(platform="ios", version_minima="1.5.0", version_recomendada="1.5.0")

        monkeypatch.setattr(mobile_routes, "get_version_config", _spy)
        body = client.get("/api/v1/mobile/version?platform=ios").get_json()
        assert captured["platform"] == "ios"
        assert body["platform"] == "ios"
        assert body["version_minima"] == "1.5.0"

    def test_plataforma_en_mayusculas_se_normaliza(self, monkeypatch):
        client = _build_client(monkeypatch)
        captured = {}

        def _spy(platform):
            captured["platform"] = platform
            return None

        monkeypatch.setattr(mobile_routes, "get_version_config", _spy)
        client.get("/api/v1/mobile/version?platform=ANDROID")
        assert captured["platform"] == "android"


# ── Validaciones de formato de versión (lógica de _validate) ─────────────────

class TestVersionFormatoValidacion:
    """
    El servidor valida que las versiones tengan formato X.Y.Z.
    La lógica de comparación (menor/mayor) es responsabilidad del cliente mobile.
    """

    def _post_nuevo(self, client, **kwargs):
        defaults = {
            "platform": "android",
            "version_minima": "1.0.0",
            "version_recomendada": "1.0.0",
            "activo": "1",
        }
        defaults.update(kwargs)
        return client.post("/app-version/nuevo", data=defaults)

    def test_formato_valido_xyz(self, monkeypatch):
        client = _build_client(monkeypatch)
        _login_admin(client)
        monkeypatch.setattr(auth_decorators, "has_role", lambda uid, role: role == "admin")
        monkeypatch.setattr(app_version_routes, "log_audit", lambda *a, **kw: None)
        monkeypatch.setattr(app_version_routes, "create", lambda data: 1)

        resp = self._post_nuevo(client, version_minima="2.0.0", version_recomendada="2.3.1")
        assert resp.status_code == 302

    def test_version_sin_patch_falla(self, monkeypatch):
        client = _build_client(monkeypatch)
        _login_admin(client)
        monkeypatch.setattr(auth_decorators, "has_role", lambda uid, role: role == "admin")

        resp = self._post_nuevo(client, version_minima="2.0")
        assert resp.status_code == 200
        assert "X.Y.Z" in resp.get_data(as_text=True)

    def test_version_con_texto_falla(self, monkeypatch):
        client = _build_client(monkeypatch)
        _login_admin(client)
        monkeypatch.setattr(auth_decorators, "has_role", lambda uid, role: role == "admin")

        resp = self._post_nuevo(client, version_recomendada="latest")
        assert resp.status_code == 200
        assert "X.Y.Z" in resp.get_data(as_text=True)

    def test_version_vacia_usa_fallback_1_0_0(self, monkeypatch):
        """version_minima vacía usa '1.0.0' como fallback (no es un error)."""
        client = _build_client(monkeypatch)
        _login_admin(client)
        monkeypatch.setattr(auth_decorators, "has_role", lambda uid, role: role == "admin")
        monkeypatch.setattr(app_version_routes, "log_audit", lambda *a, **kw: None)
        captured = {}
        monkeypatch.setattr(app_version_routes, "create", lambda data: captured.update(data) or 1)

        resp = client.post(
            "/app-version/nuevo",
            data={"platform": "android", "version_minima": "", "version_recomendada": "1.0.0", "activo": "1"},
            follow_redirects=False,
        )
        assert resp.status_code == 302
        assert captured["version_minima"] == "1.0.0"

    def test_plataforma_invalida_falla(self, monkeypatch):
        client = _build_client(monkeypatch)
        _login_admin(client)
        monkeypatch.setattr(auth_decorators, "has_role", lambda uid, role: role == "admin")

        resp = self._post_nuevo(client, platform="windows")
        assert resp.status_code == 200
        assert "Plataforma" in resp.get_data(as_text=True)


# ── Panel web /app-version/ ───────────────────────────────────────────────────

class TestAppVersionPanelAcceso:
    def test_listado_redirige_a_login_sin_sesion(self, monkeypatch):
        client = _build_client(monkeypatch)
        resp = client.get("/app-version/")
        assert resp.status_code == 302
        assert "login" in resp.headers["Location"]

    def test_listado_403_para_rol_no_admin(self, monkeypatch):
        client = _build_client(monkeypatch)
        with client.session_transaction() as sess:
            sess["user_id"] = 2
            sess["user_role"] = "rrhh"
        monkeypatch.setattr(auth_decorators, "has_role", lambda uid, role: role == "rrhh")
        resp = client.get("/app-version/")
        assert resp.status_code == 403


class TestAppVersionListado:
    def test_muestra_configs_existentes(self, monkeypatch):
        client = _build_client(monkeypatch)
        _login_admin(client)
        monkeypatch.setattr(auth_decorators, "has_role", lambda uid, role: role == "admin")
        monkeypatch.setattr(
            app_version_routes, "get_all",
            lambda: [
                {
                    "id": 1, "platform": "android", "version_minima": "3.0.0",
                    "version_recomendada": "3.1.0", "url_descarga": None,
                    "mensaje": "Actualiza.", "activo": 1, "updated_at": None,
                }
            ],
        )
        resp = client.get("/app-version/")
        html = resp.get_data(as_text=True)
        assert resp.status_code == 200
        assert "android" in html
        assert "3.0.0" in html
        assert "3.1.0" in html

    def test_muestra_empty_state_cuando_no_hay_configs(self, monkeypatch):
        client = _build_client(monkeypatch)
        _login_admin(client)
        monkeypatch.setattr(auth_decorators, "has_role", lambda uid, role: role == "admin")
        monkeypatch.setattr(app_version_routes, "get_all", lambda: [])
        resp = client.get("/app-version/")
        assert resp.status_code == 200
        assert "primera configuración" in resp.get_data(as_text=True)


class TestAppVersionNuevo:
    def test_get_renderiza_formulario(self, monkeypatch):
        client = _build_client(monkeypatch)
        _login_admin(client)
        monkeypatch.setattr(auth_decorators, "has_role", lambda uid, role: role == "admin")
        resp = client.get("/app-version/nuevo")
        assert resp.status_code == 200
        assert "version_minima" in resp.get_data(as_text=True)

    def test_post_crea_config_android(self, monkeypatch):
        client = _build_client(monkeypatch)
        _login_admin(client)
        monkeypatch.setattr(auth_decorators, "has_role", lambda uid, role: role == "admin")
        monkeypatch.setattr(app_version_routes, "log_audit", lambda *a, **kw: None)
        captured = {}

        def _fake_create(data):
            captured.update(data)
            return 10

        monkeypatch.setattr(app_version_routes, "create", _fake_create)

        resp = client.post(
            "/app-version/nuevo",
            data={
                "platform": "android",
                "version_minima": "2.0.0",
                "version_recomendada": "2.3.0",
                "url_descarga": "https://play.google.com/store",
                "mensaje": "Actualiza para continuar.",
                "activo": "1",
            },
            follow_redirects=False,
        )

        assert resp.status_code == 302
        assert resp.headers["Location"].endswith("/app-version/")
        assert captured["platform"] == "android"
        assert captured["version_minima"] == "2.0.0"
        assert captured["version_recomendada"] == "2.3.0"
        assert captured["activo"] is True
        assert captured["mensaje"] == "Actualiza para continuar."

    def test_post_crea_config_ios(self, monkeypatch):
        client = _build_client(monkeypatch)
        _login_admin(client)
        monkeypatch.setattr(auth_decorators, "has_role", lambda uid, role: role == "admin")
        monkeypatch.setattr(app_version_routes, "log_audit", lambda *a, **kw: None)
        captured = {}
        monkeypatch.setattr(app_version_routes, "create", lambda data: captured.update(data) or 11)

        resp = client.post(
            "/app-version/nuevo",
            data={"platform": "ios", "version_minima": "1.5.0", "version_recomendada": "1.5.0", "activo": "1"},
            follow_redirects=False,
        )

        assert resp.status_code == 302
        assert captured["platform"] == "ios"

    def test_post_crea_config_all(self, monkeypatch):
        client = _build_client(monkeypatch)
        _login_admin(client)
        monkeypatch.setattr(auth_decorators, "has_role", lambda uid, role: role == "admin")
        monkeypatch.setattr(app_version_routes, "log_audit", lambda *a, **kw: None)
        captured = {}
        monkeypatch.setattr(app_version_routes, "create", lambda data: captured.update(data) or 12)

        resp = client.post(
            "/app-version/nuevo",
            data={"platform": "all", "version_minima": "1.0.0", "version_recomendada": "1.0.0", "activo": "1"},
            follow_redirects=False,
        )

        assert resp.status_code == 302
        assert captured["platform"] == "all"

    def test_post_activo_false_cuando_checkbox_ausente(self, monkeypatch):
        client = _build_client(monkeypatch)
        _login_admin(client)
        monkeypatch.setattr(auth_decorators, "has_role", lambda uid, role: role == "admin")
        monkeypatch.setattr(app_version_routes, "log_audit", lambda *a, **kw: None)
        captured = {}
        monkeypatch.setattr(app_version_routes, "create", lambda data: captured.update(data) or 13)

        client.post(
            "/app-version/nuevo",
            data={"platform": "android", "version_minima": "1.0.0", "version_recomendada": "1.0.0"},
            follow_redirects=False,
        )

        assert captured["activo"] is False


class TestAppVersionEditar:
    _config = {
        "id": 1, "platform": "android", "version_minima": "1.0.0",
        "version_recomendada": "1.0.0", "url_descarga": None,
        "mensaje": None, "activo": 1,
    }

    def test_get_precarga_datos_existentes(self, monkeypatch):
        client = _build_client(monkeypatch)
        _login_admin(client)
        monkeypatch.setattr(auth_decorators, "has_role", lambda uid, role: role == "admin")
        monkeypatch.setattr(app_version_routes, "get_by_id", lambda cid: dict(self._config))

        resp = client.get("/app-version/editar/1")
        html = resp.get_data(as_text=True)
        assert resp.status_code == 200
        assert "1.0.0" in html

    def test_get_404_si_no_existe(self, monkeypatch):
        client = _build_client(monkeypatch)
        _login_admin(client)
        monkeypatch.setattr(auth_decorators, "has_role", lambda uid, role: role == "admin")
        monkeypatch.setattr(app_version_routes, "get_by_id", lambda cid: None)

        resp = client.get("/app-version/editar/999")
        assert resp.status_code == 404

    def test_post_actualiza_version(self, monkeypatch):
        client = _build_client(monkeypatch)
        _login_admin(client)
        monkeypatch.setattr(auth_decorators, "has_role", lambda uid, role: role == "admin")
        monkeypatch.setattr(app_version_routes, "log_audit", lambda *a, **kw: None)
        monkeypatch.setattr(app_version_routes, "get_by_id", lambda cid: dict(self._config))
        captured = {}

        def _fake_update(config_id, data):
            captured["id"] = config_id
            captured.update(data)

        monkeypatch.setattr(app_version_routes, "update", _fake_update)

        resp = client.post(
            "/app-version/editar/1",
            data={
                "platform": "android",
                "version_minima": "3.0.0",
                "version_recomendada": "3.1.0",
                "url_descarga": "https://play.google.com/store",
                "mensaje": "Nueva version.",
                "activo": "1",
            },
            follow_redirects=False,
        )

        assert resp.status_code == 302
        assert captured["id"] == 1
        assert captured["version_minima"] == "3.0.0"
        assert captured["version_recomendada"] == "3.1.0"

    def test_post_muestra_error_con_version_invalida(self, monkeypatch):
        client = _build_client(monkeypatch)
        _login_admin(client)
        monkeypatch.setattr(auth_decorators, "has_role", lambda uid, role: role == "admin")
        monkeypatch.setattr(app_version_routes, "get_by_id", lambda cid: dict(self._config))

        resp = client.post(
            "/app-version/editar/1",
            data={
                "platform": "android",
                "version_minima": "3.0",  # inválido
                "version_recomendada": "3.1.0",
                "activo": "1",
            },
        )

        assert resp.status_code == 200
        assert "X.Y.Z" in resp.get_data(as_text=True)


class TestAppVersionEliminar:
    def test_elimina_config_existente(self, monkeypatch):
        client = _build_client(monkeypatch)
        _login_admin(client)
        monkeypatch.setattr(auth_decorators, "has_role", lambda uid, role: role == "admin")
        monkeypatch.setattr(app_version_routes, "log_audit", lambda *a, **kw: None)
        monkeypatch.setattr(
            app_version_routes, "get_by_id",
            lambda cid: {"id": cid, "platform": "android"},
        )
        deleted = []
        monkeypatch.setattr(app_version_routes, "delete", lambda cid: deleted.append(cid))

        resp = client.post("/app-version/eliminar/1", follow_redirects=False)

        assert resp.status_code == 302
        assert resp.headers["Location"].endswith("/app-version/")
        assert 1 in deleted

    def test_404_si_config_no_existe(self, monkeypatch):
        client = _build_client(monkeypatch)
        _login_admin(client)
        monkeypatch.setattr(auth_decorators, "has_role", lambda uid, role: role == "admin")
        monkeypatch.setattr(app_version_routes, "get_by_id", lambda cid: None)

        resp = client.post("/app-version/eliminar/999")
        assert resp.status_code == 404
