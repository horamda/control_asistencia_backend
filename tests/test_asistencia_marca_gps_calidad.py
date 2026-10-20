"""Repositorio de marcas: la calidad del GPS (contrato 1.54.0) solo entra al INSERT cuando llega algun dato."""
from repositories import asistencia_marca_repository as repo


class _Cursor:
    lastrowid = 9

    def __init__(self):
        self.ejecutadas = []

    def execute(self, sql, params=()):
        self.ejecutadas.append((sql, params))

    def close(self):
        pass


class _Db:
    def __init__(self):
        self.cur = _Cursor()

    def cursor(self, *args, **kwargs):
        return self.cur

    def commit(self):
        pass

    def close(self):
        pass


BASE = dict(empresa_id=1, empleado_id=10, fecha="2026-10-19", hora="08:00", accion="ingreso", metodo="qr",
            tipo_marca="jornada", lat=-34.6, lon=-58.4, foto=None, gps_ok=True, gps_distancia_m=10, gps_tolerancia_m=80,
            gps_ref_lat=-34.6, gps_ref_lon=-58.4, estado="ok")


def _insert(**extra):
    db = _Db()
    repo.create(**BASE, **extra, _db=db)
    sql, params = db.cur.ejecutadas[0]
    return " ".join(sql.split()), params


def test_sin_calidad_el_insert_queda_como_antes():
    sql, params = _insert()
    assert "gps_precision_m" not in sql and len(params) == 18 and sql.count("%s") == 18


def test_con_calidad_agrega_solo_lo_que_llega():
    sql, params = _insert(gps_precision_m=12.5, gps_simulada=False)
    assert "observaciones, gps_precision_m, gps_simulada)" in sql and "gps_edad_s" not in sql
    assert sql.count("%s") == 20 and params[-2:] == (12.5, 0)
