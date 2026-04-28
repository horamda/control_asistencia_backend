import io

import services.empleado_import_service as import_service


class _FakeCursor:
    def __init__(self):
        self.executed = []

    def execute(self, sql, params=None):
        self.executed.append((sql, params))

    def fetchone(self):
        return None

    def close(self):
        return None


class _FakeDb:
    def __init__(self, cursor):
        self._cursor = cursor
        self.closed = False

    def cursor(self, dictionary=False):
        return self._cursor

    def close(self):
        self.closed = True


_COLUMNS = [
    "legajo",
    "dni",
    "cuil",
    "apellido",
    "nombre",
    "sexo",
    "fecha_nacimiento",
    "email",
    "telefono",
    "direccion",
    "codigo_postal",
    "fecha_ingreso",
    "tipo_contrato",
    "modalidad",
    "categoria",
    "obra_social",
    "cod_chess_erp",
    "banco",
    "cbu",
    "numero_emergencia",
    "estado",
    "sucursal_nombre",
    "sector_nombre",
    "puesto_nombre",
    "password",
]


def _patch_import_dependencies(monkeypatch):
    cursor = _FakeCursor()
    db = _FakeDb(cursor)
    created = []

    monkeypatch.setattr(import_service, "get_db", lambda: db)
    monkeypatch.setattr(import_service, "exists_unique", lambda field, value: False)
    monkeypatch.setattr(import_service, "_create_empleado", lambda data: created.append(dict(data)) or len(created))
    monkeypatch.setattr(import_service, "generate_password_hash", lambda value: f"hash:{value}")

    return created, cursor, db


def _template_row(**values):
    data = {column: "" for column in _COLUMNS}
    data.update(values)
    return ";".join(str(data[column]) for column in _COLUMNS)


def test_importar_desde_csv_acepta_template_excel_con_punto_y_coma(monkeypatch):
    created, cursor, db = _patch_import_dependencies(monkeypatch)
    label_row = _template_row(
        legajo="Legajo  *",
        dni="DNI  *",
        apellido="Apellido  *",
        nombre="Nombre  *",
    )
    data_row = _template_row(
        legajo="L001",
        dni="30123456",
        apellido="Perez",
        nombre="Ana",
        sexo="FEMENINO",
        fecha_nacimiento="10/1/1990",
        fecha_ingreso="01/02/2020",
        tipo_contrato="EFECTIVO",
        modalidad="PRESENCIAL",
        estado="ACTIVO",
        sucursal_nombre="Casa Central",
        sector_nombre="Operaciones",
        puesto_nombre="Repartidor",
    )
    content = "\n".join(
        [
            "INSTRUCCIONES: complete la hoja" + ";" * (len(_COLUMNS) - 1),
            ";".join(_COLUMNS),
            label_row,
            data_row,
        ]
    )

    result = import_service.importar_desde_csv(io.BytesIO(content.encode("utf-8")), empresa_id=1)

    assert result == {"creados": 1, "omitidos": 0, "errores": []}
    assert len(created) == 1
    assert created[0]["fecha_nacimiento"] == "1990-01-10"
    assert created[0]["fecha_ingreso"] == "2020-02-01"
    assert created[0]["sexo"] == "femenino"
    assert created[0]["tipo_contrato"] == "efectivo"
    assert created[0]["modalidad"] == "presencial"
    assert created[0]["estado"] == "activo"
    assert db.closed is True
    assert len(cursor.executed) == 3


def test_importar_desde_csv_mantiene_csv_simple_con_comas(monkeypatch):
    created, _, _ = _patch_import_dependencies(monkeypatch)
    content = "\n".join(
        [
            "legajo,dni,apellido,nombre,sexo,fecha_nacimiento,fecha_ingreso",
            "L002,30123457,Gomez,Juan,masculino,1991-03-04,2021-05-06",
        ]
    )

    result = import_service.importar_desde_csv(io.BytesIO(content.encode("utf-8")), empresa_id=1)

    assert result["creados"] == 1
    assert result["errores"] == []
    assert created[0]["legajo"] == "L002"
    assert created[0]["fecha_nacimiento"] == "1991-03-04"
    assert created[0]["fecha_ingreso"] == "2021-05-06"
