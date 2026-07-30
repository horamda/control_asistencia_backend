import repositories.articulo_catalogo_pedido_repository as articulo_catalogo_pedido_repository
import repositories.empleado_repository as empleado_repository
import repositories.feedback_cliente_repository as feedback_cliente_repository
import repositories.feedback_repository as feedback_repository


class _FakeCursor:
    def __init__(self):
        self.calls = []
        self._mode = None

    def execute(self, sql, params=None):
        self.calls.append((sql, params))
        normalized = " ".join(str(sql).split()).upper()
        self._mode = "count" if normalized.startswith("SELECT COUNT(*) AS TOTAL FROM") else "rows"

    def fetchall(self):
        if self._mode == "rows":
            return [{"id": 1}]
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


def test_feedback_repository_search_tokenizes_terms(monkeypatch):
    fake_cursor = _FakeCursor()
    monkeypatch.setattr(feedback_repository, "get_db", lambda: _FakeDB(fake_cursor))

    rows, total = feedback_repository.get_page(1, 20, search="cliente urgente")

    assert total == 1
    assert rows[0]["id"] == 1

    sql, params = fake_cursor.calls[1]
    assert "fb.resolucion_descripcion LIKE %s" in sql
    assert params[:25] == tuple(["%cliente%"] * 25)
    assert params[25:50] == tuple(["%urgente%"] * 25)
    assert params[-2:] == (20, 0)


def test_feedback_cliente_repository_search_tokenizes_terms(monkeypatch):
    fake_cursor = _FakeCursor()
    monkeypatch.setattr(feedback_cliente_repository, "get_db", lambda: _FakeDB(fake_cursor))

    rows, total = feedback_cliente_repository.get_page(1, 20, search="cliente centro", activo=1)

    assert total == 1
    assert rows[0]["id"] == 1

    sql, params = fake_cursor.calls[0]
    assert "LOWER(TRIM(COALESCE(CAST(sucursal_origen AS CHAR), ''))) LIKE %s" in sql
    assert "LOWER(TRIM(COALESCE(descripcion_provincia, ''))) LIKE %s" in sql
    assert params[:15] == tuple(["%cliente%"] * 15)
    assert params[15:30] == tuple(["%centro%"] * 15)
    assert params[30] == 1
    assert params[-2:] == (20, 0)
    assert sql.count("%s") == len(params)


def test_articulo_catalogo_pedido_repository_search_tokenizes_terms(monkeypatch):
    fake_cursor = _FakeCursor()
    monkeypatch.setattr(articulo_catalogo_pedido_repository, "get_db", lambda: _FakeDB(fake_cursor))

    rows, total = articulo_catalogo_pedido_repository.get_page(1, 20, search="gas cola", habilitado_only=True)

    assert total == 1
    assert rows[0]["id"] == 1

    sql, params = fake_cursor.calls[0]
    assert "a.codigo_barras LIKE %s" in sql
    assert "CAST(a.unidades_por_bulto AS CHAR) LIKE %s" in sql
    assert params[:16] == tuple(["%gas%"] * 16)
    assert params[16:32] == tuple(["%cola%"] * 16)
    assert params[32] == 20
    assert params[33] == 0


def test_empleado_repository_search_tokenizes_full_name(monkeypatch):
    fake_cursor = _FakeCursor()
    monkeypatch.setattr(empleado_repository, "get_db", lambda: _FakeDB(fake_cursor))

    rows, total = empleado_repository.get_page(1, 20, search="moran juan francisco", activo=1)

    assert total == 1
    assert rows[0]["id"] == 1

    sql, params = fake_cursor.calls[0]
    assert "CONCAT_WS(' ', e.apellido, e.nombre) LIKE %s" in sql
    assert "CONCAT_WS(' ', e.nombre, e.apellido) LIKE %s" in sql
    assert params[:6] == tuple(["%moran%"] * 6)
    assert params[6:12] == tuple(["%juan%"] * 6)
    assert params[12:18] == tuple(["%francisco%"] * 6)
    assert params[18] == 1
    assert params[-2:] == (20, 0)
