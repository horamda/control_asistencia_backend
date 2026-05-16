import app as app_module
import web.auth.decorators as auth_decorators
import web.organigrama.organigrama_routes as organigrama_routes


def _build_client(monkeypatch):
    monkeypatch.setattr(app_module, "init_db", lambda: None)
    app = app_module.create_app()
    app.config["TESTING"] = True
    app.config["WTF_CSRF_ENABLED"] = False
    return app.test_client()


def _login_session(client, role="rrhh"):
    with client.session_transaction() as sess:
        sess["user_id"] = 101
        sess["user_role"] = role


def test_organigrama_renderiza_estructura_y_responsables(monkeypatch):
    client = _build_client(monkeypatch)
    _login_session(client)
    monkeypatch.setattr(auth_decorators, "has_role", lambda actor_id, role: role == "rrhh")
    monkeypatch.setattr(
        organigrama_routes,
        "get_empresas",
        lambda include_inactive=False: [{"id": 1, "razon_social": "Empresa A"}],
    )
    monkeypatch.setattr(
        organigrama_routes,
        "get_organigrama",
        lambda empresa_id=None, activo=1: [
            {
                "empresa_id": 1,
                "empresa_nombre": "Empresa A",
                "total_sectores": 2,
                "total_empleados": 3,
                "responsables_asignados": 1,
                "empleados_sin_sector": [
                    {
                        "nombre_completo": "Gomez Luis",
                        "puesto_nombre": "Administrativo",
                    }
                ],
                "roots": [
                    {
                        "id": 10,
                        "nombre": "Operaciones",
                        "activo": 1,
                        "responsable_nombre_completo": "Perez Ana",
                        "responsable_apellido": "Perez",
                        "responsable_nombre": "Ana",
                        "responsable_puesto_nombre": "Gerente",
                        "dotacion_total": 2,
                        "children": [
                            {
                                "id": 11,
                                "nombre": "Logistica",
                                "activo": 1,
                                "responsable_nombre_completo": "",
                                "responsable_apellido": None,
                                "responsable_nombre": None,
                                "responsable_puesto_nombre": None,
                                "dotacion_total": 1,
                                "children": [],
                                "empleados": [
                                    {
                                        "nombre_completo": "Lopez Juan",
                                        "puesto_nombre": "Operario",
                                    }
                                ],
                            }
                        ],
                        "empleados": [
                            {
                                "nombre_completo": "Perez Ana",
                                "puesto_nombre": "Gerente",
                                "puestos_adicionales": [
                                    {"puesto_nombre": "Supervisor"},
                                    {"puesto_nombre": "Operario"},
                                ],
                            }
                        ],
                    }
                ],
            }
        ],
    )

    resp = client.get("/organigrama/")

    assert resp.status_code == 200
    assert b"Organigrama" in resp.data
    assert b"Empresa A" in resp.data
    assert b"Operaciones" in resp.data
    assert b"Logistica" in resp.data
    assert b"Perez Ana" in resp.data
    assert b"Tambien: Supervisor, Operario" in resp.data
    assert b"Sin responsable" in resp.data
    assert b"Gomez Luis" in resp.data


def test_organigrama_pasa_filtros_al_repositorio(monkeypatch):
    client = _build_client(monkeypatch)
    _login_session(client, role="admin")
    monkeypatch.setattr(auth_decorators, "has_role", lambda actor_id, role: role == "admin")
    monkeypatch.setattr(
        organigrama_routes,
        "get_empresas",
        lambda include_inactive=False: [{"id": 2, "razon_social": "Empresa B"}],
    )
    captured = {}

    def _fake_get_organigrama(empresa_id=None, activo=1):
        captured["empresa_id"] = empresa_id
        captured["activo"] = activo
        return []

    monkeypatch.setattr(organigrama_routes, "get_organigrama", _fake_get_organigrama)

    resp = client.get("/organigrama/?empresa_id=2&activo=all")

    assert resp.status_code == 200
    assert captured == {"empresa_id": 2, "activo": None}
