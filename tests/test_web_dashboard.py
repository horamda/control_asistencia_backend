import app as app_module
import web.web_routes as web_routes


def _build_client(monkeypatch):
    monkeypatch.setattr(app_module, "init_db", lambda: None)
    app = app_module.create_app()
    app.config["TESTING"] = True
    app.config["WTF_CSRF_ENABLED"] = False
    return app.test_client()


def _login_session(client):
    with client.session_transaction() as sess:
        sess["user_id"] = 77


def test_dashboard_rrhh_render_ok(monkeypatch):
    client = _build_client(monkeypatch)
    _login_session(client)
    monkeypatch.setattr(
        web_routes,
        "_dashboard_metrics",
        lambda: (
            {
                "empleados_activos": 120,
                "empleados_con_fichada_hoy": 98,
                "presentismo_hoy_pct": 81.7,
                "asistencias_hoy": 101,
                "fichadas_mes": 960,
                "ok_fichadas_mes": 802,
                "puntualidad_mes_pct": 83.5,
                "asistencias_30d": 2240,
                "asistencias_mes": 980,
                "asistencias_anio": 2240,
                "tardes_hoy": 11,
                "tardes_30d": 210,
                "tardes_mes": 95,
                "tardes_anio": 210,
                "ausentes_hoy": 8,
                "ausentes_30d": 190,
                "ausentes_mes": 84,
                "ausentes_anio": 190,
                "ausentes_trimestre": 120,
                "ausentismo_mes_pct": 8.6,
                "ausentismo_anual_pct": 8.5,
                "frecuencia_ausencias_mes": 0.7,
                "frecuencia_ausencias_trimestre": 1.0,
                "ausentes_sin_justificacion_mes": 21,
                "no_show_mes_pct": 25.0,
                "justificaciones_mes_total": 38,
                "justificaciones_mes_pendientes": 9,
                "justificaciones_mes_aprobadas": 24,
                "justificaciones_mes_rechazadas": 5,
                "tasa_aprobacion_justificaciones_mes_pct": 63.2,
                "justificaciones_pendientes_total": 14,
                "jornadas_completas_mes": 870,
                "cumplimiento_jornada_mes_pct": 90.6,
                "salida_anticipada_mes": 44,
                "tasa_salida_anticipada_mes_pct": 4.6,
                "vacaciones_en_curso_hoy": 6,
                "vacaciones_proximas_30d": 11,
                "vacaciones_dias_mes": 74,
                "vacaciones_dias_anio": 331,
                "horas_registradas_mes": 7120.5,
                "horas_esperadas_mes": 7360.0,
                "desvio_horas_mes": -239.5,
                "cumplimiento_horas_mes_pct": 96.7,
                "incidentes_regularizados_mes": 93,
                "incidentes_sin_regularizar_mes": 47,
                "lead_time_regularizacion_horas_mes": 29.3,
                "reincidencia_umbral": 3,
                "excepciones_hoy": 3,
                "horarios_activos": 6,
                "asignaciones_vigentes": 117,
                "usuarios_activos": 9,
            },
            [
                {
                    "fecha": "2026-02-27 10:00:00",
                    "accion": "update",
                    "tabla_afectada": "asistencias",
                    "registro_id": 10,
                    "usuario_nombre": "admin",
                }
            ],
            {
                "daily_7d": [
                    {"fecha": "2026-02-21", "dia": "21/02", "asistencias": 100, "tardes": 7, "ausentes": 5},
                    {"fecha": "2026-02-22", "dia": "22/02", "asistencias": 104, "tardes": 9, "ausentes": 4},
                ],
                "max_daily": 104,
                "status_30d": [
                    {"key": "ok", "label": "OK", "tone": "ok", "total": 1800, "pct": 80.4},
                    {"key": "tarde", "label": "Tarde", "tone": "warning", "total": 210, "pct": 9.4},
                    {"key": "ausente", "label": "Ausente", "tone": "danger", "total": 190, "pct": 8.5},
                ],
                "empresa_top_30d": [
                    {
                        "empresa": "Empresa A",
                        "total": 400,
                        "ausentes": 40,
                        "tardes": 25,
                        "ausentes_pct": 100.0,
                        "tardes_pct": 62.5,
                    }
                ],
                "max_empresa": 40,
                "justificaciones_estado_mes": [
                    {"key": "pendiente", "label": "Pendiente", "tone": "warning", "total": 9, "pct": 23.7},
                    {"key": "aprobada", "label": "Aprobada", "tone": "ok", "total": 24, "pct": 63.2},
                    {"key": "rechazada", "label": "Rechazada", "tone": "danger", "total": 5, "pct": 13.2},
                ],
                "persona_top_ausencias_anio": [
                    {
                        "empleado_id": 13,
                        "apellido": "Perez",
                        "nombre": "Ana",
                        "dni": "30111222",
                        "empresa": "Empresa A",
                        "ausencias": 14,
                        "tardanzas": 9,
                        "total": 160,
                    }
                ],
                "top_reincidencia_mes": [
                    {
                        "empleado_id": 13,
                        "apellido": "Perez",
                        "nombre": "Ana",
                        "dni": "30111222",
                        "empresa": "Empresa A",
                        "ausencias": 4,
                        "tardanzas": 3,
                        "salidas_anticipadas": 1,
                        "incidentes": 8,
                    }
                ],
                "streak_top_empleados": [
                    {
                        "empleado_id": 9,
                        "apellido": "Gomez",
                        "nombre": "Luis",
                        "dni": "32222111",
                        "empresa": "Empresa A",
                        "sector": "Operaciones",
                        "sucursal": "Centro",
                        "streak": 12,
                    }
                ],
                "streak_top_equipos": [
                    {"equipo": "Empresa A", "promedio_racha": 5.4, "max_racha": 12, "empleados_con_racha": 17}
                ],
                "ausentismo_rank_empresa": [
                    {
                        "nombre": "Empresa A",
                        "dotacion": 50,
                        "ausentes": 40,
                        "indice_ausencias_por_empleado": 0.8,
                        "tasa_pct": 1.6,
                    }
                ],
                "ausentismo_rank_sector": [
                    {
                        "nombre": "Operaciones",
                        "dotacion": 25,
                        "ausentes": 30,
                        "indice_ausencias_por_empleado": 1.2,
                        "tasa_pct": 2.4,
                    }
                ],
                "ausentismo_rank_sucursal": [
                    {
                        "nombre": "Centro",
                        "dotacion": 35,
                        "ausentes": 28,
                        "indice_ausencias_por_empleado": 0.8,
                        "tasa_pct": 1.6,
                    }
                ],
                "vacaciones_proximas_detalle": [
                    {
                        "id": 99,
                        "fecha_desde": "2026-03-03",
                        "fecha_hasta": "2026-03-10",
                        "apellido": "Lopez",
                        "nombre": "Maria",
                        "empresa": "Empresa A",
                        "dias": 8,
                    }
                ],
                "vacaciones_top_dias_anio": [
                    {
                        "empleado_id": 25,
                        "apellido": "Gonzalez",
                        "nombre": "Tomas",
                        "empresa": "Empresa A",
                        "dias": 21,
                        "dias_pct": 100.0,
                    }
                ],
            },
        ),
    )

    resp = client.get("/dashboard")
    assert resp.status_code == 200
    assert b"Dashboard de asistencia" in resp.data
    assert b"Top empresas con mas ausencias/tardanzas" in resp.data
    assert b"Personas con mas ausencias (acumulado anual)" in resp.data
    assert b"Puntualidad mes" in resp.data
    assert b"Indice no-show mes" in resp.data
    assert b"Justificaciones del mes" in resp.data
    assert b"Vacaciones proximas (30 dias)" in resp.data
    assert b"Torta de estados (30 dias)" in resp.data
    assert b"Aprobacion justif. mes" in resp.data
    assert b"Top reincidencia (incidentes del mes)" in resp.data
    assert b"Lead time de regularizacion (mes)" in resp.data
    assert b"% ausentismo mes" in resp.data
    assert b"Empresa A" in resp.data
    assert b"Perez Ana" in resp.data
