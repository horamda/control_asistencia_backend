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
    monkeypatch.setattr(empleados_routes, "get_periodos_laborales", lambda emp_id: [])
    monkeypatch.setattr(empleados_routes, "get_localidades", lambda *args, **kwargs: [])
    monkeypatch.setattr(empleados_routes, "exists_codigo", lambda _codigo: True)
    monkeypatch.setattr(empleados_routes, "exists_unique", lambda *args, **kwargs: False)
    monkeypatch.setattr(empleados_routes, "get_puestos_ids_by_empleado", lambda *args, **kwargs: [])
    monkeypatch.setattr(empleados_routes, "replace_puestos_adicionales", lambda *args, **kwargs: None)


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
    }


def test_empleados_listado_muestra_foto_y_fallback(monkeypatch):
    client = _build_client(monkeypatch)
    _login_session(client)
    monkeypatch.setattr(auth_decorators, "has_role", lambda actor_id, role: True)
    monkeypatch.setattr(
        empleados_routes,
        "get_listado_resumen",
        lambda **kwargs: {"total": 1, "activos": 1, "sin_control": 0, "con_foto": 1},
    )
    monkeypatch.setattr(
        empleados_routes,
        "get_page",
        lambda *args, **kwargs: (
            [
                {
                    "id": 7,
                    "activo": 1,
                    "foto": "https://cdn.example.com/fotos/30123456.jpg",
                    "apellido": "Perez",
                    "nombre": "Ana",
                    "legajo": "L-1",
                    "dni": "30123456",
                    "email": "ana@example.com",
                    "empresa_nombre": "Empresa A",
                    "empresa_id": 1,
                    "sucursal_nombre": "Casa",
                    "sucursal_id": 1,
                    "sector_nombre": "RRHH",
                    "sector_id": 1,
                    "puesto_nombre": "Analista",
                    "puesto_id": 1,
                    "localidad_nombre": "CABA",
                    "codigo_postal": "1000",
                },
                {
                    "id": 8,
                    "activo": 1,
                    "foto": None,
                    "apellido": "Lopez",
                    "nombre": "Juan",
                    "legajo": "L-2",
                    "dni": "30123457",
                    "email": "juan@example.com",
                    "empresa_nombre": "Empresa A",
                    "empresa_id": 1,
                    "sucursal_nombre": "Casa",
                    "sucursal_id": 1,
                    "sector_nombre": "RRHH",
                    "sector_id": 1,
                    "puesto_nombre": "Analista",
                    "puesto_id": 1,
                    "localidad_nombre": "CABA",
                    "codigo_postal": "1000",
                },
            ],
            2,
        ),
    )
    monkeypatch.setattr(empleados_routes, "get_empresas", lambda *args, **kwargs: [])
    monkeypatch.setattr(empleados_routes, "get_sucursales", lambda *args, **kwargs: [])
    monkeypatch.setattr(empleados_routes, "get_sectores", lambda *args, **kwargs: [])

    resp = client.get("/empleados/")
    assert resp.status_code == 200
    assert b"https://cdn.example.com/fotos/30123456.jpg" in resp.data
    assert b"img/empleado-default.svg" in resp.data


def test_empleados_listado_muestra_vacaciones_resumen(monkeypatch):
    client = _build_client(monkeypatch)
    _login_session(client)
    monkeypatch.setattr(auth_decorators, "has_role", lambda actor_id, role: True)
    monkeypatch.setattr(
        empleados_routes,
        "get_listado_resumen",
        lambda **kwargs: {"total": 1, "activos": 1, "sin_control": 0, "con_foto": 1},
    )
    monkeypatch.setattr(
        empleados_routes,
        "get_page",
        lambda *args, **kwargs: (
            [
                {
                    "id": 7,
                    "activo": 1,
                    "foto": None,
                    "apellido": "Perez",
                    "nombre": "Ana",
                    "legajo": "L-1",
                    "dni": "30123456",
                    "email": "ana@example.com",
                    "empresa_nombre": "Empresa A",
                    "empresa_id": 1,
                    "sucursal_nombre": "Casa",
                    "sucursal_id": 1,
                    "sector_nombre": "RRHH",
                    "sector_id": 1,
                    "puesto_nombre": "Analista",
                    "puesto_id": 1,
                    "localidad_nombre": "CABA",
                    "codigo_postal": "1000",
                }
            ],
            1,
        ),
    )
    monkeypatch.setattr(
        empleados_routes,
        "calcular_resumenes_vacaciones",
        lambda empleados, anio: {7: {
            "anio": anio,
            "vacaciones": {
                "dias_base": 14,
                "dias_corresponden": 14,
                "dias_tomados": 4,
                "dias_disponibles": 10,
                "dias_disponibles_con_pendientes": 8,
                "dias_pendientes": 2,
            },
        }},
    )
    monkeypatch.setattr(empleados_routes, "get_empresas", lambda *args, **kwargs: [])
    monkeypatch.setattr(empleados_routes, "get_sucursales", lambda *args, **kwargs: [])
    monkeypatch.setattr(empleados_routes, "get_sectores", lambda *args, **kwargs: [])

    resp = client.get("/empleados/")
    assert resp.status_code == 200
    assert b"Vacaciones" in resp.data
    assert b"14 dias" in resp.data
    assert b"4 tomados / 10 disponibles" in resp.data


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


def test_empleados_nuevo_guarda_puestos_adicionales(monkeypatch):
    client = _build_client(monkeypatch)
    _login_session(client)
    monkeypatch.setattr(auth_decorators, "has_role", lambda actor_id, role: True)
    _patch_catalogs(monkeypatch)
    monkeypatch.setattr(
        empleados_routes,
        "get_puestos",
        lambda *args, **kwargs: [
            {"id": 1, "empresa_id": 1, "empresa_nombre": "Empresa A", "nombre": "Gerente"},
            {"id": 2, "empresa_id": 1, "empresa_nombre": "Empresa A", "nombre": "Supervisor"},
            {"id": 3, "empresa_id": 1, "empresa_nombre": "Empresa A", "nombre": "Operario"},
        ],
    )
    monkeypatch.setattr(empleados_routes, "log_audit", lambda *args, **kwargs: None)

    captured = {}
    monkeypatch.setattr(empleados_routes, "upload_profile_photo", lambda *args, **kwargs: None)
    monkeypatch.setattr(empleados_routes, "create", lambda data: 88)
    monkeypatch.setattr(
        empleados_routes,
        "replace_puestos_adicionales",
        lambda emp_id, **kwargs: captured.update({"emp_id": emp_id, **kwargs}),
    )

    form_data = _base_form_data()
    form_data["password"] = "secret123"
    form_data["puesto_id"] = "1"
    form_data["puestos_adicionales_ids"] = ["2", "3"]

    resp = client.post("/empleados/nuevo", data=form_data, follow_redirects=False)

    assert resp.status_code == 302
    assert captured["emp_id"] == 88
    assert captured["empresa_id"] == 1
    assert captured["sector_id"] == 1
    assert captured["puesto_principal_id"] == 1
    assert captured["puesto_ids"] == [2, 3]


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


def test_empleados_editar_preserva_foto_existente_si_no_hay_cambios(monkeypatch):
    client = _build_client(monkeypatch)
    _login_session(client)
    monkeypatch.setattr(auth_decorators, "has_role", lambda actor_id, role: True)
    _patch_catalogs(monkeypatch)
    monkeypatch.setattr(empleados_routes, "log_audit", lambda *args, **kwargs: None)

    state = {}
    foto_actual = "https://cdn.example.com/fotos/30123456.jpg"
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
            "foto": foto_actual,
        },
    )
    monkeypatch.setattr(empleados_routes, "update_password", lambda *args, **kwargs: None)
    monkeypatch.setattr(empleados_routes, "update", lambda emp_id, data: state.update({"update_data": dict(data)}))

    resp = client.post(
        "/empleados/editar/7",
        data=_base_form_data(),
        content_type="multipart/form-data",
        follow_redirects=False,
    )

    assert resp.status_code == 302
    assert resp.headers["Location"].endswith("/empleados/")
    assert state["update_data"]["foto"] == foto_actual


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


def test_empleados_listado_kpis_cubren_todo_el_filtro(monkeypatch):
    client = _build_client(monkeypatch)
    _login_session(client)
    monkeypatch.setattr(auth_decorators, "has_role", lambda actor_id, role: True)
    filtros_resumen = []
    monkeypatch.setattr(empleados_routes, "get_page", lambda *args, **kwargs: ([], 240))
    monkeypatch.setattr(
        empleados_routes,
        "get_listado_resumen",
        lambda **kwargs: filtros_resumen.append(kwargs) or {"total": 240, "activos": 231, "sin_control": 12, "con_foto": 87},
    )
    monkeypatch.setattr(empleados_routes, "get_empresas", lambda include_inactive=True: [])
    monkeypatch.setattr(empleados_routes, "get_sucursales", lambda include_inactive=True: [])
    monkeypatch.setattr(empleados_routes, "get_sectores", lambda include_inactive=True: [])

    response = client.get("/empleados/?q=ana&sector_id=4&activo=1&page=3")

    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert ">231<" in html and ">12<" in html and ">87<" in html
    assert "De 240 filtrados" in html
    # Los totales usan los mismos filtros que el listado, sin paginar.
    assert filtros_resumen == [{
        "include_inactive": True, "search": "ana", "empresa_id": None,
        "activo": 1, "sucursal_id": None, "sector_id": 4,
    }]


def test_empleados_listado_se_actualiza_con_htmx(monkeypatch):
    client = _build_client(monkeypatch)
    _login_session(client)
    monkeypatch.setattr(auth_decorators, "has_role", lambda actor_id, role: True)
    monkeypatch.setattr(empleados_routes, "get_page", lambda *args, **kwargs: ([], 0))
    monkeypatch.setattr(empleados_routes, "get_listado_resumen", lambda **kw: {"total": 0, "activos": 0, "sin_control": 0, "con_foto": 0})
    monkeypatch.setattr(empleados_routes, "get_empresas", lambda include_inactive=True: [])
    monkeypatch.setattr(empleados_routes, "get_sucursales", lambda include_inactive=True: [])
    monkeypatch.setattr(empleados_routes, "get_sectores", lambda include_inactive=True: [])

    html = client.get("/empleados/").get_data(as_text=True)

    # Sin JavaScript propio: ajax-nav.js puede reemplazar el contenido.
    assert '<main class="page-content" id="page-content">' in html
    assert 'id="per-page" data-autosubmit' in html
    assert "js/ajax-nav.js" in html


def _patch_baja_reingreso(monkeypatch):
    monkeypatch.setattr(auth_decorators, "can_access_module", lambda *args, **kwargs: True)
    monkeypatch.setattr(empleados_routes, "require_company_record", lambda record: record)
    monkeypatch.setattr(empleados_routes, "get_by_id", lambda emp_id: {"id": emp_id, "empresa_id": 1})
    monkeypatch.setattr(empleados_routes, "log_audit", lambda *args, **kwargs: None)


def test_desactivar_registra_la_fecha_de_baja_elegida(monkeypatch):
    import datetime as dt

    client = _build_client(monkeypatch)
    _login_session(client)
    _patch_baja_reingreso(monkeypatch)
    llamadas = []
    monkeypatch.setattr(empleados_routes, "dar_de_baja", lambda emp_id, fecha: llamadas.append((emp_id, fecha)))

    resp = client.post("/empleados/desactivar/7", data={"fecha_baja": "2026-10-10"})

    assert resp.status_code == 302
    assert llamadas == [(7, dt.date(2026, 10, 10))]


def test_activar_con_fecha_invalida_avisa_sin_reincorporar(monkeypatch):
    from services.empleado_periodo_service import PeriodoLaboralError

    client = _build_client(monkeypatch)
    _login_session(client)
    _patch_baja_reingreso(monkeypatch)

    def reincorporar(emp_id, fecha):
        raise PeriodoLaboralError("La fecha de reingreso debe ser posterior a la ultima baja.")

    monkeypatch.setattr(empleados_routes, "reincorporar", reincorporar)

    resp = client.post("/empleados/activar/7", data={"fecha_reingreso": "2026-01-01"})

    assert resp.status_code == 302
    with client.session_transaction() as sess:
        assert ("error", "La fecha de reingreso debe ser posterior a la ultima baja.") in sess["_flashes"]


def test_editar_inactivo_muestra_reingreso_y_periodos(monkeypatch):
    import datetime as dt

    client = _build_client(monkeypatch)
    _login_session(client)
    _patch_catalogs(monkeypatch)
    monkeypatch.setattr(auth_decorators, "has_role", lambda actor_id, role: True)
    monkeypatch.setattr(empleados_routes, "get_localidades", lambda *args, **kwargs: [])
    monkeypatch.setattr(empleados_routes, "get_puestos_ids_by_empleado", lambda emp_id: [])
    monkeypatch.setattr(empleados_routes, "_get_empleados_lista_para_form", lambda: [])
    # Desactivado con el boton viejo: activo=0 pero estado "activo".
    monkeypatch.setattr(empleados_routes, "get_by_id", lambda emp_id: {
        "id": emp_id, "empresa_id": 1, "nombre": "Ana", "apellido": "Perez", "dni": "30123456",
        "activo": 0, "estado": "activo", "fecha_ingreso": "2024-01-01", "fecha_baja": "2026-03-31",
    })
    monkeypatch.setattr(empleados_routes, "get_periodos_laborales", lambda emp_id: [
        {"id": 1, "fecha_desde": dt.date(2024, 1, 1), "fecha_hasta": dt.date(2026, 3, 31)},
    ])

    resp = client.get("/empleados/editar/7")

    html = resp.get_data(as_text=True)
    assert resp.status_code == 200
    assert 'name="fecha_reingreso"' in html
    assert "01/01/2024 – 31/03/2026" in html
    assert '<option value="inactivo" selected>' in html
