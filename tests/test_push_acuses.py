"""Acuses de push: la app confirma recibido / abierto con la firma que viaja en el aviso (sin MySQL)."""
import datetime as dt
from contextlib import contextmanager

import pytest

from services import push_service as s

AHORA = dt.datetime(2026, 10, 16, 21, 30, 5, 123)


@pytest.fixture(autouse=True)
def clave(monkeypatch):
    monkeypatch.setenv("SECRET_KEY", "clave-de-prueba-de-al-menos-32-caracteres")
    monkeypatch.setattr(s, "now_local", lambda: AHORA)


@pytest.fixture
def base(monkeypatch):
    sentencias = []

    class Cursor:
        rowcount = 1

        def execute(self, sql, args=()):
            assert sql.count("%s") == len(args)
            sentencias.append((" ".join(sql.split()), args))

    @contextmanager
    def transaction(read_only=False):
        yield Cursor()

    monkeypatch.setattr(s.db, "transaction", transaction)
    return sentencias


def test_firma_estable_y_distinta_por_envio():
    assert s.firma_acuse(7) == s.firma_acuse("7")
    assert s.firma_acuse(7) != s.firma_acuse(8)
    assert len(s.firma_acuse(7)) == 32


def test_sin_secret_key_no_hay_firma(monkeypatch):
    monkeypatch.delenv("SECRET_KEY")
    assert s.firma_acuse(7) is None


def test_recibido_marca_solo_la_primera_vez(base):
    assert s.registrar_acuse(7, s.firma_acuse(7), "recibido") == {"ok": True}
    sql, args = base[0]
    assert "recibido_at=COALESCE(recibido_at, %s)" in sql and "abierto_at" not in sql
    assert args == (AHORA.replace(microsecond=0), 7)


def test_abierto_tambien_marca_recibido(base):
    s.registrar_acuse("7", s.firma_acuse(7), "abierto")
    sql, args = base[0]
    assert "recibido_at=COALESCE(recibido_at, %s)" in sql and "abierto_at=COALESCE(abierto_at, %s)" in sql
    assert args[-1] == 7


@pytest.mark.parametrize("envio_id,firma,evento,status", [
    (7, "0" * 32, "recibido", 403),       # firma falsa
    (8, None, "recibido", 403),           # sin firma
    ("x", "abc", "recibido", 400),        # id invalido
    (7, None, "leido", 400),              # evento desconocido
])
def test_acuses_invalidos_no_escriben(base, envio_id, firma, evento, status):
    with pytest.raises(s.Error) as error:
        s.registrar_acuse(envio_id, firma, evento)
    assert error.value.status == status
    assert base == []


def test_cada_push_lleva_su_envio_y_su_firma(monkeypatch):
    enviados = []
    pendiente = {"id": 41, "empleado_id": 10, "tipo": "comunicado", "titulo": "T", "cuerpo": "C", "intentos": 0,
                 "datos": '{"comunicado_id": "5", "ruta": "/comunicados/5"}'}

    class Cursor:
        rowcount = 1

        def execute(self, sql, args=()):
            pass

    @contextmanager
    def transaction(read_only=False):
        yield Cursor()

    def all_rows(c, sql, args=()):
        if "FROM push_envios" in sql:
            return [dict(pendiente)]
        return [{"id": 1, "token": "token-del-celular"}]

    monkeypatch.setattr(s, "credenciales", lambda: {"project_id": "p"})
    monkeypatch.setattr(s.db, "transaction", transaction)
    monkeypatch.setattr(s.db, "all_rows", all_rows)

    def enviar(cred, token, titulo, cuerpo, datos):
        enviados.append(datos)
        return True, None, False

    assert s.procesar_cola(enviar=enviar)["enviados"] == 1
    assert enviados[0]["envio_id"] == "41"
    assert enviados[0]["acuse"] == s.firma_acuse(41)
    assert enviados[0]["comunicado_id"] == "5" and enviados[0]["tipo"] == "comunicado"


def test_endpoint_sin_sesion(monkeypatch, base):
    import app as app_module

    monkeypatch.setattr(app_module, "init_db", lambda: None)
    app = app_module.create_app()
    app.config.update(TESTING=True)
    client = app.test_client()

    ok = client.post("/api/v1/mobile/push/acuse", json={"envio_id": 7, "acuse": s.firma_acuse(7), "evento": "recibido"})
    assert ok.status_code == 200 and ok.get_json() == {"ok": True}
    falso = client.post("/api/v1/mobile/push/acuse", json={"envio_id": 7, "acuse": "0" * 32, "evento": "recibido"})
    assert falso.status_code == 403 and falso.get_json() == {"error": "Acuse inválido."}
