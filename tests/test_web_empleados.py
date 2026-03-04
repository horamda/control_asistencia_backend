import io

import app as app_module
import web.auth.decorators as auth_decorators
import web.empleados.empleados_routes as empleados_routes


def _build_client(monkeypatch):
    monkeypatch.setattr(app_module, "init_db", lambda: None)
    app = app_module.create_app()
    app.config["TESTING"] = True
    app.config["WTF_CSRF_ENABLED"] = False
    return app.test_client()


def _login_session(client):
    with client.session_transaction() as sess:
        sess["user_id"] = 101


def _patch_catalogs(monkeypatch):
    monkeypatch.setattr(empleados_routes, "get_empresas", lambda *args, **kwargs: [])
    monkeypatch.setattr(empleados_routes, "get_sucursales", lambda *args, **kwargs: [])
    monkeypatch.setattr(empleados_routes, "get_sectores", lambda *args, **kwargs: [])
    monkeypatch.setattr(empleados_routes, "get_puestos", lambda *args, **kwargs: [])
    monkeypatch.setattr(empleados_routes, "get_localidades", lambda *args, **kwargs: [])
    monkeypatch.setattr(empleados_routes, "exists_codigo", lambda _codigo: True)
    monkeypatch.setattr(empleados_routes, "exists_unique", lambda *args, **kwargs: False)


def _base_form_data():
    return {
        "empresa_id": "1",
        "sucursal_id": "1",
        "sector_id": "1",
        "puesto_id": "1",
        "codigo_postal": "1000",
        "legajo": "L001",
        "dni": "30123456",
        "nombre": "Ana",
        "apellido": "Perez",
        "email": "ana@example.com",
        "telefono": "11223344",
        "direccion": "Calle 1",
        "estado": "activo",
        "sexo": "femenino",
        "fecha_nacimiento": "1990-01-10",
        "fecha_ingreso": "2020-02-01",
        "foto": "",
    }


def test_empleados_nuevo_sube_foto_file(monkeypatch):
    client = _build_client(monkeypatch)
    _login_session(client)
    monkeypatch.setattr(auth_decorators, "has_role", lambda actor_id, role: True)
    _patch_catalogs(monkeypatch)
    monkeypatch.setattr(empleados_routes, "log_audit", lambda *args, **kwargs: None)

    captured = {}

    def _fake_upload(file_storage, dni):
        captured["uploaded_name"] = file_storage.filename
        captured["uploaded_dni"] = dni
        return "https://cdn.example.com/fotos/30123456.jpg"

    def _fake_create(data):
        captured["create_data"] = dict(data)
        return 88

    monkeypatch.setattr(empleados_routes, "upload_profile_photo", _fake_upload)
    monkeypatch.setattr(empleados_routes, "create", _fake_create)

    form_data = _base_form_data()
    form_data["password"] = "secret123"
    form_data["foto_file"] = (io.BytesIO(b"\xff\xd8\xffjpeg"), "perfil.jpg")

    resp = client.post(
        "/empleados/nuevo",
        data=form_data,
        content_type="multipart/form-data",
        follow_redirects=False,
    )

    assert resp.status_code == 302
    assert resp.headers["Location"].endswith("/empleados/")
    assert captured["uploaded_name"] == "perfil.jpg"
    assert captured["uploaded_dni"] == "30123456"
    assert captured["create_data"]["foto"] == "https://cdn.example.com/fotos/30123456.jpg"


def test_empleados_editar_elimina_foto(monkeypatch):
    client = _build_client(monkeypatch)
    _login_session(client)
    monkeypatch.setattr(auth_decorators, "has_role", lambda actor_id, role: True)
    _patch_catalogs(monkeypatch)
    monkeypatch.setattr(empleados_routes, "log_audit", lambda *args, **kwargs: None)

    state = {}
    monkeypatch.setattr(
        empleados_routes,
        "get_by_id",
        lambda emp_id: {
            "id": emp_id,
            "dni": "30123456",
            "nombre": "Ana",
            "apellido": "Perez",
            "email": "ana@example.com",
            "empresa_id": 1,
            "sucursal_id": 1,
            "sector_id": 1,
            "puesto_id": 1,
            "codigo_postal": "1000",
            "estado": "activo",
            "sexo": "femenino",
            "foto": "https://cdn.example.com/fotos/30123456.jpg",
        },
    )
    monkeypatch.setattr(
        empleados_routes,
        "delete_profile_photo_for_dni",
        lambda dni: state.update({"deleted_dni": dni}),
    )
    monkeypatch.setattr(empleados_routes, "update_password", lambda *args, **kwargs: None)
    monkeypatch.setattr(empleados_routes, "update", lambda emp_id, data: state.update({"update_data": dict(data)}))

    form_data = _base_form_data()
    form_data["foto"] = "https://cdn.example.com/fotos/30123456.jpg"
    form_data["eliminar_foto"] = "1"

    resp = client.post(
        "/empleados/editar/7",
        data=form_data,
        content_type="multipart/form-data",
        follow_redirects=False,
    )

    assert resp.status_code == 302
    assert resp.headers["Location"].endswith("/empleados/")
    assert state["deleted_dni"] == "30123456"
    assert state["update_data"]["foto"] is None


def test_empleados_editar_bloquea_file_y_eliminar_juntos(monkeypatch):
    client = _build_client(monkeypatch)
    _login_session(client)
    monkeypatch.setattr(auth_decorators, "has_role", lambda actor_id, role: True)
    _patch_catalogs(monkeypatch)

    called = {"update": False}
    monkeypatch.setattr(
        empleados_routes,
        "get_by_id",
        lambda emp_id: {
            "id": emp_id,
            "dni": "30123456",
            "nombre": "Ana",
            "apellido": "Perez",
            "email": "ana@example.com",
            "empresa_id": 1,
            "sucursal_id": 1,
            "sector_id": 1,
            "puesto_id": 1,
            "codigo_postal": "1000",
            "estado": "activo",
            "sexo": "femenino",
            "foto": "https://cdn.example.com/fotos/30123456.jpg",
        },
    )
    monkeypatch.setattr(
        empleados_routes,
        "upload_profile_photo",
        lambda *args, **kwargs: "https://cdn.example.com/fotos/30123456.jpg",
    )
    monkeypatch.setattr(empleados_routes, "update", lambda *args, **kwargs: called.update({"update": True}))

    form_data = _base_form_data()
    form_data["eliminar_foto"] = "1"
    form_data["foto_file"] = (io.BytesIO(b"\xff\xd8\xffjpeg"), "perfil.jpg")

    resp = client.post(
        "/empleados/editar/7",
        data=form_data,
        content_type="multipart/form-data",
        follow_redirects=False,
    )

    assert resp.status_code == 200
    assert b"No puede enviar una foto y marcar eliminar foto al mismo tiempo." in resp.data
    assert called["update"] is False


def test_empleados_editar_no_actualiza_password_sin_checkbox(monkeypatch):
    client = _build_client(monkeypatch)
    _login_session(client)
    monkeypatch.setattr(auth_decorators, "has_role", lambda actor_id, role: True)
    _patch_catalogs(monkeypatch)
    monkeypatch.setattr(empleados_routes, "log_audit", lambda *args, **kwargs: None)

    state = {"password_updates": 0}
    monkeypatch.setattr(
        empleados_routes,
        "get_by_id",
        lambda emp_id: {
            "id": emp_id,
            "dni": "30123456",
            "nombre": "Ana",
            "apellido": "Perez",
            "email": "ana@example.com",
            "empresa_id": 1,
            "sucursal_id": 1,
            "sector_id": 1,
            "puesto_id": 1,
            "codigo_postal": "1000",
            "estado": "activo",
            "sexo": "femenino",
            "foto": None,
        },
    )
    monkeypatch.setattr(empleados_routes, "update", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        empleados_routes,
        "update_password",
        lambda *args, **kwargs: state.update({"password_updates": state["password_updates"] + 1}),
    )

    form_data = _base_form_data()
    form_data["password"] = "autofill-que-no-debe-guardar"

    resp = client.post(
        "/empleados/editar/7",
        data=form_data,
        content_type="multipart/form-data",
        follow_redirects=False,
    )

    assert resp.status_code == 302
    assert state["password_updates"] == 0


def test_empleados_editar_actualiza_password_con_checkbox(monkeypatch):
    client = _build_client(monkeypatch)
    _login_session(client)
    monkeypatch.setattr(auth_decorators, "has_role", lambda actor_id, role: True)
    _patch_catalogs(monkeypatch)
    monkeypatch.setattr(empleados_routes, "log_audit", lambda *args, **kwargs: None)

    state = {"password_updates": 0}
    monkeypatch.setattr(
        empleados_routes,
        "get_by_id",
        lambda emp_id: {
            "id": emp_id,
            "dni": "30123456",
            "nombre": "Ana",
            "apellido": "Perez",
            "email": "ana@example.com",
            "empresa_id": 1,
            "sucursal_id": 1,
            "sector_id": 1,
            "puesto_id": 1,
            "codigo_postal": "1000",
            "estado": "activo",
            "sexo": "femenino",
            "foto": None,
        },
    )
    monkeypatch.setattr(empleados_routes, "update", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        empleados_routes,
        "update_password",
        lambda *args, **kwargs: state.update({"password_updates": state["password_updates"] + 1}),
    )

    form_data = _base_form_data()
    form_data["cambiar_password"] = "1"
    form_data["password"] = "nuevo-password-seguro"

    resp = client.post(
        "/empleados/editar/7",
        data=form_data,
        content_type="multipart/form-data",
        follow_redirects=False,
    )

    assert resp.status_code == 302
    assert state["password_updates"] == 1


def test_empleados_editar_redirige_next_interno(monkeypatch):
    client = _build_client(monkeypatch)
    _login_session(client)
    monkeypatch.setattr(auth_decorators, "has_role", lambda actor_id, role: True)
    _patch_catalogs(monkeypatch)
    monkeypatch.setattr(empleados_routes, "log_audit", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        empleados_routes,
        "get_by_id",
        lambda emp_id: {
            "id": emp_id,
            "dni": "30123456",
            "nombre": "Ana",
            "apellido": "Perez",
            "email": "ana@example.com",
            "empresa_id": 1,
            "sucursal_id": 1,
            "sector_id": 1,
            "puesto_id": 1,
            "codigo_postal": "1000",
            "estado": "activo",
            "sexo": "femenino",
            "foto": None,
        },
    )
    monkeypatch.setattr(empleados_routes, "update", lambda *args, **kwargs: None)
    monkeypatch.setattr(empleados_routes, "update_password", lambda *args, **kwargs: None)

    form_data = _base_form_data()
    form_data["next"] = "/empleados/?page=2&per=50"

    resp = client.post(
        "/empleados/editar/7",
        data=form_data,
        content_type="multipart/form-data",
        follow_redirects=False,
    )

    assert resp.status_code == 302
    assert resp.headers["Location"].endswith("/empleados/?page=2&per=50")


def test_empleados_editar_bloquea_next_externo(monkeypatch):
    client = _build_client(monkeypatch)
    _login_session(client)
    monkeypatch.setattr(auth_decorators, "has_role", lambda actor_id, role: True)
    _patch_catalogs(monkeypatch)
    monkeypatch.setattr(empleados_routes, "log_audit", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        empleados_routes,
        "get_by_id",
        lambda emp_id: {
            "id": emp_id,
            "dni": "30123456",
            "nombre": "Ana",
            "apellido": "Perez",
            "email": "ana@example.com",
            "empresa_id": 1,
            "sucursal_id": 1,
            "sector_id": 1,
            "puesto_id": 1,
            "codigo_postal": "1000",
            "estado": "activo",
            "sexo": "femenino",
            "foto": None,
        },
    )
    monkeypatch.setattr(empleados_routes, "update", lambda *args, **kwargs: None)
    monkeypatch.setattr(empleados_routes, "update_password", lambda *args, **kwargs: None)

    form_data = _base_form_data()
    form_data["next"] = "https://example.com/phishing"

    resp = client.post(
        "/empleados/editar/7",
        data=form_data,
        content_type="multipart/form-data",
        follow_redirects=False,
    )

    assert resp.status_code == 302
    assert resp.headers["Location"].endswith("/empleados/")
