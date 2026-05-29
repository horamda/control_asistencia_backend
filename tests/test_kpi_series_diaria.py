"""Tests para get_series_diaria_empleado del repositorio KPI sectorial."""
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
        self._sector_row = sector_row
        self._kpi_rows = kpi_rows
        self._resultado_rows = resultado_rows

    def cursor(self, dictionary=False):
        return _Cursor(self._sector_row, self._kpi_rows, self._resultado_rows)

    def close(self):
        pass


def _patch(monkeypatch, sector_row, kpi_rows, resultado_rows):
    monkeypatch.setattr(repo, "get_db", lambda: _Db(sector_row, kpi_rows, resultado_rows))


# ---------------------------------------------------------------------------
# Tests — sin sector / sin KPIs
# ---------------------------------------------------------------------------

def test_sin_sector_devuelve_lista_vacia(monkeypatch):
    _patch(monkeypatch, {"sector_id": None, "sector_nombre": None}, [], [])
    result = repo.get_series_diaria_empleado(1, 2026, dias=30, today=datetime.date(2026, 5, 28))
    assert result == []


def test_sin_kpis_devuelve_lista_vacia(monkeypatch):
    _patch(monkeypatch, {"sector_id": 3, "sector_nombre": "Entrega"}, [], [])
    result = repo.get_series_diaria_empleado(1, 2026, dias=30, today=datetime.date(2026, 5, 28))
    assert result == []


# ---------------------------------------------------------------------------
# Tests — KPI suma
# ---------------------------------------------------------------------------

def test_kpi_suma_acumula_correctamente(monkeypatch):
    kpis = [{
        "kpi_id": 1, "codigo": "BULTOS", "nombre": "Bultos", "unidad": "u",
        "tipo_acumulacion": "suma", "mayor_es_mejor": 1,
        "objetivo_anual": 365.0, "condicion": "gte",
        "valor_min": None, "valor_max": None,
    }]
    resultados = [
        {"kpi_id": 1, "fecha": datetime.date(2026, 5, 26), "valor": 10.0},
        {"kpi_id": 1, "fecha": datetime.date(2026, 5, 27), "valor": 20.0},
        {"kpi_id": 1, "fecha": datetime.date(2026, 5, 28), "valor": 5.0},
    ]
    _patch(monkeypatch, {"sector_id": 3, "sector_nombre": "Entrega"}, kpis, resultados)

    result = repo.get_series_diaria_empleado(1, 2026, dias=30, today=datetime.date(2026, 5, 28))

    assert len(result) == 1
    puntos = result[0]["puntos"]
    assert len(puntos) == 3

    assert puntos[0]["fecha"] == "2026-05-26"
    assert puntos[0]["resultado_dia"] == 10.0
    assert puntos[0]["resultado_acumulado_a_fecha"] == 10.0

    assert puntos[1]["fecha"] == "2026-05-27"
    assert puntos[1]["resultado_dia"] == 20.0
    assert puntos[1]["resultado_acumulado_a_fecha"] == 30.0

    assert puntos[2]["fecha"] == "2026-05-28"
    assert puntos[2]["resultado_dia"] == 5.0
    assert puntos[2]["resultado_acumulado_a_fecha"] == 35.0


def test_kpi_suma_objetivo_dia_proporcional(monkeypatch):
    kpis = [{
        "kpi_id": 1, "codigo": "BULTOS", "nombre": "Bultos", "unidad": "u",
        "tipo_acumulacion": "suma", "mayor_es_mejor": 1,
        "objetivo_anual": 365.0, "condicion": "gte",
        "valor_min": None, "valor_max": None,
    }]
    resultados = [{"kpi_id": 1, "fecha": datetime.date(2026, 1, 1), "valor": 1.0}]
    _patch(monkeypatch, {"sector_id": 3, "sector_nombre": "E"}, kpis, resultados)

    result = repo.get_series_diaria_empleado(1, 2026, dias=30, today=datetime.date(2026, 1, 1))
    punto = result[0]["puntos"][0]

    # 2026 no es bisiesto → 365 días; objetivo_anual=365 → objetivo_dia=1.0
    assert punto["objetivo_dia"] == 1.0
    assert punto["progreso_dia_pct"] == 100.0


def test_kpi_suma_objetivo_acumulado_proporcional(monkeypatch):
    kpis = [{
        "kpi_id": 1, "codigo": "BULTOS", "nombre": "B", "unidad": "u",
        "tipo_acumulacion": "suma", "mayor_es_mejor": 1,
        "objetivo_anual": 365.0, "condicion": "gte",
        "valor_min": None, "valor_max": None,
    }]
    # Día 365 del año (31 dic en año no bisiesto)
    resultados = [{"kpi_id": 1, "fecha": datetime.date(2026, 12, 31), "valor": 365.0}]
    _patch(monkeypatch, {"sector_id": 3, "sector_nombre": "E"}, kpis, resultados)

    result = repo.get_series_diaria_empleado(1, 2026, dias=365, today=datetime.date(2026, 12, 31))
    punto = result[0]["puntos"][0]

    assert punto["objetivo_acumulado_a_fecha"] == 365.0
    assert punto["resultado_acumulado_a_fecha"] == 365.0
    assert punto["progreso_acumulado_pct"] == 100.0


# ---------------------------------------------------------------------------
# Tests — KPI promedio
# ---------------------------------------------------------------------------

def test_kpi_promedio_acumula_promedio(monkeypatch):
    kpis = [{
        "kpi_id": 2, "codigo": "SATISF", "nombre": "Satisfaccion", "unidad": "%",
        "tipo_acumulacion": "promedio", "mayor_es_mejor": 1,
        "objetivo_anual": 90.0, "condicion": "gte",
        "valor_min": None, "valor_max": None,
    }]
    resultados = [
        {"kpi_id": 2, "fecha": datetime.date(2026, 5, 10), "valor": 80.0},
        {"kpi_id": 2, "fecha": datetime.date(2026, 5, 20), "valor": 100.0},
    ]
    _patch(monkeypatch, {"sector_id": 3, "sector_nombre": "E"}, kpis, resultados)

    result = repo.get_series_diaria_empleado(2, 2026, dias=30, today=datetime.date(2026, 5, 28))
    puntos = result[0]["puntos"]

    assert puntos[0]["resultado_acumulado_a_fecha"] == 80.0
    assert puntos[1]["resultado_acumulado_a_fecha"] == 90.0  # (80+100)/2

    # Para promedio, objetivo_dia == objetivo_anual
    assert puntos[0]["objetivo_dia"] == 90.0
    assert puntos[1]["objetivo_dia"] == 90.0

    # objetivo_acumulado también es fijo = objetivo_anual
    assert puntos[0]["objetivo_acumulado_a_fecha"] == 90.0


# ---------------------------------------------------------------------------
# Tests — KPI between
# ---------------------------------------------------------------------------

def test_kpi_between_objetivo_dia_es_none(monkeypatch):
    kpis = [{
        "kpi_id": 3, "codigo": "TEMP", "nombre": "Temperatura", "unidad": "C",
        "tipo_acumulacion": "promedio", "mayor_es_mejor": 0,
        "objetivo_anual": 0.0, "condicion": "between",
        "valor_min": 18.0, "valor_max": 24.0,
    }]
    resultados = [{"kpi_id": 3, "fecha": datetime.date(2026, 5, 28), "valor": 21.0}]
    _patch(monkeypatch, {"sector_id": 3, "sector_nombre": "E"}, kpis, resultados)

    result = repo.get_series_diaria_empleado(3, 2026, dias=10, today=datetime.date(2026, 5, 28))
    punto = result[0]["puntos"][0]

    assert punto["objetivo_dia"] is None
    assert punto["objetivo_acumulado_a_fecha"] is None
    assert punto["semaforo_dia"] == "verde"
    assert punto["semaforo_acumulado"] == "verde"
    assert result[0]["valor_min"] == 18.0
    assert result[0]["valor_max"] == 24.0


def test_kpi_between_fuera_de_rango_semaforo_rojo(monkeypatch):
    kpis = [{
        "kpi_id": 3, "codigo": "TEMP", "nombre": "Temperatura", "unidad": "C",
        "tipo_acumulacion": "promedio", "mayor_es_mejor": 0,
        "objetivo_anual": 0.0, "condicion": "between",
        "valor_min": 18.0, "valor_max": 24.0,
    }]
    resultados = [{"kpi_id": 3, "fecha": datetime.date(2026, 5, 28), "valor": 35.0}]
    _patch(monkeypatch, {"sector_id": 3, "sector_nombre": "E"}, kpis, resultados)

    result = repo.get_series_diaria_empleado(3, 2026, dias=10, today=datetime.date(2026, 5, 28))
    punto = result[0]["puntos"][0]

    assert punto["semaforo_dia"] == "rojo"


# ---------------------------------------------------------------------------
# Tests — Ventana series_dias
# ---------------------------------------------------------------------------

def test_series_dias_filtra_puntos_del_display(monkeypatch):
    """Datos fuera de la ventana no aparecen en puntos pero sí contribuyen al acumulado."""
    kpis = [{
        "kpi_id": 1, "codigo": "BULTOS", "nombre": "B", "unidad": "u",
        "tipo_acumulacion": "suma", "mayor_es_mejor": 1,
        "objetivo_anual": 365.0, "condicion": "gte",
        "valor_min": None, "valor_max": None,
    }]
    # Valor antiguo (fuera de ventana de 5 días) + valor reciente
    resultados = [
        {"kpi_id": 1, "fecha": datetime.date(2026, 5, 1), "valor": 100.0},
        {"kpi_id": 1, "fecha": datetime.date(2026, 5, 28), "valor": 5.0},
    ]
    _patch(monkeypatch, {"sector_id": 3, "sector_nombre": "E"}, kpis, resultados)

    result = repo.get_series_diaria_empleado(1, 2026, dias=5, today=datetime.date(2026, 5, 28))
    puntos = result[0]["puntos"]

    # Solo el punto del 28 está dentro de la ventana
    assert len(puntos) == 1
    assert puntos[0]["fecha"] == "2026-05-28"

    # El acumulado incluye el valor del 1 de mayo
    assert puntos[0]["resultado_acumulado_a_fecha"] == 105.0


def test_kpi_sin_resultados_devuelve_puntos_vacios(monkeypatch):
    kpis = [{
        "kpi_id": 1, "codigo": "BULTOS", "nombre": "B", "unidad": "u",
        "tipo_acumulacion": "suma", "mayor_es_mejor": 1,
        "objetivo_anual": 365.0, "condicion": "gte",
        "valor_min": None, "valor_max": None,
    }]
    _patch(monkeypatch, {"sector_id": 3, "sector_nombre": "E"}, kpis, [])

    result = repo.get_series_diaria_empleado(1, 2026, dias=30, today=datetime.date(2026, 5, 28))

    assert len(result) == 1
    assert result[0]["puntos"] == []
    assert result[0]["periodo_desde"] is not None
    assert result[0]["periodo_hasta"] is not None


def test_periodo_desde_hasta_correctos(monkeypatch):
    kpis = [{
        "kpi_id": 1, "codigo": "K", "nombre": "K", "unidad": "u",
        "tipo_acumulacion": "suma", "mayor_es_mejor": 1,
        "objetivo_anual": 100.0, "condicion": "gte",
        "valor_min": None, "valor_max": None,
    }]
    _patch(monkeypatch, {"sector_id": 3, "sector_nombre": "E"}, kpis, [])

    result = repo.get_series_diaria_empleado(1, 2026, dias=10, today=datetime.date(2026, 5, 28))

    assert result[0]["periodo_desde"] == "2026-05-19"  # 28 - 9 días
    assert result[0]["periodo_hasta"] == "2026-05-28"
