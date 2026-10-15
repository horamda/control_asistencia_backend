"""Reglas de disponibilidad EPP por sector + puesto (sin base de datos)."""
import pytest

from scripts.migrate_20261015_02_epp_habilitaciones import legacy_rules
from services import epp_service as s


def emp(sector, puesto, adicionales=()):
    return {"sector_id": sector, "puesto_id": puesto, "puestos_adicionales": list(adicionales)}


def art(reglas, activo=1):
    return {"activo": activo, "habilitaciones": [{"s": a, "p": b} for a, b in reglas]}


def test_pair_only_matches_that_puesto_inside_that_sector():
    casco = art([(2, 7)])  # pickers de Almacen
    assert s.available(casco, emp(2, 7))
    assert not s.available(casco, emp(1, 7))  # mismo puesto en otro sector
    assert not s.available(casco, emp(2, 8))


def test_whole_sector_any_sector_and_everyone():
    assert s.available(art([(3, None)]), emp(3, 99))
    assert s.available(art([(None, 7)]), emp(5, 7))
    assert s.available(art([]), emp(1, 1))
    assert not s.available(art([], activo=0), emp(1, 1))


def test_additional_positions_count():
    assert s.available(art([(2, 7)]), emp(1, 1, adicionales=[(2, 7)]))


def test_legacy_articles_keep_previous_behaviour():
    # Sin migrar: el empleado debe estar en ambas listas (producto).
    legacy = {"activo": 1, "sectores": [1, 3], "puestos": [7]}
    assert s.rules(legacy) == [(1, 7), (3, 7)]
    assert s.available(legacy, emp(3, 7)) and not s.available(legacy, emp(3, 8))
    assert legacy_rules([1], []) == [{"s": 1, "p": None}]
    assert legacy_rules([], [7]) == [{"s": None, "p": 7}]
    assert legacy_rules([1, 2], [7]) == [{"s": 1, "p": 7}, {"s": 2, "p": 7}]


@pytest.mark.parametrize("value,expected", [("4", (4, None)), ("4:9", (4, 9)), (":9", (None, 9)), ({"s": 4, "p": None}, (4, None))])
def test_parse_rule(value, expected):
    assert s._parse_rule(value) == expected


@pytest.mark.parametrize("value", [":", "", "x:1", "0:2"])
def test_parse_rule_rejects_invalid(value):
    with pytest.raises(Exception):
        s._parse_rule(value)


def test_article_rules_validates_company_and_drops_redundant_pairs(monkeypatch):
    validos = {("sectores", 1), ("sectores", 2), ("puestos", 7), ("puestos", 8)}
    monkeypatch.setattr(s.db, "one", lambda c, sql, args: (sql.split("FROM ")[1].split()[0], args[0]) in validos or None)
    reglas = s.article_rules(None, {"empresa_id": 1}, {"habilitaciones": ["1", "1:7", "2:8", "2:8"]})
    assert reglas == [{"s": 1, "p": None}, {"s": 2, "p": 8}]
    with pytest.raises(s.Error):
        s.article_rules(None, {"empresa_id": 1}, {"habilitaciones": ["3:7"]})
    # Formato anterior (dos listas) sigue aceptado: se combinan.
    assert s.article_rules(None, {"empresa_id": 1}, {"sectores": [1], "puestos": [7]}) == [{"s": 1, "p": 7}]


def test_eligibility_groups_real_puestos_by_sector_and_keeps_orphan_rules(monkeypatch):
    from contextlib import contextmanager

    import web.epp.routes as routes

    @contextmanager
    def tx(read_only=False):
        yield None

    def all_rows(c, sql, args=()):
        if "FROM sectores" in sql:
            return [{"id": 1, "nombre": "Almacen"}, {"id": 2, "nombre": "Operaciones"}, {"id": 3, "nombre": "Vacio"}]
        if "FROM puestos" in sql:
            return [{"id": 7, "nombre": "Picker"}, {"id": 8, "nombre": "Chofer"}]
        return [  # empleado 1 con puesto adicional en Operaciones
            {"empleado_id": 1, "sector_id": 1, "puesto_id": 7},
            {"empleado_id": 2, "sector_id": 1, "puesto_id": 7},
            {"empleado_id": 3, "sector_id": 2, "puesto_id": 8},
            {"empleado_id": 1, "sector_id": 2, "puesto_id": 8},
        ]

    monkeypatch.setattr(routes.s.db, "transaction", tx)
    monkeypatch.setattr(routes.s.db, "all_rows", all_rows)
    data = routes.eligibility({"empresa_id": 1}, {"habilitaciones": [{"s": 2, "p": 7}]})

    sectores = {g["nombre"]: g for g in data["sectores"]}
    assert set(sectores) == {"Almacen", "Operaciones"}  # sin empleados ni reglas: no se muestra
    assert sectores["Almacen"]["empleados"] == 2
    assert sectores["Almacen"]["puestos"] == [{"id": 7, "nombre": "Picker", "empleados": 2, "marcado": False}]
    # Regla guardada sin empleados (Picker en Operaciones) se muestra para poder quitarla.
    operaciones = {p["nombre"]: p for p in sectores["Operaciones"]["puestos"]}
    assert operaciones["Picker"] == {"id": 7, "nombre": "Picker", "empleados": 0, "marcado": True}
    assert operaciones["Chofer"]["empleados"] == 2
    assert sorted(map(sorted, data["empleados"])) == [["1:7"], ["1:7", "2:8"], ["2:8"]]
