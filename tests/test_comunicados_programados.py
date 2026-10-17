"""Comunicados programados: proximo envio, validacion y ejecucion (sin MySQL)."""
import datetime as dt
import json
from contextlib import contextmanager

import pytest
from werkzeug.datastructures import MultiDict

from services import comunicado_programado_service as p

D = dt.datetime


def _prog(**valores):
    base = dict(frecuencia="diaria", hora=dt.time(9, 0), fecha_inicio=dt.date(2026, 10, 17), fecha_fin=None,
                dias_semana=None, dia_mes=None, solo_habiles=0, max_envios=None, envios=0)
    base.update(valores)
    return base


def test_una_vez():
    prog = _prog(frecuencia="una_vez", fecha_inicio=dt.date(2026, 10, 20), hora=dt.time(8, 30))
    assert p.proxima(prog, D(2026, 10, 17, 12, 0)) == D(2026, 10, 20, 8, 30)
    assert p.proxima(dict(prog, envios=1), D(2026, 10, 17, 12, 0)) is None
    assert p.proxima(prog, D(2026, 10, 20, 9, 0)) is None  # ya paso


def test_diaria_hoy_si_no_paso_la_hora_si_no_manana():
    assert p.proxima(_prog(), D(2026, 10, 17, 8, 0)) == D(2026, 10, 17, 9, 0)
    assert p.proxima(_prog(), D(2026, 10, 17, 9, 0)) == D(2026, 10, 18, 9, 0)


def test_diaria_solo_habiles_saltea_domingo_y_no_laborables():
    feriado = dt.date(2026, 10, 19)  # lunes no laborable
    habil = lambda fecha: fecha.isoweekday() != 7 and fecha != feriado  # noqa: E731
    # sabado 17 despues de las 9 -> domingo 18 (no) -> lunes 19 (feriado) -> martes 20
    assert p.proxima(_prog(solo_habiles=1), D(2026, 10, 17, 10, 0), habil) == D(2026, 10, 20, 9, 0)


def test_semanal_lunes_y_jueves():
    prog = _prog(frecuencia="semanal", dias_semana="1,4")
    assert p.proxima(prog, D(2026, 10, 17, 10, 0)) == D(2026, 10, 19, 9, 0)  # sabado -> lunes
    assert p.proxima(prog, D(2026, 10, 19, 9, 0)) == D(2026, 10, 22, 9, 0)  # lunes ya enviado -> jueves


def test_mensual_dia_31_en_meses_cortos_y_habil():
    prog = _prog(frecuencia="mensual", dia_mes=31)
    assert p.proxima(prog, D(2026, 10, 31, 10, 0)) == D(2026, 11, 30, 9, 0)
    # 1 de noviembre 2026 es domingo: con solo habiles pasa al lunes 2
    habil = lambda fecha: fecha.isoweekday() != 7  # noqa: E731
    assert p.proxima(_prog(frecuencia="mensual", dia_mes=1, solo_habiles=1), D(2026, 10, 17, 10, 0), habil) == D(2026, 11, 2, 9, 0)


def test_termina_por_fecha_o_cantidad():
    assert p.proxima(_prog(fecha_fin=dt.date(2026, 10, 18)), D(2026, 10, 18, 9, 0)) is None
    assert p.proxima(_prog(max_envios=3, envios=3), D(2026, 10, 17, 8, 0)) is None


def test_descripcion_legible():
    assert p.descripcion(_prog(frecuencia="semanal", dias_semana="1,4", solo_habiles=1)) == "Lunes y jueves a las 09:00 (solo hábiles)"
    assert p.descripcion(_prog(frecuencia="mensual", dia_mes=5, max_envios=6)) == "El día 5 de cada mes a las 09:00, 6 envíos"
    assert p.descripcion(_prog(frecuencia="una_vez", fecha_inicio=dt.date(2026, 12, 24))) == "El 24/12/2026 a las 09:00"


@pytest.mark.parametrize("campos,mensaje", [
    ({"frecuencia": "anual"}, "frecuencia"),
    ({"frecuencia": "semanal", "hora": "09:00"}, "día de la semana"),
    ({"frecuencia": "mensual", "hora": "09:00", "dia_mes": "40"}, "1 a 31"),
    ({"frecuencia": "diaria", "hora": ""}, "hora"),
    ({"frecuencia": "diaria", "hora": "09:00", "termina": "cantidad", "max_envios": "0"}, "1 a 1000"),
    ({"frecuencia": "diaria", "hora": "09:00", "termina": "fecha", "fecha_inicio": "2026-10-20", "fecha_fin": "2026-10-19"}, "anterior al inicio"),
])
def test_programacion_invalida(campos, mensaje):
    with pytest.raises(p.Error, match=mensaje):
        p._programacion(MultiDict(campos), D(2026, 10, 17, 10, 0))


def test_programacion_semanal_valida():
    prog = p._programacion(MultiDict([("frecuencia", "semanal"), ("hora", "08:15"), ("dias_semana", "4"),
                                      ("dias_semana", "1"), ("solo_habiles", "1"), ("termina", "cantidad"),
                                      ("max_envios", "10")]), D(2026, 10, 17, 10, 0))
    assert prog["dias_semana"] == "1,4" and prog["hora"] == dt.time(8, 15)
    assert prog["solo_habiles"] == 1 and prog["max_envios"] == 10 and prog["fecha_inicio"] == dt.date(2026, 10, 17)


def test_habiles_consulta_el_calendario_una_vez_por_mes():
    consultas = []

    def consulta(**kw):
        consultas.append((kw["year"], kw["month"]))
        return {"2026-10-19"}

    habil = p.Habiles(1, consulta)
    assert habil(dt.date(2026, 10, 19)) is False and habil(dt.date(2026, 10, 20)) is True
    assert habil(dt.date(2026, 10, 18)) is False  # domingo, sin consultar
    assert consultas == [(2026, 10)]


# --- Ejecucion por el scheduler ----------------------------------------------------------------------

@pytest.fixture
def base(monkeypatch):
    fila = dict(id=3, empresa_id=1, titulo="Pausa activa", mensaje="A las 10 hacemos pausa.", imagen=None, imagen_push=None,
                destinatarios=json.dumps(dict(reglas=["todos"], empleados=[], sucursales=[], base_url="https://x.test/")),
                frecuencia="diaria", hora=dt.timedelta(hours=10), fecha_inicio=dt.date(2026, 10, 1), fecha_fin=None,
                dias_semana=None, dia_mes=None, solo_habiles=0, max_envios=None, envios=4,
                proximo_envio=D(2026, 10, 17, 10, 0), estado="activo", creado_por=9)
    actualizaciones, envios = [], []

    class Cursor:
        def execute(self, sql, args=()):
            if sql.lstrip().startswith("UPDATE comunicados_programados"):
                actualizaciones.append(args)

        def fetchone(self):
            return dict(fila)

    @contextmanager
    def transaction(read_only=False):
        yield Cursor()

    monkeypatch.setattr(p.db, "transaction", transaction)
    monkeypatch.setattr(p.db, "all_rows", lambda c, sql, args: [{"id": 3}])
    monkeypatch.setattr(p, "Habiles", lambda empresa_id: (lambda fecha: True))
    monkeypatch.setattr(p.com, "enviar_contenido", lambda who, data, contenido, push, **kw: envios.append((who, data, kw)) or (50, 12))
    return fila, actualizaciones, envios


def test_ejecuta_y_agenda_el_siguiente(base):
    _, actualizaciones, envios = base
    assert p.ejecutar_vencidos(D(2026, 10, 17, 10, 0, 30)) == 1
    who, data, kw = envios[0]
    assert who == {"empresa_id": 1, "user_id": 9} and data["reglas"] == ["todos"] and data["titulo"] == "Pausa activa"
    assert kw == {"programado_id": 3, "base_url": "https://x.test/"}
    _, siguiente, estado, _ = actualizaciones[0]
    assert siguiente == D(2026, 10, 18, 10, 0) and estado == "activo"


def test_ultimo_envio_finaliza(base):
    fila, actualizaciones, _ = base
    fila.update(max_envios=5)
    p.ejecutar_vencidos(D(2026, 10, 17, 10, 1))
    assert actualizaciones[0][1:3] == (None, "finalizado")


def test_sin_destinatarios_hoy_saltea_y_sigue(base, monkeypatch):
    _, actualizaciones, _ = base

    def sin_nadie(*a, **k):
        raise p.Error("Con esa selección no hay empleados activos para recibir el comunicado.")

    monkeypatch.setattr(p.com, "enviar_contenido", sin_nadie)
    assert p.ejecutar_vencidos(D(2026, 10, 17, 10, 1)) == 0
    assert actualizaciones[0][2] == "activo"


def test_pausado_o_no_vencido_no_se_envia(base):
    fila, actualizaciones, envios = base
    fila.update(estado="pausado")
    assert p.ejecutar_vencidos(D(2026, 10, 17, 10, 1)) == 0 and envios == [] and actualizaciones == []
