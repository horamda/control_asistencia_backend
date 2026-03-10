import io

from PIL import Image
from werkzeug.datastructures import FileStorage

import services.profile_photo_service as photo_service


def _make_image_bytes(fmt: str = "JPEG", size=(1600, 1200), color=(20, 120, 220)):
    image = Image.new("RGB", size, color=color)
    buffer = io.BytesIO()
    image.save(buffer, format=fmt, quality=95)
    return buffer.getvalue()


def test_normalize_profile_photo_webp_and_resize(monkeypatch):
    monkeypatch.setenv("FOTO_OUTPUT_FORMAT", "webp")
    monkeypatch.setenv("FOTO_FORCE_CROP", "1")
    monkeypatch.setenv("FOTO_MAX_WIDTH", "320")
    monkeypatch.setenv("FOTO_MAX_HEIGHT", "320")
    monkeypatch.setenv("FOTO_CROP_WIDTH", "320")
    monkeypatch.setenv("FOTO_CROP_HEIGHT", "320")
    monkeypatch.setenv("FOTO_OUTPUT_QUALITY", "80")

    raw = _make_image_bytes(size=(2000, 1400))
    normalized, ext, mime = photo_service._normalize_profile_photo(raw, output_max_bytes=300000)

    assert ext == "webp"
    assert mime == "image/webp"
    assert len(normalized) <= 300000

    with Image.open(io.BytesIO(normalized)) as out:
        assert out.width <= 320
        assert out.height <= 320


def test_normalize_profile_photo_crop_fixed_size(monkeypatch):
    monkeypatch.setenv("FOTO_OUTPUT_FORMAT", "jpg")
    monkeypatch.setenv("FOTO_FORCE_CROP", "1")
    monkeypatch.setenv("FOTO_CROP_WIDTH", "256")
    monkeypatch.setenv("FOTO_CROP_HEIGHT", "256")
    monkeypatch.setenv("FOTO_OUTPUT_QUALITY", "80")

    raw = _make_image_bytes(size=(1800, 900))
    normalized, ext, mime = photo_service._normalize_profile_photo(raw, output_max_bytes=250000)

    assert ext == "jpg"
    assert mime == "image/jpeg"
    assert len(normalized) <= 250000

    with Image.open(io.BytesIO(normalized)) as out:
        assert out.width == 256
        assert out.height == 256


def test_upload_profile_photo_db_uses_relative_url_if_no_public_base(monkeypatch):
    monkeypatch.setenv("FOTO_STORAGE_BACKEND", "db")
    monkeypatch.delenv("FOTO_PUBLIC_BASE_URL", raising=False)
    monkeypatch.delenv("API_PUBLIC_BASE_URL", raising=False)
    monkeypatch.setenv("FOTO_OUTPUT_FORMAT", "jpg")
    monkeypatch.setenv("FOTO_MAX_WIDTH", "512")
    monkeypatch.setenv("FOTO_MAX_HEIGHT", "512")
    monkeypatch.setenv("FOTO_MAX_BYTES", "500000")
    monkeypatch.setenv("FOTO_INPUT_MAX_BYTES", "5000000")

    captured = {}

    def _fake_db_upsert_photo(dni: str, mime_type: str, ext: str, data: bytes):
        captured["dni"] = dni
        captured["mime_type"] = mime_type
        captured["ext"] = ext
        captured["data_size"] = len(data)
        return True

    monkeypatch.setattr(photo_service, "_db_upsert_photo", _fake_db_upsert_photo)

    file_storage = FileStorage(
        stream=io.BytesIO(_make_image_bytes(fmt="PNG", size=(1024, 1024))),
        filename="perfil.png",
        content_type="image/png",
    )

    url = photo_service.upload_profile_photo(file_storage, "30.123.456")
    assert url == "/media/empleados/foto/30123456"
    assert captured["dni"] == "30123456"
    assert captured["mime_type"] == "image/jpeg"
    assert captured["ext"] == "jpg"
    assert captured["data_size"] <= 500000
