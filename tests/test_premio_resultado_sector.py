from unittest.mock import Mock

import pytest

import repositories.premio_concurso_repository as repository


@pytest.mark.parametrize("allow", [False, True])
@pytest.mark.parametrize("editing", [False, True])
def test_cross_sector_result_requires_explicit_exception(monkeypatch, allow, editing):
    db = Mock()
    monkeypatch.setattr(repository, "get_db", lambda: db)
    employee = {"id": 10, "empresa_id": 1, "sector_id": 3, "nombre": "Ana"}
    contest = {"id": 9, "empresa_id": 1, "sector_id": 4, "alcance": "sector"}
    monkeypatch.setattr(repository, "_fetch_empleado", lambda *args: employee)
    monkeypatch.setattr(repository, "_fetch_concurso", lambda *args: contest)
    save = Mock(return_value=(7, not editing))
    monkeypatch.setattr(repository, "_save_prepared_resultado", save)
    data = dict(empresa_id=1, empleado_id=10, concurso_id=9, periodo="2026-09", ranking=1,
                permitir_otro_sector=allow)
    if allow:
        repository.save_resultado(data, resultado_id=7 if editing else None)
        assert save.call_args.args[1]["sector_id"] == 3
        assert contest["sector_id"] == 4
        db.commit.assert_called_once()
    else:
        with pytest.raises(ValueError, match="sector"):
            repository.save_resultado(data, resultado_id=7 if editing else None)
        save.assert_not_called()
        db.commit.assert_not_called()
    db.close.assert_called_once()


@pytest.mark.parametrize("employee,contest", [(None, {"id": 9}), ({"id": 10}, None)])
def test_sector_exception_does_not_bypass_company_lookup(employee, contest):
    with pytest.raises(ValueError, match="empresa seleccionada"):
        repository._validate_resultado_data(employee, contest, permitir_otro_sector=True)


def test_same_sector_and_global_contests_need_no_exception():
    employee = {"sector_id": 3}
    repository._validate_resultado_data(employee, {"alcance": "sector", "sector_id": 3})
    repository._validate_resultado_data(employee, {"alcance": "global"})


@pytest.mark.parametrize("length", [256, 5000, 5001])
def test_observaciones_length_limit(length):
    data = dict(
        empresa_id=1, empleado={"id": 10, "sector_id": 3},
        concurso={"id": 9, "alcance": "global"}, periodo="2026-09", ranking=1,
        observaciones="á" * length,
    )
    if length > 5000:
        with pytest.raises(ValueError, match="5000"):
            repository.build_prepared_resultado(**data)
    else:
        assert repository.build_prepared_resultado(**data)["observaciones"] == data["observaciones"]
