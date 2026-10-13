"""Per-request DBAPI metrics. Never records SQL text, parameters or results."""
from time import perf_counter
from flask import g, has_request_context


class MeasuredCursor:
    def __init__(self, cursor):
        self._cursor = cursor

    def __getattr__(self, name):
        return getattr(self._cursor, name)

    def __iter__(self):
        return iter(self._cursor)

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()

    def _run(self, method, *args, **kwargs):
        start = perf_counter()
        try:
            return getattr(self._cursor, method)(*args, **kwargs)
        finally:
            if has_request_context():
                g.db_ms = getattr(g, 'db_ms', 0) + (perf_counter() - start) * 1000
                g.db_queries = getattr(g, 'db_queries', 0) + 1

    def execute(self, *args, **kwargs):
        return self._run('execute', *args, **kwargs)

    def executemany(self, *args, **kwargs):
        return self._run('executemany', *args, **kwargs)


class MeasuredConnection:
    def __init__(self, connection):
        self._connection = connection

    def __getattr__(self, name):
        return getattr(self._connection, name)

    def cursor(self, *args, **kwargs):
        return MeasuredCursor(self._connection.cursor(*args, **kwargs))

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()
