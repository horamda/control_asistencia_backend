import app as app_module
import web.auth.decorators as auth_decorators
import web.sectores.sectores_routes as sectores_routes


def _build_client(monkeypatch):
    monkeypatch.setattr(app_module, "init_db", lambda: None)
    app = app_module.create_app()
    app.config["TESTING"] = True
    app.config["WTF_CSRF_ENABLED"] = False
    return app.test_client()


def _login_session(client):
    with client.session_transaction() as sess:
        sess["user_id"] = 101
        sess["user_role"] = "admin"


def _patch_catalogos(monkeypatch):
    monkeypatch.setattr(
        sectores_routes,
        "get_empresas",
        lambda include_inactive=True: [{"id": 1, "razon_social": "Empresa A"}],
    )
    monkeypatch.setattr(
        sectores_routes,
        "get_sectores",
        lambda include_inactive=True: [
            {
                "id": 4,
                "empresa_id": 1,
                "empresa_nombre": "Empresa A",
                "nombre": "Operaciones",
            },
            {
                "id": 6,
                "empresa_id": 1,
                "empresa_nombre": "Empresa A",
                "nombre": "Logistica",
            },
        ],
    )
    monkeypatch.setattr(
        sectores_routes,
        "get_empleados",
        lambda include_inactive=True: [
            {
                "id": 9,
                "empresa_id": 1,
                "empresa_nombre": "Empresa A",
                "apellido": "Perez",
                "nombre": "Ana",
                "puesto_nombre": "Gerente",
            }
        ],
    )


def test_sectores_nuevo_guarda_sector_padre_y_responsable(monkeypatch):
    client = _build_client(monkeypatch)
    _login_session(client)
    monkeypatch.setattr(auth_decorators, "has_role", lambda actor_id, role: role == "admin")
    _patch_catalogos(monkeypatch)
    monkeypatch.setattr(sectores_routes, "log_audit", lambda *args, **kwargs: None)
    captured = {}

    def _fake_create(data):
        captured.update(data)
        return 22

    monkeypatch.setattr(sectores_routes, "create", _fake_create)

    resp = client.post(
        "/sectores/nuevo",
        data={
            "empresa_id": "1",
            "sector_padre_id": "4",
            "responsable_empleado_id": "9",
            "nombre": "Deposito",
            "activo": "1",
        },
        follow_redirects=False,
    )

    assert resp.status_code == 302
    assert resp.headers["Location"].endswith("/sectores/")
    assert captured["empresa_id"] == 1
    assert captured["sector_padre_id"] == 4
    assert captured["responsable_empleado_id"] == 9
    assert captured["nombre"] == "Deposito"
    assert captured["activo"] is True


def test_sectores_editar_rechaza_ciclo_de_jerarquia(monkeypatch):
    client = _build_client(monkeypatch)
    _login_session(client)
    monkeypatch.setattr(auth_decorators, "has_role", lambda actor_id, role: role == "admin")
    _patch_catalogos(monkeypatch)
    monkeypatch.setattr(
        sectores_routes,
        "get_by_id",
        lambda sector_id: {
            "id": sector_id,
            "empresa_id": 1,
            "sector_padre_id": None,
            "responsable_empleado_id": None,
            "nombre": "Operaciones",
            "activo": 1,
        },
    )
    monkeypatch.setattr(sectores_routes, "would_create_cycle", lambda sector_id, parent_id: True)
    monkeypatch.setattr(sectores_routes, "update", lambda *args, **kwargs: None)

    resp = client.post(
        "/sectores/editar/4",
        data={
            "empresa_id": "1",
            "sector_padre_id": "6",
            "responsable_empleado_id": "9",
            "nombre": "Operaciones",
            "activo": "1",
        },
    )

    assert resp.status_code == 200
    assert b"La jerarquia seleccionada genera un ciclo." in resp.data
