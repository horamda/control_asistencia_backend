"""Imagen de los comunicados: compresion, link firmado para el push y mensaje de Firebase (sin MySQL)."""
import io
from contextlib import contextmanager

import pytest
from flask import Flask
from PIL import Image
from werkzeug.datastructures import FileStorage

from services import comunicado_service as s
from services import push_service
from web.comunicados.routes import web as comunicados_web

AHORA = 1_800_000_000


@pytest.fixture
def app():
    app = Flask(__name__)
    app.secret_key = "clave-de-prueba"
    app.register_blueprint(comunicados_web)
    return app


@pytest.fixture
def con_imagen(monkeypatch):
    """Base falsa: el comunicado 5 tiene imagen."""

    @contextmanager
    def transaction(read_only=False):
        yield None

    monkeypatch.setattr(s.db, "transaction", transaction)
    monkeypatch.setattr(s.db, "one", lambda c, sql, args: {"contenido": b"jpeg"} if args[0] == 5 else None)


def _png(ancho=2400, alto=1200):
    buffer = io.BytesIO()
    Image.new("RGB", (ancho, alto), (200, 30, 30)).save(buffer, format="PNG")
    buffer.seek(0)
    return FileStorage(stream=buffer, filename="aviso.png", content_type="image/png")


def test_imagen_subida_se_comprime_a_jpeg():
    contenido = s._imagen_subida(_png())
    with Image.open(io.BytesIO(contenido)) as imagen:
        assert imagen.format == "JPEG"
        assert max(imagen.size) == 1800


def test_sin_archivo_no_hay_imagen():
    assert s._imagen_subida(None) is None
    assert s._imagen_subida(FileStorage(stream=io.BytesIO(b""), filename="")) is None


def test_archivo_que_no_es_imagen_se_rechaza():
    with pytest.raises(s.Error, match="imagen válida"):
        s._imagen_subida(FileStorage(stream=io.BytesIO(b"no soy una imagen"), filename="x.png"))


def test_link_push_firmado_y_con_vencimiento(app, con_imagen):
    with app.test_request_context(base_url="https://panel.test"):
        url = s.url_imagen_push(5, ahora=AHORA)
    vence = AHORA + s.IMAGEN_PUSH_DIAS * 86400
    assert url.startswith(f"https://panel.test/comunicados/imagen-push/5/{vence}/")
    firma = url.rsplit("/", 1)[1].removesuffix(".jpg")
    with app.app_context():
        assert s.imagen_push(5, vence, firma, ahora=AHORA)["contenido"] == b"jpeg"
        with pytest.raises(s.Error):
            s.imagen_push(5, vence, firma, ahora=vence + 1)  # vencido
        with pytest.raises(s.Error):
            s.imagen_push(6, vence, firma, ahora=AHORA)  # firma de otro comunicado
        with pytest.raises(s.Error):
            s.imagen_push(5, vence + 86400, firma, ahora=AHORA)  # vencimiento alterado


def test_sin_https_no_se_manda_imagen_en_el_push(app):
    with app.test_request_context(base_url="http://localhost"):
        assert s.url_imagen_push(5) is None


def test_ruta_publica_sirve_la_imagen_solo_con_firma_valida(app, con_imagen):
    vence = 4_000_000_000
    with app.app_context():
        firma = s.firma_imagen(5, vence)
    client = app.test_client()

    ok = client.get(f"/comunicados/imagen-push/5/{vence}/{firma}.jpg")
    assert ok.status_code == 200
    assert ok.mimetype == "image/jpeg"
    assert ok.data == b"jpeg"
    assert client.get(f"/comunicados/imagen-push/5/{vence}/{'0' * 32}.jpg").status_code == 404


def test_mensaje_firebase_lleva_la_imagen():
    datos = {"tipo": "comunicado", "ruta": "/comunicados/5", "imagen": "https://panel.test/comunicados/imagen-push/5/1/a.jpg"}
    mensaje = push_service._mensaje("token", "Corte de luz", "El jueves…", datos)["message"]
    assert mensaje["notification"]["image"] == datos["imagen"]
    assert mensaje["data"]["imagen"] == datos["imagen"]


def test_mensaje_firebase_sin_imagen_no_cambia():
    mensaje = push_service._mensaje("token", "Turno", "Mañana", {"tipo": "reunion", "ruta": "/reuniones"})["message"]
    assert "image" not in mensaje["notification"]


def test_item_de_la_app_trae_url_de_imagen():
    import datetime as dt

    fila = {"id": 5, "titulo": "T", "mensaje": "M", "creado_at": dt.datetime(2026, 10, 16, 9, 30), "leido_at": None}
    assert s._item(dict(fila, tiene_imagen=1))["imagen_url"] == "/api/v1/mobile/comunicados/5/imagen"
    assert s._item(dict(fila, tiene_imagen=0))["imagen_url"] is None
