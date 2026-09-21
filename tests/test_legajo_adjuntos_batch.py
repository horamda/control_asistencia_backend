from repositories import legajo_adjunto_repository as repo


def test_empty_batch_does_not_connect(monkeypatch):
    def fail():
        raise AssertionError('Empty history must not query the database')
    monkeypatch.setattr(repo, 'get_db', fail)
    assert repo.get_adjuntos_by_eventos([]) == {}


def test_batch_groups_metadata_in_one_query(monkeypatch):
    calls = []
    class Cursor:
        def execute(self, sql, params):
            calls.append((sql, params))
        def fetchall(self):
            return [{'id': 3, 'evento_id': 12}, {'id': 2, 'evento_id': 11}, {'id': 1, 'evento_id': 12}]
        def close(self): pass
    class Db:
        def cursor(self, dictionary=False): return Cursor()
        def close(self): pass
    monkeypatch.setattr(repo, 'get_db', Db)
    result = repo.get_adjuntos_by_eventos([11, 12, 13, 11])
    assert len(calls) == 1
    assert calls[0][1] == (11, 12, 13)
    assert "a.estado = 'activo'" in calls[0][0]
    assert 'legajo_evento_adjuntos_db' not in calls[0][0]
    assert [r['id'] for r in result[12]] == [3, 1]
    assert result[13] == []
