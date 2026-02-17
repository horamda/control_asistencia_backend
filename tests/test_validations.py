import pytest

from services.excepcion_service import _normalize_bloques as normalize_excepcion_bloques
from services.horario_service import _normalize_dias
from utils.asistencia import infer_estado
from utils.validators import EmpleadoValidator


def _exists_unique_false(field, value, emp_id=None):
    return False


def _exists_codigo_true(codigo):
    return True


def _valid_employee_form():
    return {
        "nombre": "Juan",
        "apellido": "Perez",
        "dni": "123",
        "email": "a@b.com",
        "empresa_id": "1",
        "sucursal_id": "1",
        "sector_id": "1",
        "puesto_id": "1",
        "codigo_postal": "7000",
        "sexo": "masculino",
        "fecha_nacimiento": "2000-01-01",
        "fecha_ingreso": "2020-01-01",
        "estado": "activo",
    }


def test_empleado_validator_ok():
    validator = EmpleadoValidator()
    errors = validator.validate(
        _valid_employee_form(),
        require_password=False,
        emp_id=None,
        exists_unique=_exists_unique_false,
        exists_codigo=_exists_codigo_true,
    )
    assert errors == []


def test_empleado_validator_invalid_sexo():
    form = _valid_employee_form()
    form["sexo"] = "otro"

    validator = EmpleadoValidator()
    errors = validator.validate(
        form,
        require_password=False,
        emp_id=None,
        exists_unique=_exists_unique_false,
        exists_codigo=_exists_codigo_true,
    )
    assert "Sexo invalido." in errors


def test_empleado_validator_fecha_ingreso_menor_que_nacimiento():
    form = _valid_employee_form()
    form["fecha_nacimiento"] = "2020-01-01"
    form["fecha_ingreso"] = "2019-01-01"

    validator = EmpleadoValidator()
    errors = validator.validate(
        form,
        require_password=False,
        emp_id=None,
        exists_unique=_exists_unique_false,
        exists_codigo=_exists_codigo_true,
    )
    assert "Fecha de ingreso debe ser posterior a fecha de nacimiento." in errors


def test_horarios_normalize_dias_rechaza_superposicion_de_bloques():
    with pytest.raises(ValueError, match="superpuestos"):
        _normalize_dias(
            [
                {
                    "dia_semana": 1,
                    "bloques": [
                        {"entrada": "08:00", "salida": "12:00"},
                        {"entrada": "11:00", "salida": "16:00"},
                    ],
                }
            ]
        )


def test_excepciones_normalize_bloques_rechaza_superposicion():
    with pytest.raises(ValueError, match="superpuestos"):
        normalize_excepcion_bloques(
            [
                {"entrada": "08:00", "salida": "12:00"},
                {"entrada": "11:00", "salida": "13:00"},
            ]
        )


def test_infer_estado_aplica_tolerancia_y_salida_anticipada():
    bloques = [{"entrada": "08:00", "salida": "16:00"}]

    assert infer_estado("08:03", None, bloques, 5) == "ok"
    assert infer_estado("08:06", None, bloques, 5) == "tarde"
    assert infer_estado(None, "15:50", bloques, 5) == "salida_anticipada"
