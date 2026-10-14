import datetime

import app as app_module
import web.dashboard_metrics as metrics
import web.web_routes as web_routes
from services.svg_chart_service import _nice_ticks, column_chart, line_chart

LABELS = [{"label": m, "sub": ""} for m in ("Ago", "Sep", "Oct")]


# --- Geometria ----------------------------------------------------------------

def test_nice_ticks_use_round_steps():
    assert _nice_ticks(0, 7.3) == [0, 2, 4, 6, 8]
    assert _nice_ticks(80, 100) == [80, 85, 90, 95, 100]


def test_line_chart_breaks_path_on_missing_month_and_scales_to_ticks():
    chart = line_chart(LABELS, [{"key": "a", "name": "A", "values": [4.0, None, 6.0]}])
    serie = chart["series"][0]
    # Un mes sin datos corta la linea en dos tramos en lugar de inventar un valor.
    assert serie["path"].count("M") == 2
    assert [p["index"] for p in serie["points"]] == [0, 2]
    assert serie["end_label"] == "6.0%"
    assert chart["y_ticks"][0]["label"] == "0%"
    assert chart["plot"]["top"] <= min(p["y"] for p in serie["points"])
    assert len(chart["columns"]) == 3


def test_line_chart_drops_end_labels_when_series_converge():
    close = line_chart(LABELS, [
        {"key": "a", "name": "A", "values": [1, 2, 3.0]},
        {"key": "b", "name": "B", "values": [1, 2, 3.1]},
    ])
    apart = line_chart(LABELS, [
        {"key": "a", "name": "A", "values": [1, 2, 9.0]},
        {"key": "b", "name": "B", "values": [1, 2, 1.0]},
    ])
    assert close["show_end_labels"] is False
    assert apart["show_end_labels"] is True


def test_line_chart_caps_axis_at_y_max():
    chart = line_chart(LABELS, [{"key": "p", "name": "P", "values": [88.0, 92.5, 97.0]}], y_min=None, y_max=100)
    labels = [t["label"] for t in chart["y_ticks"]]
    assert labels[-1] == "100%"
    assert float(labels[0].rstrip("%")) < 88


def test_empty_charts_report_empty():
    assert line_chart(LABELS, [{"key": "a", "name": "A", "values": [None] * 3}])["empty"] is True
    assert column_chart([{"label": "Lun", "value": None}])["empty"] is True


def test_column_chart_bars_have_rounded_top_and_capped_width():
    chart = column_chart([{"label": "Lun", "value": 4.0}, {"label": "Mar", "value": 2.0}])
    bar = chart["bars"][0]
    assert bar["path"].startswith("M") and "Q" in bar["path"]
    x_values = [float(part.split(",")[0].lstrip("MQ")) for part in bar["path"].split() if "," in part]
    assert max(x_values) - min(x_values) <= 24
    assert bar["value_label"] == "4.0%"
    assert chart["bars"][1]["y_top"] > bar["y_top"]


# --- Calculo de tendencias ---------------------------------------------------------

def _month(year, month, posibles, ausencias, justificadas, lunes=(0, 0)):
    semana = [{"posibles": 0, "ausencias": 0} for _ in range(7)]
    semana[0] = {"posibles": lunes[0], "ausencias": lunes[1]}
    semana[1] = {"posibles": posibles - lunes[0], "ausencias": ausencias - lunes[1]}
    return {
        "year": year, "month": month, "dias_laborables": 20, "dias_posibles": posibles,
        "ausencias_computables": ausencias, "ausencias_justificadas": justificadas, "presentes": 0,
        "por_dia_semana": semana,
    }


class _FakeDb:
    def close(self):
        pass


def test_dashboard_trends_builds_monthly_rows_and_weekday_rates(monkeypatch):
    calls = {}

    def fake_by_month(db, start, end, **kwargs):
        calls["rango"] = (start, end, kwargs)
        return [_month(2026, 9, 200, 10, 4, lunes=(40, 6)), _month(2026, 10, 0, 0, 0)], 50

    monkeypatch.setattr(metrics, "get_db", _FakeDb)
    monkeypatch.setattr(metrics, "_unified_attendance_by_month", fake_by_month)
    monkeypatch.setattr(metrics, "_punctuality_by_month", lambda *a, **kw: {(2026, 9): (180, 153)})

    trends = metrics._dashboard_trends(months=2, empresa_id=3, today=datetime.date(2026, 10, 14))

    assert calls["rango"] == (datetime.date(2026, 9, 1), datetime.date(2026, 10, 14), {"empresa_id": 3, "sucursal_id": None})
    septiembre, octubre = trends["meses"]
    assert septiembre["nombre"] == "Septiembre 2026" and septiembre["sub"] == "2026"
    assert septiembre["ausentismo_pct"] == 5.0
    assert septiembre["justificadas_pct"] == 2.0
    assert septiembre["puntualidad_pct"] == 85.0
    # Sin dias posibles ni fichadas el valor es "sin dato", no 0%.
    assert octubre["ausentismo_pct"] is None and octubre["puntualidad_pct"] is None
    assert octubre["parcial"] is True and septiembre["parcial"] is False
    dias = {d["nombre"]: d for d in trends["dias_semana"]}
    assert set(dias) == {"Lunes", "Martes"}  # dias sin jornadas posibles no se grafican
    assert dias["Lunes"]["value"] == 15.0


def test_dashboard_trends_twelve_months_crosses_year(monkeypatch):
    seen = {}
    monkeypatch.setattr(metrics, "get_db", _FakeDb)
    monkeypatch.setattr(metrics, "_unified_attendance_by_month", lambda db, start, end, **kw: seen.setdefault("start", start) and ([], 0))
    monkeypatch.setattr(metrics, "_punctuality_by_month", lambda *a, **kw: {})
    metrics._dashboard_trends(months=12, today=datetime.date(2026, 10, 14))
    assert seen["start"] == datetime.date(2025, 11, 1)


def test_unified_summary_sums_monthly_breakdown(monkeypatch):
    monkeypatch.setattr(
        metrics, "_unified_attendance_by_month",
        lambda *a, **kw: ([_month(2026, 9, 200, 10, 4), _month(2026, 10, 100, 2, 1)], 20),
    )
    totals = metrics._build_unified_attendance_summary(None, datetime.date(2026, 9, 1), datetime.date(2026, 10, 14))
    assert totals["dias_posibles"] == 300
    assert totals["ausencias_computables"] == 12
    assert totals["ausentismo_pct"] == 4.0
    assert totals["frecuencia_ausencias"] == 0.6


def test_unified_by_month_counts_weekdays_from_planilla(monkeypatch):
    class Cursor:
        def close(self):
            pass

    class Db:
        def cursor(self, **kw):
            return Cursor()

    monkeypatch.setattr(metrics, "_safe_fetchall", lambda cursor, query, params=None: [])
    monkeypatch.setattr(metrics, "get_dias_no_laborables", lambda **kw: set())
    cells = [
        {"iso": "2026-09-07", "status": "unjustified"},  # lunes
        {"iso": "2026-09-14", "status": "present"},      # lunes
        {"iso": "2026-09-08", "status": "justified"},    # martes
        {"iso": "2026-09-13", "status": "non_laborable"},  # domingo: no cuenta
    ]
    monkeypatch.setattr(metrics, "build_monthly_attendance_report", lambda **kw: {
        "kpis": {"dias_laborables": 20, "dias_posibles": 3, "ausencias_computables": 1,
                 "ausencias_justificadas": 1, "presentes": 1},
        "planilla_rows": [{"cells": cells}],
    })
    months, _ = metrics._unified_attendance_by_month(Db(), datetime.date(2026, 9, 1), datetime.date(2026, 9, 30))
    semana = months[0]["por_dia_semana"]
    assert semana[0] == {"posibles": 2, "ausencias": 1}
    assert semana[1] == {"posibles": 1, "ausencias": 0}
    assert semana[6] == {"posibles": 0, "ausencias": 0}


# --- Ruta y dashboard --------------------------------------------------------------

def _client(monkeypatch):
    monkeypatch.setattr(app_module, "init_db", lambda: None)
    app = app_module.create_app()
    app.config["TESTING"] = True
    client = app.test_client()
    with client.session_transaction() as sess:
        sess["user_id"] = 77
    return client


def _fake_trends(**kwargs):
    meses = []
    for month, aus in ((9, 5.0), (10, 4.2)):
        meses.append({
            "key": f"2026-{month:02d}", "nombre": f"Mes {month} 2026", "label": f"M{month}", "sub": "",
            "parcial": month == 10, "dias_posibles": 1020, "ausencias": 34, "justificadas": 12,
            "ausentismo_pct": aus, "justificadas_pct": 1.2, "fichadas": 900, "en_horario": 810,
            "puntualidad_pct": 90.0,
        })
    return {"meses": meses, "dias_semana": [
        {"nombre": "Lunes", "label": "Lun", "posibles": 200, "ausencias": 12, "value": 6.0},
        {"nombre": "Martes", "label": "Mar", "posibles": 200, "ausencias": 4, "value": 2.0},
    ]}


def test_evolucion_fragment_renders_charts_tables_and_period(monkeypatch):
    client = _client(monkeypatch)
    pedidos = []
    monkeypatch.setattr(web_routes, "_dashboard_trends", lambda **kw: pedidos.append(kw) or _fake_trends())

    response = client.get("/dashboard/evolucion?meses=6&empresa_id=3")

    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert pedidos == [{"months": 6, "empresa_id": 3, "sucursal_id": None}]
    assert html.count("<svg") == 3
    assert "Faltas injustificadas por día de la semana" in html
    assert 'aria-label="Mes 10 2026 (parcial): faltas injustificadas 4.2%, ausencias justificadas 1.2%"' in html
    assert "1.020" in html  # miles con punto en tablas y tooltips
    assert 'aria-pressed="true"' in html and ">6 meses<" in html
    assert "empresa_id=3" in html  # el selector de periodo conserva el filtro
    assert "<html" not in html  # fragmento, no pagina completa


def test_evolucion_rejects_unknown_period_and_survives_errors(monkeypatch):
    client = _client(monkeypatch)
    pedidos = []

    def boom(**kw):
        pedidos.append(kw["months"])
        raise RuntimeError("db caida")

    monkeypatch.setattr(web_routes, "_dashboard_trends", boom)
    response = client.get("/dashboard/evolucion?meses=999")

    assert response.status_code == 200
    assert pedidos == [12]
    assert "No se pudieron calcular las tendencias" in response.get_data(as_text=True)


def test_evolucion_requires_login(monkeypatch):
    monkeypatch.setattr(app_module, "init_db", lambda: None)
    response = app_module.create_app().test_client().get("/dashboard/evolucion")
    assert response.status_code in (302, 401, 403)
