from datetime import datetime

import pytest

import app as app_module
import repositories.request_metrics_repository as repo
import services.performance_report_service as report_service
import web.auth.decorators as auth_decorators
from utils import request_metrics as rm

HORA = datetime(2026, 10, 15, 9, 30, tzinfo=rm.ARGENTINA)


@pytest.fixture(autouse=True)
def _clean_pending():
    rm._drain()
    yield
    rm._drain()


# --- Recolector -----------------------------------------------------------------

def test_record_aggregates_by_hour_route_and_method_with_histogram():
    rm.record("/empleados/", "GET", 200, 80, db_ms=20, db_queries=4, now=HORA)
    rm.record("/empleados/", "GET", 500, 1500, db_ms=60, db_queries=6, now=HORA)
    rm.record("/empleados/", "POST", 200, 300, now=HORA)

    data = rm._drain()
    fila = data[(datetime(2026, 10, 15, 9), "/empleados/", "GET")]
    assert fila["pedidos"] == 2 and fila["errores"] == 1
    assert fila["ms_total"] == 1580 and fila["ms_max"] == 1500
    assert fila["db_consultas"] == 10
    assert fila["buckets"] == [1, 0, 0, 0, 1, 0, 0]  # <=100 ms y <=2000 ms
    assert len(data) == 2


def test_flush_retries_when_database_fails(monkeypatch):
    rm.record("/x", "GET", 200, 50, now=HORA)
    monkeypatch.setattr(repo, "upsert_hourly", lambda data: (_ for _ in ()).throw(RuntimeError("db caida")))
    assert rm.flush() == 0
    # Los datos vuelven al acumulador y se suman a los nuevos.
    rm.record("/x", "GET", 200, 70, now=HORA)
    saved = []
    monkeypatch.setattr(repo, "upsert_hourly", lambda data: saved.append(data))
    assert rm.flush() == 1
    assert saved[0][(datetime(2026, 10, 15, 9), "/x", "GET")]["pedidos"] == 2


def test_pending_keys_are_capped(monkeypatch):
    monkeypatch.setattr(rm, "MAX_PENDING_KEYS", 2)
    for ruta in ("/a", "/b", "/c"):
        rm.record(ruta, "GET", 200, 10, now=HORA)
    assert len(rm._drain()) == 2


def test_ignored_paths():
    assert not rm.should_record("/healthz")
    assert not rm.should_record("/static/css/panel.css")
    assert rm.should_record("/empleados/")


def test_upsert_sums_existing_hour(monkeypatch):
    executed = {}

    class Cursor:
        def executemany(self, sql, params):
            executed["sql"], executed["params"] = sql, params

        def close(self):
            pass

    class Db:
        def cursor(self):
            return Cursor()

        def commit(self):
            executed["commit"] = True

        def close(self):
            pass

    monkeypatch.setattr(repo, "get_db", Db)
    rm.record("/x", "GET", 200, 120, db_ms=5, db_queries=1, now=HORA)
    repo.upsert_hourly(rm._drain())
    assert "ON DUPLICATE KEY UPDATE" in executed["sql"]
    assert "pedidos = pedidos + VALUES(pedidos)" in executed["sql"]
    assert "ms_max = GREATEST(ms_max, VALUES(ms_max))" in executed["sql"]
    assert executed["params"][0][:4] == (datetime(2026, 10, 15, 9), "/x", "GET", 1)
    assert executed["commit"]


# --- Reporte ----------------------------------------------------------------------

def test_percentile_label_from_buckets():
    assert report_service.percentile_label([90, 5, 3, 1, 1, 0, 0], 0.5) == "≤ 100 ms"
    assert report_service.percentile_label([0, 0, 0, 0, 0, 0, 10], 0.95) == "> 5 s"
    assert report_service.percentile_label([0] * 7, 0.5) == "s/d"


def _fila(**valores):
    base = {"pedidos": 0, "errores": 0, "ms_total": 0, "ms_max": 0, "db_ms_total": 0, "db_consultas": 0}
    base.update({c: 0 for c in rm.BUCKET_COLUMNS})
    base.update(valores)
    return base


def test_build_report_fills_missing_hours_and_ranks_routes():
    pedidos_hora = _fila(pedidos=10, ms_total=6000, db_ms_total=200, db_consultas=100, b500=8, b2000=2)
    pedido = {}

    def fake_fetch(desde, por_dia):
        pedido.update(desde=desde, por_dia=por_dia)
        return {
            "totales": pedidos_hora,
            "serie": [{"periodo": datetime(2026, 10, 15, 9), **pedidos_hora}],
            "rutas": [
                {"ruta": "/dashboard", "metodo": "GET", **_fila(pedidos=2, ms_total=4500, b5000=2)},
                {"ruta": "/empleados/", "metodo": "GET", **_fila(pedidos=8, ms_total=1500, b250=8)},
            ],
        }

    r = report_service.build_report("24h", ahora=datetime(2026, 10, 15, 9, 40), fetch=fake_fetch)

    assert pedido == {"desde": datetime(2026, 10, 14, 10), "por_dia": False}
    assert len(r["tabla_periodos"]) == 24  # horas sin trafico tambien aparecen
    assert r["tabla_periodos"][-1][:3] == ["15/10 09:00", "10", "0.60 s"]
    assert r["totales"]["lentos_pct"] == 20.0
    assert r["totales"]["ms_por_consulta"] == 2.0
    assert [x["ruta"] for x in r["rutas"]] == ["/dashboard", "/empleados/"]
    assert r["rutas"][0]["impacto_pct"] == 75.0
    assert not r["graficos"]["tiempo"]["empty"]


def test_build_report_daily_periods():
    r = report_service.build_report(
        "7d", ahora=datetime(2026, 10, 15, 9),
        fetch=lambda desde, por_dia: {"totales": {}, "serie": [], "rutas": []},
    )
    assert len(r["tabla_periodos"]) == 7 and not r["hay_datos"]


# --- Ruta y registro automatico -------------------------------------------------

def _client(monkeypatch, rol):
    monkeypatch.setattr(app_module, "init_db", lambda: None)
    monkeypatch.setattr(auth_decorators, "_cached_web_user", lambda uid: {"id": 1, "activo": 1, "rol": rol})
    client = app_module.create_app().test_client()
    with client.session_transaction() as sess:
        sess["user_id"] = 1
    return client


def test_rendimiento_only_for_strict_admin(monkeypatch):
    monkeypatch.setattr(report_service, "get_report_data", lambda *a, **kw: {"totales": {}, "serie": [], "rutas": []})
    assert _client(monkeypatch, "rrhh").get("/rendimiento/").status_code == 403
    response = _client(monkeypatch, "admin").get("/rendimiento/?periodo=7d")
    assert response.status_code == 200
    assert "Todavía no hay métricas" in response.get_data(as_text=True)


def test_rendimiento_renders_charts_with_data(monkeypatch):
    fila = _fila(pedidos=10, ms_total=6000, db_ms_total=200, db_consultas=100, b500=10)
    hora = datetime.now(rm.ARGENTINA).replace(minute=0, second=0, microsecond=0, tzinfo=None)
    monkeypatch.setattr(report_service, "get_report_data", lambda desde, por_dia: {
        "totales": fila, "serie": [{"periodo": hora, **fila}],
        "rutas": [{"ruta": "/empleados/", "metodo": "GET", **fila}],
    })
    html = _client(monkeypatch, "admin").get("/rendimiento/").get_data(as_text=True)
    assert html.count('class="viz-svg"') == 4
    assert "GET /empleados/" in html and "Latencia por consulta" in html


def test_app_records_request_metrics_by_route_rule(monkeypatch):
    monkeypatch.setattr(report_service, "get_report_data", lambda *a, **kw: {"totales": {}, "serie": [], "rutas": []})
    client = _client(monkeypatch, "admin")
    rm._drain()
    client.get("/rendimiento/")
    client.get("/healthz")
    rutas = {ruta for (_, ruta, _) in rm._drain()}
    assert rutas == {"/rendimiento/"}
