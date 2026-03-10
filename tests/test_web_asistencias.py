import datetime

import app as app_module
import web.auth.decorators as auth_decorators
import web.asistencias.asistencias_routes as asistencias_routes


def _build_client(monkeypatch):
    monkeypatch.setattr(app_module, "init_db", lambda: None)
    app = app_module.create_app()
    app.config["TESTING"] = True
    app.config["WTF_CSRF_ENABLED"] = False
    return app.test_client()


def _login_session(client):
    with client.session_transaction() as sess:
        sess["user_id"] = 99


def test_asistencias_get_ok(monkeypatch):
    client = _build_client(monkeypatch)
    _login_session(client)
    monkeypatch.setattr(auth_decorators, "has_role", lambda actor_id, role: True)
    monkeypatch.setattr(asistencias_routes, "get_page", lambda *args, **kwargs: ([], 0))
    monkeypatch.setattr(asistencias_routes, "get_empleados", lambda include_inactive=True: [])

    resp = client.get("/asistencias/")
    assert resp.status_code == 200
    assert b"Generar ausentes por rango" in resp.data


def test_asistencias_get_muestra_error(monkeypatch):
    client = _build_client(monkeypatch)
    _login_session(client)
    monkeypatch.setattr(auth_decorators, "has_role", lambda actor_id, role: True)
    monkeypatch.setattr(asistencias_routes, "get_page", lambda *args, **kwargs: ([], 0))
    monkeypatch.setattr(asistencias_routes, "get_empleados", lambda include_inactive=True: [])

    resp = client.get("/asistencias/?error=Fecha+invalida")
    assert resp.status_code == 200
    assert b"Fecha invalida" in resp.data


def test_generar_ausentes_dia(monkeypatch):
    client = _build_client(monkeypatch)
    _login_session(client)
    monkeypatch.setattr(auth_decorators, "has_role", lambda actor_id, role: True)
    captured = {}

    def _fake_generar_ausentes(fecha):
        captured["fecha"] = fecha
        return 0, []

    monkeypatch.setattr(asistencias_routes, "generar_ausentes", _fake_generar_ausentes)
    monkeypatch.setattr(asistencias_routes, "generar_ausentes_rango", lambda *args, **kwargs: (0, []))

    fecha = (datetime.date.today() - datetime.timedelta(days=1)).isoformat()
    resp = client.post(
        "/asistencias/generar-ausentes",
        data={"modo": "dia", "fecha": fecha},
        follow_redirects=False,
    )
    assert resp.status_code == 302
    assert f"fecha_desde={fecha}" in resp.headers["Location"]
    assert captured["fecha"] == fecha


def test_generar_ausentes_rango(monkeypatch):
    client = _build_client(monkeypatch)
    _login_session(client)
    monkeypatch.setattr(auth_decorators, "has_role", lambda actor_id, role: True)
    captured = {}

    def _fake_generar_ausentes_rango(fecha_desde, fecha_hasta):
        captured["desde"] = fecha_desde
        captured["hasta"] = fecha_hasta
        return 0, []

    monkeypatch.setattr(asistencias_routes, "generar_ausentes", lambda *args, **kwargs: (0, []))
    monkeypatch.setattr(asistencias_routes, "generar_ausentes_rango", _fake_generar_ausentes_rango)

    fecha_hasta = (datetime.date.today() - datetime.timedelta(days=1)).isoformat()
    fecha_desde = (datetime.date.today() - datetime.timedelta(days=10)).isoformat()
    resp = client.post(
        "/asistencias/generar-ausentes",
        data={"modo": "rango", "fecha_desde": fecha_desde, "fecha_hasta": fecha_hasta},
        follow_redirects=False,
    )
    assert resp.status_code == 302
    assert f"fecha_desde={fecha_desde}" in resp.headers["Location"]
    assert f"fecha_hasta={fecha_hasta}" in resp.headers["Location"]
    assert captured["desde"] == fecha_desde
    assert captured["hasta"] == fecha_hasta


def test_generar_ausentes_rango_propagates_errors(monkeypatch):
    client = _build_client(monkeypatch)
    _login_session(client)
    monkeypatch.setattr(auth_decorators, "has_role", lambda actor_id, role: True)
    monkeypatch.setattr(asistencias_routes, "generar_ausentes", lambda *args, **kwargs: (0, []))
    monkeypatch.setattr(
        asistencias_routes,
        "generar_ausentes_rango",
        lambda fecha_desde, fecha_hasta: (0, ["fecha_desde no puede ser mayor a fecha_hasta."]),
    )

    fecha_hasta = (datetime.date.today() - datetime.timedelta(days=5)).isoformat()
    fecha_desde = (datetime.date.today() - datetime.timedelta(days=2)).isoformat()
    resp = client.post(
        "/asistencias/generar-ausentes",
        data={"modo": "rango", "fecha_desde": fecha_desde, "fecha_hasta": fecha_hasta},
        follow_redirects=False,
    )
    assert resp.status_code == 302
    assert "error=fecha_desde+no+puede+ser+mayor+a+fecha_hasta." in resp.headers["Location"]


def test_generar_ausentes_rango_fecha_hasta_futura(monkeypatch):
    client = _build_client(monkeypatch)
    _login_session(client)
    monkeypatch.setattr(auth_decorators, "has_role", lambda actor_id, role: True)
    called = {"rango": False}

    def _fake_generar_ausentes_rango(fecha_desde, fecha_hasta):
        called["rango"] = True
        return 0, []

    monkeypatch.setattr(asistencias_routes, "generar_ausentes", lambda *args, **kwargs: (0, []))
    monkeypatch.setattr(asistencias_routes, "generar_ausentes_rango", _fake_generar_ausentes_rango)

    fecha_desde = (datetime.date.today() - datetime.timedelta(days=2)).isoformat()
    fecha_hasta = (datetime.date.today() + datetime.timedelta(days=1)).isoformat()
    resp = client.post(
        "/asistencias/generar-ausentes",
        data={"modo": "rango", "fecha_desde": fecha_desde, "fecha_hasta": fecha_hasta},
        follow_redirects=False,
    )
    assert resp.status_code == 302
    assert "error=" in resp.headers["Location"]
    assert "fecha_hasta+no+puede+ser+mayor+a+hoy" in resp.headers["Location"]
    assert called["rango"] is False


def test_sync_simple_marcas_for_asistencia_crea_par_basico(monkeypatch):
    monkeypatch.setattr(
        asistencias_routes,
        "get_by_id",
        lambda asistencia_id: {
            "id": asistencia_id,
            "empresa_id": 1,
            "empleado_id": 100,
            "fecha": "2026-03-10",
            "hora_entrada": "08:00:00",
            "hora_salida": "12:00:00",
            "metodo_entrada": "manual",
            "metodo_salida": "manual",
            "lat_entrada": None,
            "lon_entrada": None,
            "lat_salida": None,
            "lon_salida": None,
            "foto_entrada": None,
            "foto_salida": None,
            "gps_ok_entrada": None,
            "gps_ok_salida": None,
            "gps_distancia_entrada_m": None,
            "gps_distancia_salida_m": None,
            "gps_tolerancia_entrada_m": None,
            "gps_tolerancia_salida_m": None,
            "gps_ref_lat_entrada": None,
            "gps_ref_lon_entrada": None,
            "gps_ref_lat_salida": None,
            "gps_ref_lon_salida": None,
            "estado": "ok",
            "observaciones": "manual",
        },
    )
    monkeypatch.setattr(asistencias_routes, "get_marcas_by_asistencia", lambda asistencia_id: [])
    deleted = {"count": 0}
    created = {"rows": []}

    monkeypatch.setattr(
        asistencias_routes,
        "delete_marca_by_id",
        lambda marca_id: deleted.__setitem__("count", deleted["count"] + 1) or True,
    )

    def _fake_create_marca(**kwargs):
        created["rows"].append(kwargs)
        return len(created["rows"])

    monkeypatch.setattr(asistencias_routes, "create_marca", _fake_create_marca)

    result = asistencias_routes._sync_simple_marcas_for_asistencia(77)
    assert result["synced"] is True
    assert result["created"] == 2
    assert result["deleted"] == 0
    assert len(created["rows"]) == 2
    assert created["rows"][0]["accion"] == "ingreso"
    assert created["rows"][1]["accion"] == "egreso"
    assert deleted["count"] == 0


def test_sync_simple_marcas_for_asistencia_saltea_si_hay_multiples(monkeypatch):
    monkeypatch.setattr(
        asistencias_routes,
        "get_by_id",
        lambda asistencia_id: {
            "id": asistencia_id,
            "empresa_id": 1,
            "empleado_id": 100,
            "fecha": "2026-03-10",
            "hora_entrada": "08:00:00",
            "hora_salida": "12:00:00",
        },
    )
    monkeypatch.setattr(
        asistencias_routes,
        "get_marcas_by_asistencia",
        lambda asistencia_id: [
            {"id": 1, "accion": "ingreso", "tipo_marca": "jornada"},
            {"id": 2, "accion": "ingreso", "tipo_marca": "jornada"},
        ],
    )

    result = asistencias_routes._sync_simple_marcas_for_asistencia(77)
    assert result["synced"] is False
    assert result["reason"] == "multiple_marcas"


def test_asistencias_nuevo_dispara_sync_automatico(monkeypatch):
    client = _build_client(monkeypatch)
    _login_session(client)
    monkeypatch.setattr(auth_decorators, "has_role", lambda actor_id, role: True)
    monkeypatch.setattr(
        asistencias_routes,
        "get_empleados",
        lambda include_inactive=True: [{"id": 100, "apellido": "Perez", "nombre": "Ana", "dni": "30111222"}],
    )
    monkeypatch.setattr(asistencias_routes, "_validate", lambda form: [])
    monkeypatch.setattr(asistencias_routes, "validar_asistencia", lambda *args, **kwargs: ([], "ok"))
    monkeypatch.setattr(asistencias_routes, "create", lambda data: 321)
    monkeypatch.setattr(asistencias_routes, "log_audit", lambda *args, **kwargs: True)
    captured = {}
    monkeypatch.setattr(
        asistencias_routes,
        "_sync_simple_marcas_for_asistencia",
        lambda asistencia_id: captured.__setitem__("id", asistencia_id) or {"synced": True},
    )

    resp = client.post(
        "/asistencias/nuevo",
        data={
            "empleado_id": "100",
            "fecha": "2026-03-10",
            "hora_entrada": "08:00",
            "hora_salida": "12:00",
            "metodo_entrada": "manual",
            "metodo_salida": "manual",
        },
        follow_redirects=False,
    )
    assert resp.status_code == 302
    assert "/asistencias/" in resp.headers["Location"]
    assert captured["id"] == 321


def test_asistencias_editar_dispara_sync_automatico(monkeypatch):
    client = _build_client(monkeypatch)
    _login_session(client)
    monkeypatch.setattr(auth_decorators, "has_role", lambda actor_id, role: True)
    monkeypatch.setattr(
        asistencias_routes,
        "get_by_id",
        lambda asistencia_id: {"id": asistencia_id, "empleado_id": 100, "fecha": "2026-03-10"},
    )
    monkeypatch.setattr(
        asistencias_routes,
        "get_empleados",
        lambda include_inactive=True: [{"id": 100, "apellido": "Perez", "nombre": "Ana", "dni": "30111222"}],
    )
    monkeypatch.setattr(asistencias_routes, "_validate", lambda form: [])
    monkeypatch.setattr(asistencias_routes, "validar_asistencia", lambda *args, **kwargs: ([], "ok"))
    monkeypatch.setattr(asistencias_routes, "update", lambda asistencia_id, data: True)
    monkeypatch.setattr(asistencias_routes, "log_audit", lambda *args, **kwargs: True)
    captured = {}
    monkeypatch.setattr(
        asistencias_routes,
        "_sync_simple_marcas_for_asistencia",
        lambda asistencia_id: captured.__setitem__("id", asistencia_id) or {"synced": True},
    )

    resp = client.post(
        "/asistencias/editar/321",
        data={
            "empleado_id": "100",
            "fecha": "2026-03-10",
            "hora_entrada": "08:00",
            "hora_salida": "12:00",
            "metodo_entrada": "manual",
            "metodo_salida": "manual",
        },
        follow_redirects=False,
    )
    assert resp.status_code == 302
    assert "/asistencias/" in resp.headers["Location"]
    assert captured["id"] == 321


def test_historial_marcas_get_ok(monkeypatch):
    client = _build_client(monkeypatch)
    _login_session(client)
    monkeypatch.setattr(auth_decorators, "has_role", lambda actor_id, role: True)
    monkeypatch.setattr(asistencias_routes, "get_marcas_admin_page", lambda **kwargs: ([], 0))
    monkeypatch.setattr(asistencias_routes, "get_empleados", lambda include_inactive=True: [])
    monkeypatch.setattr(asistencias_routes, "get_empresas", lambda include_inactive=True: [])

    resp = client.get("/asistencias/marcas")
    assert resp.status_code == 200
    assert b"Historial de marcas" in resp.data


def test_historial_marcas_csv_ok(monkeypatch):
    client = _build_client(monkeypatch)
    _login_session(client)
    monkeypatch.setattr(auth_decorators, "has_role", lambda actor_id, role: True)
    monkeypatch.setattr(
        asistencias_routes,
        "get_marcas_admin_export",
        lambda **kwargs: [
            {
                "id": 1,
                "empresa_nombre": "Empresa Test",
                "apellido": "Perez",
                "nombre": "Ana",
                "dni": "30111222",
                "fecha": "2026-02-21",
                "hora": "08:00:00",
                "accion": "ingreso",
                "tipo_marca": "jornada",
                "metodo": "qr",
                "gps_ok": 1,
                "gps_distancia_m": 3.2,
                "gps_tolerancia_m": 30.0,
                "lat": -34.6,
                "lon": -58.4,
                "estado": "ok",
                "observaciones": "",
                "fecha_creacion": "2026-02-21 08:00:01",
            }
        ],
    )

    resp = client.get("/asistencias/marcas.csv")
    assert resp.status_code == 200
    assert "text/csv" in resp.headers["Content-Type"]
    assert "historial_marcas_" in resp.headers["Content-Disposition"]
    assert b"Empresa Test" in resp.data


def test_historial_marcas_backfill_post_ok(monkeypatch):
    client = _build_client(monkeypatch)
    _login_session(client)
    monkeypatch.setattr(auth_decorators, "has_role", lambda actor_id, role: True)
    monkeypatch.setattr(asistencias_routes, "backfill_marcas", lambda: (4, 2))

    resp = client.post(
        "/asistencias/marcas/backfill",
        data={
            "page": "1",
            "per": "20",
            "empresa_id": "",
            "empleado_id": "",
            "fecha_desde": "",
            "fecha_hasta": "",
            "tipo_marca": "",
            "accion": "",
            "metodo": "",
            "gps_ok": "",
            "q": "",
        },
        follow_redirects=False,
    )
    assert resp.status_code == 302
    assert "/asistencias/marcas" in resp.headers["Location"]
    assert "backfill_ingresos=4" in resp.headers["Location"]
    assert "backfill_egresos=2" in resp.headers["Location"]


def test_planilla_diaria_get_ok(monkeypatch):
    client = _build_client(monkeypatch)
    _login_session(client)
    monkeypatch.setattr(auth_decorators, "has_role", lambda actor_id, role: True)
    monkeypatch.setattr(
        asistencias_routes,
        "get_empresas",
        lambda include_inactive=True: [{"id": 1, "razon_social": "Del Palacio S.A"}],
    )
    monkeypatch.setattr(
        asistencias_routes,
        "get_sucursales",
        lambda include_inactive=True: [{"id": 10, "empresa_id": 1, "nombre": "Casa Central"}],
    )
    monkeypatch.setattr(
        asistencias_routes,
        "get_empleados",
        lambda include_inactive=True: [
            {"id": 100, "empresa_id": 1, "sucursal_id": 10, "apellido": "Persona", "nombre": "Uno", "dni": "123"}
        ],
    )
    monkeypatch.setattr(
        asistencias_routes,
        "get_marcas_admin_export",
        lambda **kwargs: [
            {
                "id": 1,
                "empleado_id": 100,
                "asistencia_id": 77,
                "hora": "07:00:00",
                "accion": "ingreso",
            },
            {
                "id": 2,
                "empleado_id": 100,
                "asistencia_id": 77,
                "hora": "12:00:00",
                "accion": "egreso",
            },
        ],
    )
    monkeypatch.setattr(
        asistencias_routes,
        "get_configuracion_empresa_by_id",
        lambda empresa_id: {"intervalo_minimo_fichadas_minutos": 60},
    )
    monkeypatch.setattr(asistencias_routes, "get_page", lambda *args, **kwargs: ([], 0))

    resp = client.get("/asistencias/planilla?empresa_id=1&sucursal_id=10&fecha=2026-03-10")
    assert resp.status_code == 200
    assert b"Planilla diaria de fichadas" in resp.data
    assert b"Del Palacio S.A" in resp.data
    assert b"Casa Central" in resp.data
    assert b"07:00" in resp.data
    assert b"12:00" in resp.data
    html = resp.get_data(as_text=True)
    assert "/asistencias/planilla/marca/editar/1" in html
    assert "/asistencias/planilla/marca/eliminar/1" in html


def test_planilla_diaria_detecta_intervalo_corto(monkeypatch):
    client = _build_client(monkeypatch)
    _login_session(client)
    monkeypatch.setattr(auth_decorators, "has_role", lambda actor_id, role: True)
    monkeypatch.setattr(asistencias_routes, "get_empresas", lambda include_inactive=True: [{"id": 1, "razon_social": "X"}])
    monkeypatch.setattr(asistencias_routes, "get_sucursales", lambda include_inactive=True: [])
    monkeypatch.setattr(
        asistencias_routes,
        "get_empleados",
        lambda include_inactive=True: [
            {"id": 101, "empresa_id": 1, "sucursal_id": None, "apellido": "Persona", "nombre": "Dos", "dni": "222"}
        ],
    )
    monkeypatch.setattr(
        asistencias_routes,
        "get_marcas_admin_export",
        lambda **kwargs: [
            {"id": 1, "empleado_id": 101, "asistencia_id": 88, "hora": "07:00:00", "accion": "ingreso"},
            {"id": 2, "empleado_id": 101, "asistencia_id": 88, "hora": "07:10:00", "accion": "egreso"},
        ],
    )
    monkeypatch.setattr(
        asistencias_routes,
        "get_configuracion_empresa_by_id",
        lambda empresa_id: {"intervalo_minimo_fichadas_minutos": 60},
    )
    monkeypatch.setattr(asistencias_routes, "get_page", lambda *args, **kwargs: ([], 0))

    resp = client.get("/asistencias/planilla?empresa_id=1&fecha=2026-03-10")
    html = resp.get_data(as_text=True)
    assert resp.status_code == 200
    assert "Intervalo corto" in html


def test_planilla_diaria_normaliza_hora_hhmm(monkeypatch):
    client = _build_client(monkeypatch)
    _login_session(client)
    monkeypatch.setattr(auth_decorators, "has_role", lambda actor_id, role: True)
    monkeypatch.setattr(asistencias_routes, "get_empresas", lambda include_inactive=True: [{"id": 1, "razon_social": "X"}])
    monkeypatch.setattr(asistencias_routes, "get_sucursales", lambda include_inactive=True: [])
    monkeypatch.setattr(
        asistencias_routes,
        "get_empleados",
        lambda include_inactive=True: [
            {"id": 101, "empresa_id": 1, "sucursal_id": None, "apellido": "Persona", "nombre": "Dos", "dni": "222"}
        ],
    )
    monkeypatch.setattr(
        asistencias_routes,
        "get_marcas_admin_export",
        lambda **kwargs: [
            {"id": 1, "empleado_id": 101, "asistencia_id": 88, "hora": "8:01:00", "accion": "ingreso"},
        ],
    )
    monkeypatch.setattr(
        asistencias_routes,
        "get_configuracion_empresa_by_id",
        lambda empresa_id: {"intervalo_minimo_fichadas_minutos": 60},
    )
    monkeypatch.setattr(asistencias_routes, "get_page", lambda *args, **kwargs: ([], 0))

    resp = client.get("/asistencias/planilla?empresa_id=1&fecha=2026-03-10")
    html = resp.get_data(as_text=True)
    assert resp.status_code == 200
    assert "08:01" in html


def test_planilla_diaria_export_excel_ok(monkeypatch):
    client = _build_client(monkeypatch)
    _login_session(client)
    monkeypatch.setattr(auth_decorators, "has_role", lambda actor_id, role: True)
    monkeypatch.setattr(
        asistencias_routes,
        "get_empresas",
        lambda include_inactive=True: [{"id": 1, "razon_social": "Del Palacio S.A"}],
    )
    monkeypatch.setattr(
        asistencias_routes,
        "get_sucursales",
        lambda include_inactive=True: [{"id": 10, "empresa_id": 1, "nombre": "Casa Central"}],
    )
    monkeypatch.setattr(
        asistencias_routes,
        "get_empleados",
        lambda include_inactive=True: [
            {"id": 100, "empresa_id": 1, "sucursal_id": 10, "apellido": "Persona", "nombre": "Uno", "dni": "123"}
        ],
    )
    monkeypatch.setattr(
        asistencias_routes,
        "get_marcas_admin_export",
        lambda **kwargs: [
            {"id": 1, "empleado_id": 100, "asistencia_id": 77, "hora": "07:00:00", "accion": "ingreso"},
            {"id": 2, "empleado_id": 100, "asistencia_id": 77, "hora": "12:00:00", "accion": "egreso"},
        ],
    )
    monkeypatch.setattr(
        asistencias_routes,
        "get_configuracion_empresa_by_id",
        lambda empresa_id: {"intervalo_minimo_fichadas_minutos": 60},
    )
    monkeypatch.setattr(asistencias_routes, "get_page", lambda *args, **kwargs: ([], 0))

    resp = client.get("/asistencias/planilla.xls?empresa_id=1&sucursal_id=10&fecha=2026-03-10")
    assert resp.status_code == 200
    assert "application/vnd.ms-excel" in resp.headers["Content-Type"]
    assert "planilla_fichadas_2026-03-10.xls" in resp.headers["Content-Disposition"]
    assert b"Del Palacio S.A" in resp.data
    assert b"07:00" in resp.data


def test_planilla_diaria_export_pdf_ok(monkeypatch):
    client = _build_client(monkeypatch)
    _login_session(client)
    monkeypatch.setattr(auth_decorators, "has_role", lambda actor_id, role: True)
    monkeypatch.setattr(asistencias_routes, "get_empresas", lambda include_inactive=True: [{"id": 1, "razon_social": "X"}])
    monkeypatch.setattr(asistencias_routes, "get_sucursales", lambda include_inactive=True: [])
    monkeypatch.setattr(
        asistencias_routes,
        "get_empleados",
        lambda include_inactive=True: [
            {"id": 101, "empresa_id": 1, "sucursal_id": None, "apellido": "Persona", "nombre": "Dos", "dni": "222"}
        ],
    )
    monkeypatch.setattr(
        asistencias_routes,
        "get_marcas_admin_export",
        lambda **kwargs: [
            {"id": 1, "empleado_id": 101, "asistencia_id": 88, "hora": "07:00:00", "accion": "ingreso"},
            {"id": 2, "empleado_id": 101, "asistencia_id": 88, "hora": "12:00:00", "accion": "egreso"},
        ],
    )
    monkeypatch.setattr(
        asistencias_routes,
        "get_configuracion_empresa_by_id",
        lambda empresa_id: {"intervalo_minimo_fichadas_minutos": 60},
    )
    monkeypatch.setattr(asistencias_routes, "get_page", lambda *args, **kwargs: ([], 0))

    resp = client.get("/asistencias/planilla.pdf?empresa_id=1&fecha=2026-03-10&auto_print=1")
    html = resp.get_data(as_text=True)
    assert resp.status_code == 200
    assert "text/html" in resp.headers["Content-Type"]
    assert "window.print" in html
    assert "Planilla diaria de fichadas" in html


def test_planilla_marca_editar_get_ok(monkeypatch):
    client = _build_client(monkeypatch)
    _login_session(client)
    monkeypatch.setattr(auth_decorators, "has_role", lambda actor_id, role: True)
    monkeypatch.setattr(
        asistencias_routes,
        "get_marca_by_id",
        lambda marca_id: {"id": marca_id, "asistencia_id": 77, "fecha": "2026-03-10", "hora": "08:00:00", "accion": "ingreso"},
    )

    resp = client.get("/asistencias/planilla/marca/editar/1?empresa_id=1&sucursal_id=10&fecha=2026-03-10")
    assert resp.status_code == 200
    assert b"Editar marca" in resp.data
    assert b"08:00" in resp.data


def test_planilla_diaria_muestra_asistencia_manual_sin_marcas(monkeypatch):
    client = _build_client(monkeypatch)
    _login_session(client)
    monkeypatch.setattr(auth_decorators, "has_role", lambda actor_id, role: True)
    monkeypatch.setattr(
        asistencias_routes,
        "get_empresas",
        lambda include_inactive=True: [{"id": 1, "razon_social": "Del Palacio S.A"}],
    )
    monkeypatch.setattr(
        asistencias_routes,
        "get_sucursales",
        lambda include_inactive=True: [{"id": 10, "empresa_id": 1, "nombre": "Casa Central"}],
    )
    monkeypatch.setattr(
        asistencias_routes,
        "get_empleados",
        lambda include_inactive=True: [
            {"id": 200, "empresa_id": 1, "sucursal_id": 10, "apellido": "Manual", "nombre": "SinMarca", "dni": "456"}
        ],
    )
    monkeypatch.setattr(asistencias_routes, "get_marcas_admin_export", lambda **kwargs: [])
    monkeypatch.setattr(
        asistencias_routes,
        "get_page",
        lambda *args, **kwargs: (
            [
                {
                    "id": 901,
                    "empleado_id": 200,
                    "fecha": "2026-03-10",
                    "hora_entrada": "08:00:00",
                    "hora_salida": "12:00:00",
                    "gps_ok_entrada": 1,
                    "gps_ok_salida": 1,
                }
            ],
            1,
        ),
    )
    monkeypatch.setattr(
        asistencias_routes,
        "get_configuracion_empresa_by_id",
        lambda empresa_id: {"intervalo_minimo_fichadas_minutos": 60},
    )

    resp = client.get("/asistencias/planilla?empresa_id=1&sucursal_id=10&fecha=2026-03-10")
    html = resp.get_data(as_text=True)
    assert resp.status_code == 200
    assert "Manual SinMarca" in html
    assert "08:00" in html
    assert "12:00" in html


def test_planilla_marca_eliminar_post_ok(monkeypatch):
    client = _build_client(monkeypatch)
    _login_session(client)
    monkeypatch.setattr(auth_decorators, "has_role", lambda actor_id, role: True)
    monkeypatch.setattr(
        asistencias_routes,
        "get_marca_by_id",
        lambda marca_id: {"id": marca_id, "asistencia_id": 77, "fecha": "2026-03-10", "hora": "08:00:00", "accion": "ingreso"},
    )
    deleted = {"ok": False}
    synced = {"ok": False}
    monkeypatch.setattr(asistencias_routes, "delete_marca_by_id", lambda marca_id: deleted.__setitem__("ok", True) or True)
    monkeypatch.setattr(
        asistencias_routes, "sync_from_asistencia_marcas", lambda asistencia_id: synced.__setitem__("ok", True) or True
    )
    monkeypatch.setattr(asistencias_routes, "log_audit", lambda *args, **kwargs: True)

    resp = client.post(
        "/asistencias/planilla/marca/eliminar/1",
        data={"empresa_id": "1", "sucursal_id": "10", "fecha": "2026-03-10"},
        follow_redirects=False,
    )
    assert resp.status_code == 302
    assert "/asistencias/planilla" in resp.headers["Location"]
    assert "msg=Marca+%231+eliminada." in resp.headers["Location"]
    assert deleted["ok"] is True
    assert synced["ok"] is True


def test_planilla_marca_agregar_post_ok(monkeypatch):
    client = _build_client(monkeypatch)
    _login_session(client)
    monkeypatch.setattr(auth_decorators, "has_role", lambda actor_id, role: True)
    monkeypatch.setattr(
        asistencias_routes,
        "get_by_id",
        lambda asistencia_id: {
            "id": asistencia_id,
            "empresa_id": 1,
            "empleado_id": 101,
            "fecha": "2026-03-10",
            "lat_salida": None,
            "lon_salida": None,
            "foto_salida": None,
            "metodo_salida": "manual",
            "gps_ok_salida": None,
            "gps_distancia_salida_m": None,
            "gps_tolerancia_salida_m": None,
            "gps_ref_lat_salida": None,
            "gps_ref_lon_salida": None,
            "estado": "ok",
        },
    )
    monkeypatch.setattr(asistencias_routes, "create_marca", lambda **kwargs: 999)
    monkeypatch.setattr(asistencias_routes, "sync_from_asistencia_marcas", lambda asistencia_id: True)
    monkeypatch.setattr(asistencias_routes, "log_audit", lambda *args, **kwargs: True)

    resp = client.post(
        "/asistencias/planilla/marca/agregar",
        data={
            "asistencia_id": "77",
            "accion": "egreso",
            "hora": "12:00",
            "empresa_id": "1",
            "sucursal_id": "10",
            "fecha": "2026-03-10",
        },
        follow_redirects=False,
    )
    assert resp.status_code == 302
    assert "/asistencias/planilla" in resp.headers["Location"]
    assert "msg=Marca+%23999+agregada." in resp.headers["Location"]
