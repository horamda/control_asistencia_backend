import io

import services.articulo_pedido_import_service as import_service


class _FakeCursor:
    def __init__(self, fetchall_rows=None):
        self.executed = []
        self.executemany_calls = []
        self._fetchall_rows = list(fetchall_rows or [])
        self.rowcount = 0

    def execute(self, sql, params=None):
        self.executed.append((sql, params))
        if "UPDATE articulos_catalogo_pedidos SET habilitado_pedido = 0" in sql:
            self.rowcount = 2

    def executemany(self, sql, seq):
        rows = list(seq)
        self.executemany_calls.append((sql, rows))

    def fetchall(self):
        if self._fetchall_rows:
            return self._fetchall_rows.pop(0)
        return []

    def close(self):
        return None


class _FakeDb:
    def __init__(self, cursor):
        self._cursor = cursor
        self.committed = False

    def cursor(self, dictionary=False):
        return self._cursor

    def commit(self):
        self.committed = True

    def close(self):
        return None


def test_importar_articulos_filtra_por_reglas_y_upserta(monkeypatch):
    csv_content = """Articulo;Descripcion articulo;Activo;Anulado;Usado en dispositivo movil;TIPO DE PRODUCTO;Unidades por bulto;Bultos por pallet;MARCA;FAMILIA;SABOR;DIVISION;Codigo de barras;Codigo de barras unidad;Presentacion bulto;Descripcion presentacion bulto;Presentacion unidad;Descripcion presentacion unidad
1;Articulo valido;SI;NO;SI;MERCADERIA;8;72;Marca;Familia;Sabor;Division;123;456;;;;
2;Anulado;SI;SI;SI;MERCADERIA;8;72;Marca;Familia;Sabor;Division;123;456;;;;
3;No mercaderia;SI;NO;SI;SERVICIO;8;72;Marca;Familia;Sabor;Division;123;456;;;;
"""
    cursor = _FakeCursor(fetchall_rows=[[]])
    db = _FakeDb(cursor)
    monkeypatch.setattr(import_service, "get_db", lambda: db)

    result = import_service.importar_articulos_desde_csv(io.BytesIO(csv_content.encode("utf-8")))

    assert result["total_filas"] == 3
    assert result["importables"] == 1
    assert result["creados"] == 1
    assert result["actualizados"] == 0
    assert result["deshabilitados"] == 2
    assert result["ignorados"] == 2
    assert result["errores"] == []
    assert db.committed is True
    assert len(cursor.executemany_calls) == 1
    _, rows = cursor.executemany_calls[0]
    assert rows[0]["codigo_articulo"] == "1"
    assert rows[0]["descripcion"] == "Articulo valido"


def test_importar_articulos_reporta_duplicado_en_csv(monkeypatch):
    csv_content = """Articulo;Descripcion articulo;Activo;Anulado;Usado en dispositivo movil;TIPO DE PRODUCTO;Unidades por bulto
1;Articulo valido;SI;NO;SI;MERCADERIA;8
1;Articulo duplicado;SI;NO;SI;MERCADERIA;8
"""
    cursor = _FakeCursor(fetchall_rows=[[]])
    db = _FakeDb(cursor)
    monkeypatch.setattr(import_service, "get_db", lambda: db)

    result = import_service.importar_articulos_desde_csv(io.BytesIO(csv_content.encode("utf-8")))

    assert result["importables"] == 1
    assert len(result["errores"]) == 1
    assert "duplicado" in result["errores"][0]["motivo"].lower()
