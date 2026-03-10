import io

import pytest
from PIL import Image
from werkzeug.datastructures import FileStorage

import services.legajo_attachment_service as attachment_service


def _make_image_bytes(fmt: str = "PNG", size=(1600, 1200), color=(20, 120, 220)):
    image = Image.new("RGB", size, color=color)
    buffer = io.BytesIO()
    image.save(buffer, format=fmt)
    return buffer.getvalue()


def test_save_legajo_attachment_db_converts_image_to_pdf(monkeypatch):
    monkeypatch.setenv("LEGAJO_STORAGE_BACKEND", "db")
    monkeypatch.setenv("LEGAJO_INPUT_MAX_BYTES", "15728640")
    monkeypatch.setenv("LEGAJO_MAX_BYTES", "2097152")
    monkeypatch.setenv("LEGAJO_PDF_MAX_WIDTH", "1600")
    monkeypatch.setenv("LEGAJO_PDF_MAX_HEIGHT", "1600")
    monkeypatch.setenv("LEGAJO_PDF_IMAGE_QUALITY", "88")
    monkeypatch.setenv("LEGAJO_PDF_IMAGE_MIN_QUALITY", "72")

    file_storage = FileStorage(
        stream=io.BytesIO(_make_image_bytes(fmt="PNG", size=(2200, 1400))),
        filename="certificado.png",
        content_type="image/png",
    )

    saved = attachment_service.save_legajo_attachment_local(
        file_storage,
        empresa_id=1,
        empleado_id=7,
        evento_id=44,
    )

    assert saved["storage_backend"] == "db"
    assert saved["mime_type"] == "application/pdf"
    assert saved["extension"] == "pdf"
    assert saved["nombre_original"].endswith(".pdf")
    assert saved["tamano_bytes"] == len(saved["storage_data"])
    assert saved["storage_data"].startswith(b"%PDF-")
    assert saved["tamano_bytes"] <= 2097152


def test_save_legajo_attachment_pdf_rejects_oversize(monkeypatch):
    monkeypatch.setenv("LEGAJO_STORAGE_BACKEND", "db")
    monkeypatch.setenv("LEGAJO_INPUT_MAX_BYTES", "15728640")
    monkeypatch.setenv("LEGAJO_MAX_BYTES", "262144")

    oversized_pdf = b"%PDF-1.4\n" + (b"0" * 300000)
    file_storage = FileStorage(
        stream=io.BytesIO(oversized_pdf),
        filename="documento.pdf",
        content_type="application/pdf",
    )

    with pytest.raises(ValueError) as exc:
        attachment_service.save_legajo_attachment_local(
            file_storage,
            empresa_id=1,
            empleado_id=7,
            evento_id=44,
        )
    assert "maximo permitido" in str(exc.value)
