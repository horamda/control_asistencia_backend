import repositories.articulo_catalogo_pedido_repository as articulo_catalogo_pedido_repository
import repositories.feedback_cliente_repository as feedback_cliente_repository
import repositories.feedback_repository as feedback_repository


class _FakeCursor:
    def __init__(self):
        self.calls = []
        self._mode = None

    def execute(self, sql, params=None):
        self.calls.append((sql, params))
        self._mode = "count" if "COUNT(*)" in sql else "rows"

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
    assert params[:21] == tuple(["%cliente%"] * 21)
    assert params[21:42] == tuple(["%urgente%"] * 21)
    assert params[-2:] == (20, 0)


def test_feedback_cliente_repository_search_tokenizes_terms(monkeypatch):
    fake_cursor = _FakeCursor()
    monkeypatch.setattr(feedback_cliente_repository, "get_db", lambda: _FakeDB(fake_cursor))

    rows, total = feedback_cliente_repository.get_page(1, 20, search="cliente centro", activo=1)

    assert total == 1
    assert rows[0]["id"] == 1

    sql, params = fake_cursor.calls[0]
    assert "CAST(sucursal_origen AS CHAR) LIKE %s" in sql
    assert "descripcion_provincia LIKE %s" in sql
    assert params[:14] == tuple(["%cliente%"] * 14)
    assert params[14:28] == tuple(["%centro%"] * 14)
    assert params[28] == 1
    assert params[-2:] == (20, 0)


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
