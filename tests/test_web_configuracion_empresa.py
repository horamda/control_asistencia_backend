import app as app_module
import web.auth.decorators as auth_decorators
import web.configuracion.configuracion_empresa_routes as configuracion_routes


def _build_client(monkeypatch):
    monkeypatch.setattr(app_module, "init_db", lambda: None)
    app = app_module.create_app()
    app.config["TESTING"] = True
    app.config["WTF_CSRF_ENABLED"] = False
    return app.test_client()


def _login_session(client):
    with client.session_transaction() as sess:
        sess["user_id"] = 99
        sess["user_role"] = "admin"


def test_configuracion_empresa_editar_guarda_cooldown(monkeypatch):
    client = _build_client(monkeypatch)
    _login_session(client)
    captured = {}

    monkeypatch.setattr(auth_decorators, "has_role", lambda actor_id, role: True)
    monkeypatch.setattr(
        configuracion_routes,
        "get_empresas",
        lambda include_inactive=True: [{"id": 1, "razon_social": "Del Palacio S.A."}],
    )
    monkeypatch.setattr(
        configuracion_routes,
        "get_by_empresa_id",
        lambda empresa_id: {
            "empresa_id": empresa_id,
            "requiere_qr": 1,
            "requiere_foto": 0,
            "requiere_geo": 1,
            "tolerancia_global": 5,
            "cooldown_scan_segundos": 60,
            "intervalo_minimo_fichadas_minutos": 60,
        },
    )
    monkeypatch.setattr(configuracion_routes, "upsert", lambda data: captured.setdefault("data", data) or True)
    monkeypatch.setattr(configuracion_routes, "log_audit", lambda *args, **kwargs: None)

    resp = client.post(
        "/configuracion-empresa/editar/1",
        data={
            "requiere_qr": "1",
            "requiere_geo": "1",
            "tolerancia_global": "5",
            "cooldown_scan_segundos": "15",
            "intervalo_minimo_fichadas_minutos": "45",
        },
        follow_redirects=False,
    )

    assert resp.status_code == 302
    assert captured["data"]["cooldown_scan_segundos"] == 15
    assert captured["data"]["intervalo_minimo_fichadas_minutos"] == 45
    assert "msg=Configuracion+guardada." in resp.headers["Location"]


def test_configuracion_empresa_editar_rechaza_cooldown_negativo(monkeypatch):
    client = _build_client(monkeypatch)
    _login_session(client)
    called = {"upsert": False}

    monkeypatch.setattr(auth_decorators, "has_role", lambda actor_id, role: True)
    monkeypatch.setattr(
        configuracion_routes,
        "get_empresas",
        lambda include_inactive=True: [{"id": 1, "razon_social": "Del Palacio S.A."}],
    )
    monkeypatch.setattr(configuracion_routes, "get_by_empresa_id", lambda empresa_id: {"empresa_id": empresa_id})
    monkeypatch.setattr(configuracion_routes, "upsert", lambda data: called.update(upsert=True))

    resp = client.post(
        "/configuracion-empresa/editar/1",
        data={
            "cooldown_scan_segundos": "-1",
            "intervalo_minimo_fichadas_minutos": "60",
        },
    )

    html = resp.get_data(as_text=True)
    assert resp.status_code == 200
    assert "Cooldown scan QR no puede ser negativo." in html
    assert called["upsert"] is False


def test_configuracion_empresa_editar_muestra_error_si_falta_columna_intervalo(monkeypatch):
    client = _build_client(monkeypatch)
    _login_session(client)

    monkeypatch.setattr(auth_decorators, "has_role", lambda actor_id, role: True)
    monkeypatch.setattr(
        configuracion_routes,
        "get_empresas",
        lambda include_inactive=True: [{"id": 1, "razon_social": "Del Palacio S.A."}],
    )
    monkeypatch.setattr(
        configuracion_routes,
        "get_by_empresa_id",
        lambda empresa_id: {
            "empresa_id": empresa_id,
            "requiere_qr": 1,
            "requiere_foto": 0,
            "requiere_geo": 1,
            "tolerancia_global": 5,
            "cooldown_scan_segundos": 25,
            "intervalo_minimo_fichadas_minutos": None,
        },
    )

    def fail_upsert(data):
        raise RuntimeError("Falta la columna configuracion_empresa.intervalo_minimo_fichadas_minutos.")

    monkeypatch.setattr(configuracion_routes, "upsert", fail_upsert)

    resp = client.post(
        "/configuracion-empresa/editar/1",
        data={
            "requiere_qr": "1",
            "requiere_geo": "1",
            "tolerancia_global": "5",
            "cooldown_scan_segundos": "25",
            "intervalo_minimo_fichadas_minutos": "30",
        },
    )

    html = resp.get_data(as_text=True)
    assert resp.status_code == 200
    assert "Falta la columna configuracion_empresa.intervalo_minimo_fichadas_minutos." in html
