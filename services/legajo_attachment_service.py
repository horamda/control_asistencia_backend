import hashlib
import io
import os
import uuid
from pathlib import Path

from PIL import Image, ImageOps, UnidentifiedImageError
from werkzeug.datastructures import FileStorage
from werkzeug.utils import secure_filename


_ALLOWED_MIMES = {
    "image/jpeg": "jpg",
    "image/jpg": "jpg",
    "image/png": "png",
    "image/webp": "webp",
    "application/pdf": "pdf",
}
_RESAMPLING_LANCZOS = (
    Image.Resampling.LANCZOS
    if hasattr(Image, "Resampling")
    else Image.LANCZOS
)


def _project_root() -> Path:
    return Path(__file__).resolve().parent.parent


def _parse_int_env(name: str, default: int, minimum: int | None = None, maximum: int | None = None) -> int:
    raw = str(os.getenv(name, str(default))).strip()
    try:
        value = int(raw)
    except (TypeError, ValueError):
        value = int(default)
    if minimum is not None and value < minimum:
        value = minimum
    if maximum is not None and value > maximum:
        value = maximum
    return value


def _parse_bool_env(name: str, default: bool = True) -> bool:
    raw = str(os.getenv(name, "1" if default else "0")).strip().lower()
    return raw in {"1", "true", "yes", "on"}


def _storage_backend() -> str:
    raw = str(os.getenv("LEGAJO_STORAGE_BACKEND") or "db").strip().lower()
    if raw not in {"db", "local"}:
        raise ValueError("LEGAJO_STORAGE_BACKEND invalido. Use 'db' o 'local'.")
    return raw


def _local_base_dir() -> Path:
    raw = str(os.getenv("LEGAJO_LOCAL_DIR") or "uploads/legajos").strip()
    base = Path(raw)
    if not base.is_absolute():
        base = (_project_root() / base).resolve()
    return base


def _relative_storage_path(path: Path) -> str:
    root = _project_root()
    try:
        rel = path.resolve().relative_to(root)
        return str(rel).replace("\\", "/")
    except Exception:
        return str(path.resolve()).replace("\\", "/")


def _ensure_inside_base(path: Path, base: Path) -> Path:
    resolved = path.resolve()
    if resolved != base.resolve() and base.resolve() not in resolved.parents:
        raise RuntimeError("Ruta de adjunto invalida.")
    return resolved


def _ext_from_filename(filename: str | None) -> str | None:
    raw = str(filename or "").strip()
    if "." not in raw:
        return None
    ext = raw.rsplit(".", 1)[-1].lower()
    return ext or None


def _detect_pdf(data: bytes) -> bool:
    return data.startswith(b"%PDF-")


def _normalize_pdf_name(filename: str | None) -> str:
    original = secure_filename(str(filename or "").strip())
    if not original:
        return "adjunto.pdf"
    if "." in original:
        original = original.rsplit(".", 1)[0]
    return f"{original or 'adjunto'}.pdf"


def _prepare_image_for_pdf(image: Image.Image) -> Image.Image:
    has_alpha = "A" in image.getbands()
    if has_alpha:
        base = Image.new("RGB", image.size, (255, 255, 255))
        base.paste(image, mask=image.getchannel("A"))
        return base
    return image.convert("RGB")


def _resize_to_limits(image: Image.Image, max_width: int, max_height: int) -> Image.Image:
    if image.width <= max_width and image.height <= max_height:
        return image.copy()
    resized = image.copy()
    resized.thumbnail((max_width, max_height), _RESAMPLING_LANCZOS)
    return resized


def _encode_pdf_from_image(image: Image.Image, quality: int) -> bytes:
    buffer = io.BytesIO()
    image.save(
        buffer,
        format="PDF",
        quality=quality,
        optimize=True,
    )
    return buffer.getvalue()


def _optimize_image_to_pdf(data: bytes, output_max_bytes: int) -> bytes:
    max_width = _parse_int_env("LEGAJO_PDF_MAX_WIDTH", 2000, minimum=600, maximum=5000)
    max_height = _parse_int_env("LEGAJO_PDF_MAX_HEIGHT", 2000, minimum=600, maximum=5000)
    quality = _parse_int_env("LEGAJO_PDF_IMAGE_QUALITY", 88, minimum=60, maximum=95)
    min_quality = _parse_int_env("LEGAJO_PDF_IMAGE_MIN_QUALITY", 72, minimum=50, maximum=95)
    min_side = _parse_int_env("LEGAJO_PDF_MIN_SIDE", 800, minimum=300, maximum=2500)
    resize_enabled = _parse_bool_env("LEGAJO_PDF_RESIZE", True)

    try:
        with Image.open(io.BytesIO(data)) as opened:
            if (opened.format or "").strip().lower() not in {"jpeg", "png", "webp"}:
                raise ValueError("Adjunto invalido. Solo se admiten imagenes JPG/PNG/WEBP o PDF.")
            transposed = ImageOps.exif_transpose(opened)
            base = _prepare_image_for_pdf(transposed)
    except UnidentifiedImageError as exc:
        raise ValueError("Adjunto invalido. Solo se admiten imagenes JPG/PNG/WEBP o PDF.") from exc

    image = _resize_to_limits(base, max_width, max_height) if resize_enabled else base.copy()
    encoded = _encode_pdf_from_image(image, quality=quality)

    current_quality = quality
    while len(encoded) > output_max_bytes and current_quality > min_quality:
        current_quality = max(min_quality, current_quality - 4)
        encoded = _encode_pdf_from_image(image, quality=current_quality)

    shrink_image = image
    while len(encoded) > output_max_bytes and min(shrink_image.size) > min_side:
        next_size = (
            max(min_side, int(shrink_image.width * 0.9)),
            max(min_side, int(shrink_image.height * 0.9)),
        )
        if next_size == shrink_image.size:
            break
        shrink_image = shrink_image.resize(next_size, _RESAMPLING_LANCZOS)
        encoded = _encode_pdf_from_image(shrink_image, quality=min_quality)

    if len(encoded) > output_max_bytes:
        raise ValueError(
            f"El PDF optimizado supera el maximo permitido de {output_max_bytes} bytes."
        )
    return encoded


def _normalize_to_pdf_bytes(data: bytes, mime_type: str, output_max_bytes: int) -> bytes:
    mime = str(mime_type or "").strip().lower()
    if mime == "application/pdf":
        if not _detect_pdf(data):
            raise ValueError("Archivo PDF invalido.")
        if len(data) > output_max_bytes:
            raise ValueError(
                f"El PDF supera el maximo permitido de {output_max_bytes} bytes."
            )
        return data
    return _optimize_image_to_pdf(data, output_max_bytes=output_max_bytes)


def save_legajo_attachment_local(
    file_storage: FileStorage,
    *,
    empresa_id: int,
    empleado_id: int,
    evento_id: int,
):
    if not file_storage or not str(file_storage.filename or "").strip():
        raise ValueError("Adjunto requerido.")

    input_max_bytes = _parse_int_env("LEGAJO_INPUT_MAX_BYTES", 15728640, minimum=262144, maximum=104857600)
    output_max_bytes = _parse_int_env("LEGAJO_MAX_BYTES", 2097152, minimum=262144, maximum=52428800)
    data = file_storage.read() or b""
    try:
        file_storage.stream.seek(0)
    except Exception:
        pass

    if not data:
        raise ValueError("El adjunto esta vacio.")
    if len(data) > input_max_bytes:
        raise ValueError(f"El adjunto supera el maximo permitido de entrada de {input_max_bytes} bytes.")

    mime_type = str(getattr(file_storage, "mimetype", "") or "").strip().lower()
    if not mime_type or mime_type == "application/octet-stream":
        guessed_ext = _ext_from_filename(file_storage.filename)
        for allowed_mime, allowed_ext in _ALLOWED_MIMES.items():
            if guessed_ext == allowed_ext:
                mime_type = allowed_mime
                break
    if mime_type not in _ALLOWED_MIMES:
        raise ValueError("Tipo de archivo no permitido. Use JPG, PNG, WEBP o PDF.")

    pdf_data = _normalize_to_pdf_bytes(data, mime_type=mime_type, output_max_bytes=output_max_bytes)
    output_name = _normalize_pdf_name(file_storage.filename)
    sha256 = hashlib.sha256(pdf_data).hexdigest()
    backend = _storage_backend()

    if backend == "db":
        return {
            "nombre_original": output_name,
            "mime_type": "application/pdf",
            "extension": "pdf",
            "tamano_bytes": len(pdf_data),
            "sha256": sha256,
            "storage_backend": "db",
            "storage_ruta": f"db://legajos/{sha256[:16]}.pdf",
            "storage_data": pdf_data,
        }

    base_dir = _local_base_dir()
    folder = base_dir / f"empresa_{int(empresa_id)}" / f"empleado_{int(empleado_id)}" / f"evento_{int(evento_id)}"
    folder.mkdir(parents=True, exist_ok=True)
    folder = _ensure_inside_base(folder, base_dir)

    filename = f"{uuid.uuid4().hex}.pdf"
    target = folder / filename
    tmp_target = folder / f"{filename}.tmp"
    tmp_target.write_bytes(pdf_data)
    tmp_target.replace(target)

    storage_ruta = _relative_storage_path(target)
    return {
        "nombre_original": output_name,
        "mime_type": "application/pdf",
        "extension": "pdf",
        "tamano_bytes": len(pdf_data),
        "sha256": sha256,
        "storage_backend": "local",
        "storage_ruta": storage_ruta,
    }


def resolve_legajo_storage_path(storage_ruta: str) -> Path:
    root = _project_root().resolve()
    raw = str(storage_ruta or "").strip().replace("\\", "/")
    if not raw:
        raise RuntimeError("Ruta de almacenamiento vacia.")

    candidate = Path(raw)
    if not candidate.is_absolute():
        candidate = (root / candidate).resolve()
    else:
        candidate = candidate.resolve()

    if candidate != root and root not in candidate.parents:
        raise RuntimeError("Ruta de almacenamiento fuera del proyecto.")
    return candidate
