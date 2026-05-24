import app as app_module
import routes.external_api_routes as external_routes


def _build_client(monkeypatch, api_key="secret-api-key"):
    monkeypatch.setenv("APP_ENV", "test")
    monkeypatch.setenv("SECRET_KEY", "x" * 40)
    if api_key is None:
        monkeypatch.delenv("EXTERNAL_API_KEY", raising=False)
        monkeypatch.delenv("INTEGRATION_API_KEY", raising=False)
    else:
        monkeypatch.setenv("EXTERNAL_API_KEY", api_key)
    monkeypatch.setattr(app_module, "init_db", lambda: None)
    app = app_module.create_app()
    app.config["TESTING"] = True
    app.config["WTF_CSRF_ENABLED"] = False
    return app.test_client()


def test_external_api_requires_configured_key(monkeypatch):
    client = _build_client(monkeypatch, api_key=None)

    resp = client.get("/api/v1/external/empresas")

    assert resp.status_code == 503
    assert "EXTERNAL_API_KEY" in resp.get_json()["error"]


def test_external_api_rejects_missing_key(monkeypatch):
    client = _build_client(monkeypatch)

    resp = client.get("/api/v1/external/empresas")

    assert resp.status_code == 401
    assert resp.get_json()["error"] == "API key invalida o ausente."
    assert resp.headers["WWW-Authenticate"] == 'ApiKey realm="external"'


def test_external_empresas_accepts_bearer_key(monkeypatch):
    client = _build_client(monkeypatch)
    captured = {}

    def _fake_get_empresas(activa=1):
        captured["activa"] = activa
        return [
            {
                "id": 1,
                "razon_social": "Transporte SA",
                "nombre_fantasia": "Transporte",
                "cuit": "30-00000000-1",
                "email": "info@example.com",
                "telefono": "123",
                "direccion": "Calle 1",
                "activa": 1,
            }
        ]

    monkeypatch.setattr(
        external_routes,
        "get_empresas_external",
        _fake_get_empresas,
    )

    resp = client.get(
        "/api/v1/external/empresas",
        headers={"Authorization": "Bearer secret-api-key"},
    )
    body = resp.get_json()

    assert resp.status_code == 200
    assert captured["activa"] == 1
    assert body["count"] == 1
    assert body["data"][0]["activa"] is True


def test_external_catalogo_parses_employee_filters(monkeypatch):
    client = _build_client(monkeypatch)
    captured = {}

    monkeypatch.setattr(
        external_routes,
        "get_empresas_external",
        lambda activa=1: [{"id": 1, "razon_social": "Empresa A", "activa": 1}],
    )
    monkeypatch.setattr(
        external_routes,
        "get_sucursales_external",
        lambda empresa_id=None, activa=1: [
            {
                "id": 10,
                "empresa_id": empresa_id,
                "empresa_nombre": "Empresa A",
                "nombre": "Dolores",
                "activa": activa,
            }
        ],
    )

    def _fake_list_empleados(**kwargs):
        captured.update(kwargs)
        return (
            [
                {
                    "id": 7,
                    "empresa_id": 1,
                    "empresa_nombre": "Empresa A",
                    "sucursal_id": 10,
                    "sucursal_nombre": "Dolores",
                    "puesto_id": 2,
                    "puesto_nombre": "Chofer",
                    "puestos_adicionales_ids": "3",
                    "puestos_adicionales_nombres": "Ayudante",
                    "apellido": "Perez",
                    "nombre": "Juan",
                    "dni": "30123456",
                    "estado": "activo",
                    "activo": 1,
                }
            ],
            1,
        )

    monkeypatch.setattr(external_routes, "list_empleados_external", _fake_list_empleados)

    resp = client.get(
        "/api/v1/external/catalogo"
        "?empresa_id=1"
        "&sucursal=Dolores"
        "&sucursal=Casa%20Central"
        "&tipo_empleado=choferes,ayudantes"
        "&estado=activo"
        "&per_page=50",
        headers={"X-API-Key": "secret-api-key"},
    )
    body = resp.get_json()

    assert resp.status_code == 200
    assert captured["empresa_id"] == 1
    assert captured["sucursal_nombres"] == ["Dolores", "Casa Central"]
    assert captured["puesto_nombres"] == ["choferes", "ayudantes"]
    assert captured["estados"] == ["activo"]
    assert captured["activo"] is None
    assert captured["page"] == 1
    assert captured["per_page"] == 50
    assert body["counts"]["empleados"] == 1
    assert body["empleados"][0]["activo"] is True
    assert body["empleados"][0]["puestos_adicionales_ids"] == [3]
    assert body["empleados"][0]["puestos_adicionales_nombres"] == ["Ayudante"]


def test_external_empleados_supports_id_filters_and_all_active(monkeypatch):
    client = _build_client(monkeypatch)
    captured = {}
    monkeypatch.setattr(
        external_routes,
        "list_empleados_external",
        lambda **kwargs: captured.update(kwargs) or ([], 0),
    )

    resp = client.get(
        "/api/v1/external/empleados"
        "?sucursal_id=10,11"
        "&puesto_id=2,3"
        "&activo=all"
        "&limit=25",
        headers={"X-API-Key": "secret-api-key"},
    )
    body = resp.get_json()

    assert resp.status_code == 200
    assert captured["sucursal_ids"] == [10, 11]
    assert captured["puesto_ids"] == [2, 3]
    assert captured["activo"] is None
    assert body["pagination"]["per_page"] == 25


def test_external_empleados_rejects_invalid_estado(monkeypatch):
    client = _build_client(monkeypatch)

    resp = client.get(
        "/api/v1/external/empleados?estado=borrado",
        headers={"X-API-Key": "secret-api-key"},
    )

    assert resp.status_code == 400
    assert "estado invalido" in resp.get_json()["error"]
