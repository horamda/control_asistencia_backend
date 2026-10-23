"""Inicio del panel: lo de hoy, lo pendiente y el mes, segun los permisos de cada usuario."""
import datetime as dt

import app as app_module
import web.auth.decorators as auth_decorators
import web.web_routes as web_routes
from services import inicio_service

ASISTENCIA = dict(hoy=dict(dotacion=40, presentes=31, presentismo_pct=77.5, tarde=3, ausentes=2),
                  mes=dict(ausentismo_pct=6.2, puntualidad_pct=88.0, ausentes=12, sin_justificar=4,
                           sin_justificar_pct=33.3, tardes=17))
PENDIENTES = [dict(clave="justificaciones", titulo="Justificaciones", descripcion="Para aprobar o rechazar", cantidad=5,
                   ruta="/justificaciones/?estado=pendiente"),
              dict(clave="adelantos", titulo="Adelantos", descripcion="Para pagar o rechazar", cantidad=0,
                   ruta="/adelantos/?estado=pendiente")]


def _client(monkeypatch, modulos, resumen=None, usuario=None):
    monkeypatch.setattr(app_module, "init_db", lambda: None)
    monkeypatch.setattr(web_routes, "_cached_web_user", lambda uid: usuario or dict(id=uid, rol="admin", empresa_id=1, activo=1))
    monkeypatch.setattr(auth_decorators, "can_access_module", lambda uid, modulo, accion="ver": modulo in modulos)
    monkeypatch.setattr(web_routes, "can_access_module", lambda uid, modulo, accion="ver": modulo in modulos)
    monkeypatch.setattr(web_routes, "get_empresas", lambda include_inactive=False: [
        dict(id=1, razon_social="Empresa A"), dict(id=2, razon_social="Empresa B")])
    monkeypatch.setattr(web_routes, "get_sucursales", lambda include_inactive=False: [
        dict(id=7, nombre="Casa Central", empresa_id=1), dict(id=8, nombre="Dolores", empresa_id=2)])
    llamadas = []

    def falso(*, puede, empresa_id=None, sucursal_id=None):
        llamadas.append(dict(asistencias=puede("asistencias"), empresa_id=empresa_id, sucursal_id=sucursal_id))
        if resumen:
            return resumen(puede)
        return dict(asistencia=ASISTENCIA if puede("asistencias") else None,
                    pendientes=[p for p in PENDIENTES if puede({"adelantos": "pedidos_empleados"}.get(p["clave"], p["clave"]))])

    monkeypatch.setattr(inicio_service, "resumen", falso)
    app = app_module.create_app()
    app.config["TESTING"] = True
    client = app.test_client()
    with client.session_transaction() as sess:
        sess["user_id"] = 5
    return client, llamadas


def test_inicio_con_todo(monkeypatch):
    client, llamadas = _client(monkeypatch, {"asistencias", "justificaciones", "pedidos_empleados"})
    html = client.get("/dashboard?empresa_id=1").get_data(as_text=True)
    assert llamadas == [dict(asistencias=True, empresa_id=1, sucursal_id=None)]
    assert ">Hoy</h3>" in html and "de 40 · 77.5% fichó hoy" in html
    assert ">Para resolver</h3>" in html and "5 en total" in html
    assert 'href="/justificaciones/?estado=pendiente"' in html
    assert ">Adelantos</span>" not in html  # en cero no se muestra
    assert ">Este mes</h3>" in html and "6.2%" in html and "88.0%" in html
    assert 'hx-get="/dashboard/evolucion?empresa_id=1"' in html
    assert "/estadisticas-asistencia?empresa_id=1" in html
    # Filtro: con empresa elegida solo quedan sus sucursales.
    assert "Casa Central" in html and "Dolores" not in html
    # Lo que se fue a Estadisticas ya no esta en el inicio.
    for viejo in ("Top reincidencia", "Accesos rapidos", "Semaforo de riesgo", "Personas con mas ausencias"):
        assert viejo not in html


def test_inicio_sin_asistencias_muestra_solo_sus_pendientes(monkeypatch):
    client, llamadas = _client(monkeypatch, {"justificaciones"})
    html = client.get("/dashboard").get_data(as_text=True)
    assert llamadas[0]["asistencias"] is False
    assert ">Hoy</h3>" not in html and ">Este mes</h3>" not in html
    assert "/dashboard/evolucion" not in html and "dashboard-filter-form" not in html
    assert "Presencia en vivo" not in html
    assert ">Para resolver</h3>" in html and ">Justificaciones</span>" in html


def test_inicio_sin_pendientes_lo_dice(monkeypatch):
    client, _ = _client(monkeypatch, {"justificaciones"}, resumen=lambda puede: dict(
        asistencia=None, pendientes=[dict(PENDIENTES[0], cantidad=0)]))
    html = client.get("/dashboard").get_data(as_text=True)
    assert "No hay nada pendiente en tus módulos." in html


def test_inicio_sin_permisos_da_la_bienvenida(monkeypatch):
    client, _ = _client(monkeypatch, set())
    resp = client.get("/dashboard")
    assert resp.status_code == 200
    assert "Usá el menú de la izquierda" in resp.get_data(as_text=True)


def test_inicio_sobrevive_a_un_error(monkeypatch):
    def falla(puede):
        raise RuntimeError("sin base")

    client, _ = _client(monkeypatch, {"asistencias"}, resumen=falla)
    resp = client.get("/dashboard")
    assert resp.status_code == 200
    assert "No se pudieron calcular los números de asistencia" in resp.get_data(as_text=True)


def test_quien_no_es_admin_ve_solo_su_empresa(monkeypatch):
    rrhh = dict(id=5, rol="rrhh", empresa_id=2, activo=1)
    client, llamadas = _client(monkeypatch, {"asistencias", "justificaciones"}, usuario=rrhh)
    html = client.get("/dashboard?empresa_id=1").get_data(as_text=True)  # pide otra empresa: se ignora
    assert llamadas == [dict(asistencias=True, empresa_id=2, sucursal_id=None)]
    # Una sola empresa y una sola sucursal: no hay nada para elegir, no se muestra el filtro.
    assert "dashboard-filter-form" not in html and "Empresa A" not in html and "Casa Central" not in html
    assert 'hx-get="/dashboard/evolucion?empresa_id=2"' in html


def test_estadisticas_y_evolucion_de_quien_no_es_admin_usan_su_empresa(monkeypatch):
    rrhh = dict(id=5, rol="supervisor", empresa_id=2, activo=1)
    client, _ = _client(monkeypatch, {"asistencias"}, usuario=rrhh)
    pedidas = []
    monkeypatch.setattr(web_routes, "_dashboard_metrics", lambda empresa_forzada=None: (
        pedidas.append(empresa_forzada) or ({}, [], {})))
    monkeypatch.setattr(web_routes, "get_dias_no_laborables", lambda **kwargs: set())
    client.get("/estadisticas-asistencia?empresa_id=1")  # (sin numeros la pagina no se dibuja; importa el alcance)
    assert pedidas == [2]
    tendencias = []
    monkeypatch.setattr(web_routes, "_dashboard_trends", lambda **kw: tendencias.append(kw) or {"meses": [], "dias_semana": []})
    client.get("/dashboard/evolucion?empresa_id=1&meses=6")
    assert tendencias and tendencias[0]["empresa_id"] == 2


PRESENCIA = dict(fecha="2026-10-22", actualizado="2026-10-22T10:42:05-03:00", sucursales=[
    dict(id=7, nombre="Casa Central", empresa="Empresa A", empleados=20, presentes=15, vinieron=17, retirados=2,
         sin_ingreso=3, personas=[dict(nombre="Perez Ana")]),
    dict(id=8, nombre="Dolores", empresa="Empresa A", empleados=6, presentes=0, vinieron=1, retirados=1,
         sin_ingreso=5, personas=[])])


def test_presencia_resume_por_sucursal_sin_nombres(monkeypatch):
    import services.presencia_service as presencia_service

    pedidas = []
    monkeypatch.setattr(presencia_service, "build_presence", lambda empresa_id=None: pedidas.append(empresa_id) or PRESENCIA)
    todo = inicio_service.presencia(empresa_id=1)
    assert pedidas == [1] and todo["actualizado"] == "10:42"
    assert todo["totales"] == dict(empleados=26, presentes=15, vinieron=18, retirados=3, sin_ingreso=8)
    assert "personas" not in todo["sucursales"][0] and todo["varias_empresas"] is False
    solo = inicio_service.presencia(empresa_id=1, sucursal_id=8)
    assert [b["nombre"] for b in solo["sucursales"]] == ["Dolores"]


def test_inicio_muestra_tarjetas_de_presencia(monkeypatch):
    client, _ = _client(monkeypatch, {"asistencias"})
    monkeypatch.setattr(inicio_service, "presencia", lambda empresa_id=None, sucursal_id=None: dict(
        sucursales=[dict(b, empresa="Empresa A") for b in PRESENCIA["sucursales"]], totales={},
        varias_empresas=False, actualizado="10:42"))
    html = client.get("/dashboard").get_data(as_text=True)
    assert "Ahora en las sucursales" in html and "10:42 h" in html
    assert ">Casa Central</span>" in html and "15<small" in html and "de 20" in html
    assert "vinieron 17 · se fueron 2 · sin ingreso 3" in html
    assert "Perez Ana" not in html
    assert ">Ficharon hoy</span>" in html


def test_presencia_no_se_consulta_sin_empresa_ni_sin_permiso(monkeypatch):
    llamadas = []
    sin_empresa = dict(id=5, rol="rrhh", empresa_id=None, activo=1)
    client, _ = _client(monkeypatch, {"asistencias"}, usuario=sin_empresa)
    monkeypatch.setattr(inicio_service, "presencia", lambda **kw: llamadas.append(kw))
    client.get("/dashboard")
    client2, _ = _client(monkeypatch, {"justificaciones"})
    monkeypatch.setattr(inicio_service, "presencia", lambda **kw: llamadas.append(kw))
    assert "Ahora en las sucursales" not in client2.get("/dashboard").get_data(as_text=True)
    assert llamadas == []


def test_estadisticas_pide_permiso_de_asistencias(monkeypatch):
    client, _ = _client(monkeypatch, {"justificaciones"})
    assert client.get("/estadisticas-asistencia").status_code == 403


def test_menu_tiene_estadisticas(monkeypatch):
    client, _ = _client(monkeypatch, {"asistencias"})
    assert 'href="/estadisticas-asistencia">Estadísticas</a>' in client.get("/dashboard").get_data(as_text=True)


# --- MySQL real (SH_TEST_DB_PORT) -------------------------------------------------------------------------------
from tests.test_seguridad import database  # noqa: E402,F401  (fixture)


def test_resumen_en_la_base_respeta_alcance_y_permisos(database, monkeypatch):  # noqa: F811
    monkeypatch.setattr(inicio_service, "get_db", database)
    hoy = dt.date(2026, 10, 22)
    conn = database()
    c = conn.cursor()
    for sql in [
        "ALTER TABLE empleados ADD COLUMN requiere_control_asistencia TINYINT NULL",
        "CREATE TABLE empleado_periodos_laborales (empleado_id INT, fecha_desde DATE NULL, fecha_hasta DATE NULL)",
        "INSERT INTO empleado_periodos_laborales SELECT id, NULL, NULL FROM empleados",
        """CREATE TABLE asistencias (id INT AUTO_INCREMENT PRIMARY KEY, empleado_id INT, fecha DATE, hora_entrada TIME NULL,
             hora_salida TIME NULL, estado VARCHAR(20))""",
        """CREATE TABLE justificaciones (id INT AUTO_INCREMENT PRIMARY KEY, empleado_id INT, fecha DATE NULL,
             fecha_desde DATE NULL, fecha_hasta DATE NULL, estado VARCHAR(20) NULL)""",
        # Empresa 1: 10 y 11 (sucursal 1) y 12 (sucursal 2) y 13 (sucursal 1). Empresa 2: 20.
        """INSERT INTO asistencias (empleado_id, fecha, hora_entrada, estado) VALUES
             (10, '2026-10-22', '08:00', 'ok'), (11, '2026-10-22', '08:20', 'tarde'), (12, '2026-10-22', NULL, 'ausente'),
             (10, '2026-10-21', '08:00', 'ok'), (11, '2026-10-21', NULL, 'ausente'), (12, '2026-10-20', NULL, 'ausente'),
             (20, '2026-10-22', '09:00', 'ok'), (20, '2026-10-21', NULL, 'ausente')""",
        """INSERT INTO justificaciones (empleado_id, fecha_desde, fecha_hasta, estado) VALUES
             (11, '2026-10-21', '2026-10-21', 'aprobada'), (12, '2026-10-01', '2026-10-01', 'pendiente'),
             (20, '2026-10-02', '2026-10-02', NULL)""",
    ]:
        c.execute(sql)
    conn.commit()
    c.close()
    conn.close()

    from flask import Flask

    with Flask(__name__).app_context():
        todo = inicio_service.resumen(puede=lambda m: True, hoy=hoy)
        assert todo["asistencia"]["hoy"] == dict(dotacion=5, presentes=3, presentismo_pct=60.0, tarde=1, ausentes=1)
        # Mes: 8 registros, 4 ausencias (1 justificada), 4 fichadas de las que 3 a tiempo.
        assert todo["asistencia"]["mes"] == dict(ausentismo_pct=50.0, puntualidad_pct=75.0, ausentes=4, sin_justificar=3,
                                                 sin_justificar_pct=75.0, tardes=1)
        pend = {p["clave"]: p["cantidad"] for p in todo["pendientes"]}
        assert pend == {"justificaciones": 2, "seguridad": 0}  # las tablas que no existen en esta base se omiten

        empresa1 = inicio_service.resumen(puede=lambda m: True, empresa_id=1, hoy=hoy)
        assert empresa1["asistencia"]["hoy"]["dotacion"] == 4 and empresa1["asistencia"]["hoy"]["presentes"] == 2
        assert {p["clave"]: p["cantidad"] for p in empresa1["pendientes"]} == {"justificaciones": 1, "seguridad": 0}
        sucursal2 = inicio_service.resumen(puede=lambda m: True, empresa_id=1, sucursal_id=2, hoy=hoy)
        assert sucursal2["asistencia"]["hoy"] == dict(dotacion=1, presentes=0, presentismo_pct=0.0, tarde=0, ausentes=1)

        sin_permiso = inicio_service.resumen(puede=lambda m: m == "pedidos_empleados", hoy=hoy)
        assert sin_permiso["asistencia"] is None and sin_permiso["pendientes"] == []


def test_estadisticas_con_empresa_fija_no_cuentan_otras_empresas(database, monkeypatch):  # noqa: F811
    from flask import Flask

    import web.dashboard_metrics as metricas

    monkeypatch.setattr(metricas, "get_db", database)
    conn = database()
    c = conn.cursor()
    for sql in [
        "ALTER TABLE empleados ADD COLUMN requiere_control_asistencia TINYINT NULL",
        "CREATE TABLE empleado_periodos_laborales (empleado_id INT, fecha_desde DATE NULL, fecha_hasta DATE NULL)",
        "INSERT INTO empleado_periodos_laborales SELECT id, NULL, NULL FROM empleados",
        """CREATE TABLE asistencias (id INT AUTO_INCREMENT PRIMARY KEY, empleado_id INT, fecha DATE, hora_entrada TIME NULL,
             hora_salida TIME NULL, estado VARCHAR(20))""",
        "CREATE TABLE usuarios (id INT PRIMARY KEY, empresa_id INT, activo TINYINT, usuario VARCHAR(40))",
        "INSERT INTO usuarios VALUES (1, 1, 1, 'a'), (2, 1, 1, 'b'), (3, 2, 1, 'c')",
        f"""INSERT INTO asistencias (empleado_id, fecha, hora_entrada, estado) VALUES
             (10, CURDATE(), '08:00', 'ok'), (11, CURDATE(), '08:30', 'tarde'), (20, CURDATE(), NULL, 'ausente')""",
    ]:
        c.execute(sql)
    conn.commit()
    c.close()
    conn.close()
    app = Flask(__name__)
    with app.test_request_context("/estadisticas-asistencia"):
        todas, _, _ = metricas._dashboard_metrics()  # admin sin filtro: todas las empresas, como siempre
    with app.test_request_context("/estadisticas-asistencia?empresa_id=1"):
        solo2, _, _ = metricas._dashboard_metrics(empresa_forzada=2)  # pide la 1, pero es de la 2
    assert todas["usuarios_activos"] == 3 and todas["asistencias_hoy"] == 3
    assert solo2["empleados_activos"] == 1  # solo el empleado 20
    assert solo2["usuarios_activos"] == 1
    assert solo2["asistencias_hoy"] == 1 and solo2["ausentes_hoy"] == 1 and solo2["tardes_hoy"] == 0
    assert solo2["scope_kind"] == "empresa"
