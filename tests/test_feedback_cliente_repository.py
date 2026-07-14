import repositories.feedback_cliente_repository as feedback_cliente_repository


class _FakeCursor:
    def __init__(self):
        self.calls = []
        self.mode = None

    def execute(self, sql, params=None):
        self.calls.append((sql, params))
        self.mode = "count" if "COUNT(*)" in sql else "rows"

    def fetchall(self):
        if self.mode == "rows":
            return [{"id": 1, "razon_social": "Cliente SA"}]
        return []

    def fetchone(self):
        return {"total": 1}

    def close(self):
        pass


class _FakeDB:
    def __init__(self, cursor):
        self._cursor = cursor

    def cursor(self, dictionary=True):
        return self._cursor

    def close(self):
        pass


def test_feedback_cliente_get_page_search_includes_extended_fields(monkeypatch):
    fake_cursor = _FakeCursor()
    monkeypatch.setattr(feedback_cliente_repository, "get_db", lambda: _FakeDB(fake_cursor))

    rows, total = feedback_cliente_repository.get_page(1, 20, search="cliente", activo=1)

    assert total == 1
    assert rows[0]["id"] == 1
    sql, params = fake_cursor.calls[0]
    assert "CAST(id AS CHAR) LIKE %s" in sql
    assert "CAST(sucursal_origen AS CHAR) LIKE %s" in sql
    assert "telefonos LIKE %s" in sql
    assert "movil LIKE %s" in sql
    assert "email LIKE %s" in sql
    assert "descripcion_provincia LIKE %s" in sql
    assert "LOWER(TRIM(COALESCE(CAST(id AS CHAR), ''))) = %s THEN 0" in sql
    assert params[0] == "%cliente%"
    assert params[15] == 1
    assert params[-2:] == (20, 0)


def test_feedback_cliente_ranked_rows_prioriza_codigo_nombre_y_fallback():
    rows = [
        {
            "id": 3,
            "codigo_externo": "ac-01",
            "razon_social": "Otro Comercio",
            "nombre_fantasia": "Otro Comercio",
            "email": None,
        },
        {
            "id": 1,
            "codigo_externo": "ac",
            "razon_social": "Otro Comercio",
            "nombre_fantasia": "Otro Comercio",
            "email": None,
        },
        {
            "id": 4,
            "codigo_externo": "xx",
            "razon_social": "Mega ACME Distribuciones",
            "nombre_fantasia": "Mega ACME Distribuciones",
            "email": None,
        },
        {
            "id": 2,
            "codigo_externo": "xx",
            "razon_social": "Acme Centro SA",
            "nombre_fantasia": "Acme Centro SA",
            "email": None,
        },
        {
            "id": 5,
            "codigo_externo": "xx",
            "razon_social": "Otro Comercio",
            "nombre_fantasia": "Otro Comercio",
            "email": "ventas@acme.com",
        },
    ]

    ranked = feedback_cliente_repository._feedback_cliente_ranked_rows(rows, "ac")

    assert [row["id"] for row in ranked] == [1, 3, 2, 4, 5]


def test_feedback_cliente_ranked_rows_no_match_devuelve_vacio():
    rows = [
        {
            "id": 1,
            "codigo_externo": "cli-001",
            "razon_social": "Cliente SA",
            "nombre_fantasia": "Cliente Centro",
            "email": "ventas@cliente.com",
        },
        {
            "id": 2,
            "codigo_externo": "cli-002",
            "razon_social": "Otro Comercio",
            "nombre_fantasia": "Otro Comercio",
            "email": "info@otro.com",
        },
    ]

    ranked = feedback_cliente_repository._feedback_cliente_ranked_rows(rows, "zzz")

    assert ranked == []


def test_feedback_cliente_ranked_rows_incluye_id_numerico():
    rows = [
        {
            "id": 11,
            "codigo_externo": "abc",
            "razon_social": "Cliente Once",
            "nombre_fantasia": "Negocio Once",
        },
        {
            "id": 12,
            "codigo_externo": "11",
            "razon_social": "Cliente Codigo",
            "nombre_fantasia": "Negocio Codigo",
        },
    ]

    ranked = feedback_cliente_repository._feedback_cliente_ranked_rows(rows, "11")

    assert [row["id"] for row in ranked] == [12, 11]
