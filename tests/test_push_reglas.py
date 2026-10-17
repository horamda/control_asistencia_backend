"""Reglas de avisos: silencio, resumenes, urgentes, desactivados, guardado y cola agrupada (sin MySQL)."""
import datetime as dt
from contextlib import contextmanager

import pytest
from werkzeug.datastructures import MultiDict

from services import push_reglas_service as r
from services import push_service

D = dt.datetime


def _reglas(**cambios):
    reglas = {m["clave"]: r._defecto(m) for m in r.CATALOGO}
    for clave, valores in cambios.items():
        reglas[clave.replace("__", ":")].update(valores)
    return reglas


@pytest.fixture
def config(monkeypatch):
    estado = {"reglas": _reglas(), "silencio": (None, None)}
    monkeypatch.setattr(r, "configuracion", lambda empresa_id: (estado["reglas"], estado["silencio"]))
    return estado


def test_sin_regla_sale_siempre_y_al_momento(config):
    assert r.planificar(1, None) == (True, None, None)
    assert r.planificar(1, "inexistente") == (True, None, None)


def test_inmediato_por_defecto(config):
    assert r.planificar(1, "justificacion", D(2026, 10, 17, 10, 0)) == (True, None, None)


def test_desactivado_no_sale(config):
    config["reglas"] = _reglas(justificacion={"activo": False})
    assert r.planificar(1, "justificacion", D(2026, 10, 17, 10, 0))[0] is False


@pytest.mark.parametrize("ahora,esperado", [
    (D(2026, 10, 17, 23, 30), D(2026, 10, 18, 7, 0)),   # silencio que cruza la medianoche
    (D(2026, 10, 17, 6, 10), D(2026, 10, 17, 7, 0)),
])
def test_silencio_difiere_hasta_que_termina(config, ahora, esperado):
    config["silencio"] = (dt.time(22, 0), dt.time(7, 0))
    assert r.planificar(1, "justificacion", ahora) == (True, esperado, None)


def test_urgente_en_silencio_se_descarta(config):
    config["silencio"] = (dt.time(22, 0), dt.time(7, 0))
    assert r.planificar(1, "salida_pendiente", D(2026, 10, 17, 23, 0)) == (False, None, None)
    assert r.planificar(1, "salida_pendiente", D(2026, 10, 17, 18, 0)) == (True, None, None)


def test_resumen_va_al_proximo_horario_de_los_dias_elegidos(config):
    config["reglas"] = _reglas(revision__vacaciones={"momento": "resumen", "horarios": [dt.time(8, 0), dt.time(13, 0)],
                                                      "dias": [1, 2, 3, 4, 5]})
    # sabado 17/10 a las 10: el proximo horario habil es el lunes 19 a las 8
    enviar, cuando, lote = r.planificar(1, "revision:vacaciones", D(2026, 10, 17, 10, 0))
    assert (enviar, cuando, lote) == (True, D(2026, 10, 19, 8, 0), "revision:vacaciones:202610190800")
    # lunes a las 9: sale a las 13 del mismo dia
    assert r.planificar(1, "revision:vacaciones", D(2026, 10, 19, 9, 0))[1] == D(2026, 10, 19, 13, 0)


def test_combinar_ignora_destinatarios_y_resumen_no_permitidos():
    meta = r.POR_CLAVE["justificacion"]
    regla = r._combinar(meta, dict(activo=1, destinatarios="rrhh,empleado", momento="resumen", horarios="08:00",
                                   dias="1", parametro=None))
    assert regla["destinatarios"] == ["empleado"] and regla["momento"] == "inmediato"


def test_hora_de_mysql_como_timedelta():
    assert r._hora(dt.timedelta(hours=7, minutes=30)) == dt.time(7, 30)


def _form(**extra):
    form = MultiDict()
    for meta in r.CATALOGO:
        form.add(f"activo:{meta['clave']}", "1")
        for d in meta["destinatarios"]:
            form.add(f"destinatario:{meta['clave']}", d)
    for clave, valor in extra.items():
        if isinstance(valor, list):
            for v in valor:
                form.add(clave, v)
        else:
            form[clave] = valor
    return form


@pytest.fixture
def guardado(monkeypatch):
    ejecutado = {}

    class Cursor:
        def executemany(self, sql, filas):
            ejecutado["filas"] = {f[1]: f for f in filas}

        def execute(self, sql, args):
            ejecutado["config"] = args

    @contextmanager
    def transaction(read_only=False):
        yield Cursor()

    monkeypatch.setattr(r.db, "transaction", transaction)
    return ejecutado


def test_guardar_resumen_y_silencio(guardado):
    form = _form(**{"momento:revision:vacaciones": "resumen", "horarios:revision:vacaciones": "13:00, 08:00",
                    "dias:revision:vacaciones": ["1", "5"], "parametro:salida_pendiente": "45",
                    "silencio_desde": "22:00", "silencio_hasta": "07:00"})
    r.guardar({"empresa_id": 1, "user_id": 9}, form)
    fila = guardado["filas"]["revision:vacaciones"]
    assert fila[4:7] == ("resumen", "08:00,13:00", "1,5")
    assert guardado["filas"]["salida_pendiente"][7] == 45
    assert guardado["config"][1:3] == (dt.time(22, 0), dt.time(7, 0))


@pytest.mark.parametrize("extra,mensaje", [
    ({"momento:revision:epp": "resumen", "horarios:revision:epp": ""}, "al menos un horario"),
    ({"parametro:recordatorio_reunion": "500"}, "entre 5 y 240"),
    ({"silencio_desde": "22:00"}, "desde y hasta"),
])
def test_guardar_valida(guardado, extra, mensaje):
    with pytest.raises(r.Error, match=mensaje):
        r.guardar({"empresa_id": 1}, _form(**extra))


def test_activo_sin_destinatarios_es_error(guardado):
    form = _form()
    form.setlist("destinatario:revision:epp", [])
    with pytest.raises(r.Error, match="elegí a quién avisar"):
        r.guardar({"empresa_id": 1}, form)


# --- Cola: resumenes en un solo aviso -------------------------------------------------------------------

def test_varios_del_mismo_resumen_salen_en_un_solo_aviso(monkeypatch):
    monkeypatch.setenv("SECRET_KEY", "clave-de-prueba-de-al-menos-32-caracteres")
    lote = "revision:justificaciones:202610170800"
    pendientes = [
        dict(id=1, empleado_id=50, tipo="revision_pendiente", titulo="Justificación para revisar", cuerpo="Perez Ana",
             intentos=0, datos='{"ruta": "/revisiones/justificaciones"}', lote=lote),
        dict(id=2, empleado_id=50, tipo="revision_pendiente", titulo="Justificación para revisar", cuerpo="Gómez Luis",
             intentos=0, datos="{}", lote=lote),
        dict(id=3, empleado_id=50, tipo="revision_pendiente", titulo="Vacaciones para revisar", cuerpo="Díaz Sofía",
             intentos=0, datos="{}", lote=lote),
        dict(id=4, empleado_id=60, tipo="justificacion", titulo="Justificación aprobada", cuerpo="Tu justificación…",
             intentos=0, datos="{}", lote=None),
    ]
    actualizados, enviados, consultas = [], [], []

    class Cursor:
        rowcount = 1

        def execute(self, sql, args=()):
            if sql.lstrip().startswith("UPDATE push_envios SET estado=%s"):
                actualizados.append((args[0], args[-1]))
            consultas.append(" ".join(sql.split()))

    @contextmanager
    def transaction(read_only=False):
        yield Cursor()

    def all_rows(c, sql, args=()):
        if "FROM push_envios" in sql:
            assert "programado_para IS NULL OR programado_para <= %s" in sql
            return [dict(p) for p in pendientes]
        return [{"id": 1, "token": "t"}]

    monkeypatch.setattr(push_service, "credenciales", lambda: {"project_id": "p"})
    monkeypatch.setattr(push_service.db, "transaction", transaction)
    monkeypatch.setattr(push_service.db, "all_rows", all_rows)

    def enviar(cred, token, titulo, cuerpo, datos):
        enviados.append((titulo, cuerpo, datos))
        return True, None, False

    resumen = push_service.procesar_cola(enviar=enviar)
    assert resumen["enviados"] == 2  # un aviso por persona
    titulo, cuerpo, datos = enviados[0]
    assert titulo == "Tenés 3 solicitudes para revisar"
    assert cuerpo == "Justificación para revisar (2), Vacaciones para revisar"
    assert datos["cantidad"] == "3" and datos["envio_id"] == "1" and datos["ruta"] == "/revisiones/justificaciones"
    assert enviados[1][0] == "Justificación aprobada"
    assert sorted(actualizados) == [("enviado", 1), ("enviado", 2), ("enviado", 3), ("enviado", 4)]
