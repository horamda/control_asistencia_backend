"""Tests para get_kpis_dia_empleado del repositorio KPI sectorial."""
import datetime

import repositories.kpi_sectorial_repository as repo


# ---------------------------------------------------------------------------
# Helpers de mocking
# ---------------------------------------------------------------------------

class _Cursor:
    def __init__(self, sector_row, kpi_rows, resultado_rows):
        self._sector_row = sector_row
        self._kpi_rows = kpi_rows
        self._resultado_rows = resultado_rows
        self._last_query = ""

    def execute(self, query, params=()):
        self._last_query = query

    def fetchone(self):
        if "sector_id" in self._last_query and "empleados e" in self._last_query:
            return self._sector_row
        return None

    def fetchall(self):
        if "kpis_definicion" in self._last_query:
            return self._kpi_rows
        if "kpis_empleado_resultado" in self._last_query:
            return self._resultado_rows
        return []

    def close(self):
        pass


class _Db:
    def __init__(self, sector_row, kpi_rows, resultado_rows):
        self._args = (sector_row, kpi_rows, resultado_rows)

    def cursor(self, dictionary=False):
        return _Cursor(*self._args)

    def close(self):
        pass


def _patch(monkeypatch, sector_row, kpi_rows, resultado_rows):
    monkeypatch.setattr(repo, "get_db", lambda: _Db(sector_row, kpi_rows, resultado_rows))


def _kpi_suma(kpi_id=1, objetivo=365.0):
    return {
        "kpi_id": kpi_id, "codigo": "BULTOS", "nombre": "Bultos", "unidad": "u",
        "tipo_acumulacion": "suma", "mayor_es_mejor": 1,
        "objetivo_anual": objetivo, "condicion": "gte",
        "valor_min": None, "valor_max": None,
    }


def _kpi_promedio(kpi_id=2, objetivo=90.0):
    return {
        "kpi_id": kpi_id, "codigo": "SATISF", "nombre": "Satisfaccion", "unidad": "%",
        "tipo_acumulacion": "promedio", "mayor_es_mejor": 1,
        "objetivo_anual": objetivo, "condicion": "gte",
        "valor_min": None, "valor_max": None,
    }


def _kpi_between(kpi_id=3):
    return {
        "kpi_id": kpi_id, "codigo": "TEMP", "nombre": "Temp", "unidad": "C",
        "tipo_acumulacion": "promedio", "mayor_es_mejor": 0,
        "objetivo_anual": 0.0, "condicion": "between",
        "valor_min": 18.0, "valor_max": 24.0,
    }


# ---------------------------------------------------------------------------
# Sin sector / sin KPIs
# ---------------------------------------------------------------------------

def test_sin_sector_devuelve_kpis_vacios(monkeypatch):
    _patch(monkeypatch, {"sector_id": None, "sector_nombre": None}, [], [])
    data = repo.get_kpis_dia_empleado(1, datetime.date(2026, 5, 27))
    assert data["sector_id"] is None
    assert data["kpis"] == []


def test_sin_kpis_devuelve_lista_vacia(monkeypatch):
    _patch(monkeypatch, {"sector_id": 3, "sector_nombre": "E"}, [], [])
    data = repo.get_kpis_dia_empleado(1, datetime.date(2026, 5, 27))
    assert data["kpis"] == []


# ---------------------------------------------------------------------------
# Con resultado en el día
# ---------------------------------------------------------------------------

def test_resultado_dia_suma_correcto(monkeypatch):
    resultados = [
        {"kpi_id": 1, "fecha": datetime.date(2026, 5, 26), "valor": 10.0},
        {"kpi_id": 1, "fecha": datetime.date(2026, 5, 27), "valor": 20.0},
    ]
    _patch(monkeypatch, {"sector_id": 3, "sector_nombre": "E"}, [_kpi_suma()], resultados)

    data = repo.get_kpis_dia_empleado(1, datetime.date(2026, 5, 27))
    kpi = data["kpis"][0]

    assert kpi["tiene_resultado"] is True
    assert kpi["resultado_dia"] == 20.0
    assert kpi["resultado_acumulado_a_fecha"] == 30.0  # 10 + 20


def test_resultado_dia_promedio_correcto(monkeypatch):
    resultados = [
        {"kpi_id": 2, "fecha": datetime.date(2026, 5, 10), "valor": 80.0},
        {"kpi_id": 2, "fecha": datetime.date(2026, 5, 27), "valor": 100.0},
    ]
    _patch(monkeypatch, {"sector_id": 3, "sector_nombre": "E"}, [_kpi_promedio()], resultados)

    data = repo.get_kpis_dia_empleado(1, datetime.date(2026, 5, 27))
    kpi = data["kpis"][0]

    assert kpi["tiene_resultado"] is True
    assert kpi["resultado_dia"] == 100.0
    assert kpi["resultado_acumulado_a_fecha"] == 90.0  # (80+100)/2


# ---------------------------------------------------------------------------
# Sin resultado en el día exacto (pero con historial previo)
# ---------------------------------------------------------------------------

def test_sin_resultado_dia_tiene_resultado_false(monkeypatch):
    resultados = [
        {"kpi_id": 1, "fecha": datetime.date(2026, 5, 20), "valor": 15.0},
    ]
    _patch(monkeypatch, {"sector_id": 3, "sector_nombre": "E"}, [_kpi_suma()], resultados)

    data = repo.get_kpis_dia_empleado(1, datetime.date(2026, 5, 27))
    kpi = data["kpis"][0]

    assert kpi["tiene_resultado"] is False
    assert kpi["resultado_dia"] is None
    assert kpi["semaforo_dia"] == "gris"
    # El acumulado hasta el 27 incluye el resultado del 20
    assert kpi["resultado_acumulado_a_fecha"] == 15.0


def test_sin_ningún_resultado_acumulado_es_none(monkeypatch):
    _patch(monkeypatch, {"sector_id": 3, "sector_nombre": "E"}, [_kpi_promedio()], [])

    data = repo.get_kpis_dia_empleado(1, datetime.date(2026, 5, 27))
    kpi = data["kpis"][0]

    assert kpi["tiene_resultado"] is False
    assert kpi["resultado_acumulado_a_fecha"] is None
    assert kpi["semaforo_dia"] == "gris"
    assert kpi["semaforo_acumulado"] == "gris"


# ---------------------------------------------------------------------------
# KPI between
# ---------------------------------------------------------------------------

def test_between_objetivo_dia_es_none(monkeypatch):
    resultados = [{"kpi_id": 3, "fecha": datetime.date(2026, 5, 27), "valor": 21.0}]
    _patch(monkeypatch, {"sector_id": 3, "sector_nombre": "E"}, [_kpi_between()], resultados)

    data = repo.get_kpis_dia_empleado(1, datetime.date(2026, 5, 27))
    kpi = data["kpis"][0]

    assert kpi["objetivo_dia"] is None
    assert kpi["objetivo_acumulado_a_fecha"] is None
    assert kpi["semaforo_dia"] == "verde"
    assert kpi["valor_min"] == 18.0
    assert kpi["valor_max"] == 24.0


def test_between_fuera_de_rango_semaforo_rojo(monkeypatch):
    resultados = [{"kpi_id": 3, "fecha": datetime.date(2026, 5, 27), "valor": 35.0}]
    _patch(monkeypatch, {"sector_id": 3, "sector_nombre": "E"}, [_kpi_between()], resultados)

    data = repo.get_kpis_dia_empleado(1, datetime.date(2026, 5, 27))
    assert data["kpis"][0]["semaforo_dia"] == "rojo"


# ---------------------------------------------------------------------------
# Objetivo proporcional (suma)
# ---------------------------------------------------------------------------

def test_suma_objetivo_dia_proporcional(monkeypatch):
    resultados = [{"kpi_id": 1, "fecha": datetime.date(2026, 1, 1), "valor": 1.0}]
    _patch(monkeypatch, {"sector_id": 3, "sector_nombre": "E"}, [_kpi_suma(objetivo=365.0)], resultados)

    data = repo.get_kpis_dia_empleado(1, datetime.date(2026, 1, 1))
    kpi = data["kpis"][0]

    # Día 1 de 365 → objetivo_dia = 365/365 = 1.0
    assert kpi["objetivo_dia"] == 1.0
    assert kpi["progreso_dia_pct"] == 100.0


# ---------------------------------------------------------------------------
# Estructura del payload
# ---------------------------------------------------------------------------

def test_payload_incluye_sector_y_fecha(monkeypatch):
    _patch(monkeypatch, {"sector_id": 5, "sector_nombre": "Depósito"}, [_kpi_suma()], [])

    data = repo.get_kpis_dia_empleado(1, datetime.date(2026, 5, 27))

    assert data["sector_id"] == 5
    assert data["sector_nombre"] == "Depósito"
    assert isinstance(data["kpis"], list)


def test_multiples_kpis_todos_presentes(monkeypatch):
    kpis = [_kpi_suma(kpi_id=1), _kpi_promedio(kpi_id=2), _kpi_between(kpi_id=3)]
    resultados = [
        {"kpi_id": 1, "fecha": datetime.date(2026, 5, 27), "valor": 5.0},
        {"kpi_id": 3, "fecha": datetime.date(2026, 5, 27), "valor": 20.0},
    ]
    _patch(monkeypatch, {"sector_id": 3, "sector_nombre": "E"}, kpis, resultados)

    data = repo.get_kpis_dia_empleado(1, datetime.date(2026, 5, 27))

    assert len(data["kpis"]) == 3
    ids = [k["kpi_id"] for k in data["kpis"]]
    assert 1 in ids and 2 in ids and 3 in ids

    kpi2 = next(k for k in data["kpis"] if k["kpi_id"] == 2)
    assert kpi2["tiene_resultado"] is False  # kpi_id=2 no tiene resultado ese día
