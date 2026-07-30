import repositories.adelanto_repository as adelanto_repository


class _FakeCursor:
    def __init__(self, *, fetchall_rows=None, fetchone_rows=None):
        self.executed = []
        self._fetchall_rows = list(fetchall_rows or [])
        self._fetchone_rows = list(fetchone_rows or [])

    def execute(self, sql, params=None):
        self.executed.append((sql, params))

    def fetchall(self):
        return list(self._fetchall_rows)

    def fetchone(self):
        if self._fetchone_rows:
            return self._fetchone_rows.pop(0)
        return None

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


def test_get_page_schema_viejo_no_usa_columnas_resolucion(monkeypatch):
    cursor = _FakeCursor(fetchall_rows=[], fetchone_rows=[{"total": 0}])
    db = _FakeDb(cursor)
    monkeypatch.setattr(adelanto_repository, "get_db", lambda: db)
    monkeypatch.setattr(adelanto_repository, "_adelantos_resolution_support", lambda cursor: (False, False))

    rows, total = adelanto_repository.get_page(page=1, per_page=20)

    assert rows == []
    assert total == 0
    sql = cursor.executed[0][0]
    assert "NULL AS resuelto_by_usuario" in sql
    assert "NULL AS resuelto_at" in sql
    assert "LEFT JOIN usuarios u ON u.id = a.resuelto_by_usuario_id" not in sql


def test_get_page_filtra_por_sucursal_y_sector(monkeypatch):
    cursor = _FakeCursor(fetchall_rows=[], fetchone_rows=[{"total": 0}])
    db = _FakeDb(cursor)
    monkeypatch.setattr(adelanto_repository, "get_db", lambda: db)
    monkeypatch.setattr(adelanto_repository, "_adelantos_resolution_support", lambda cursor: (False, False))

    rows, total = adelanto_repository.get_page(page=1, per_page=20, sucursal_id=5, sector_id=7)

    assert rows == []
    assert total == 0
    select_sql, select_params = cursor.executed[0]
    assert "LEFT JOIN sucursales s ON s.id = e.sucursal_id" in select_sql
    assert "LEFT JOIN sectores sec ON sec.id = e.sector_id" in select_sql
    assert "s.nombre AS sucursal_nombre" in select_sql
    assert "sec.nombre AS sector_nombre" in select_sql
    assert "e.sucursal_id = %s" in select_sql
    assert "e.sector_id = %s" in select_sql
    assert 5 in select_params
    assert 7 in select_params


def test_update_estado_schema_viejo_actualiza_solo_estado(monkeypatch):
    cursor = _FakeCursor()
    db = _FakeDb(cursor)
    monkeypatch.setattr(adelanto_repository, "get_db", lambda: db)
    monkeypatch.setattr(adelanto_repository, "_adelantos_resolution_support", lambda cursor: (False, False))

    adelanto_repository.update_estado(81, "aprobado", resuelto_by_usuario_id=99)

    sql, params = cursor.executed[0]
    assert "SET estado = %s" in sql
    assert "resuelto_by_usuario_id" not in sql
    assert "resuelto_at" not in sql
    assert params == ("aprobado", 81)
    assert db.committed is True
