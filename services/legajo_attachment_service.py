import hashlib
import os
import uuid
from pathlib import Path

from werkzeug.datastructures import FileStorage
from werkzeug.utils import secure_filename


_ALLOWED_MIMES = {
    "image/jpeg": "jpg",
    "image/jpg": "jpg",
    "image/png": "png",
    "image/webp": "webp",
    "application/pdf": "pdf",
}


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


def save_legajo_attachment_local(
    file_storage: FileStorage,
    *,
    empresa_id: int,
    empleado_id: int,
    evento_id: int,
):
    if not file_storage or not str(file_storage.filename or "").strip():
        raise ValueError("Adjunto requerido.")

    input_max_bytes = _parse_int_env("LEGAJO_INPUT_MAX_BYTES", 10485760, minimum=262144, maximum=104857600)
    data = file_storage.read() or b""
    try:
        file_storage.stream.seek(0)
    except Exception:
        pass

    if not data:
        raise ValueError("El adjunto esta vacio.")
    if len(data) > input_max_bytes:
        raise ValueError(f"El adjunto supera el maximo permitido de {input_max_bytes} bytes.")

    mime_type = str(getattr(file_storage, "mimetype", "") or "").strip().lower()
    if not mime_type or mime_type == "application/octet-stream":
        guessed_ext = _ext_from_filename(file_storage.filename)
        for allowed_mime, allowed_ext in _ALLOWED_MIMES.items():
            if guessed_ext == allowed_ext:
                mime_type = allowed_mime
                break
    if mime_type not in _ALLOWED_MIMES:
        raise ValueError("Tipo de archivo no permitido. Use JPG, PNG, WEBP o PDF.")

    extension = _ALLOWED_MIMES[mime_type]
    original_name = secure_filename(str(file_storage.filename or "").strip()) or f"adjunto.{extension}"

    base_dir = _local_base_dir()
    folder = base_dir / f"empresa_{int(empresa_id)}" / f"empleado_{int(empleado_id)}" / f"evento_{int(evento_id)}"
    folder.mkdir(parents=True, exist_ok=True)
    folder = _ensure_inside_base(folder, base_dir)

    filename = f"{uuid.uuid4().hex}.{extension}"
    target = folder / filename
    tmp_target = folder / f"{filename}.tmp"
    tmp_target.write_bytes(data)
    tmp_target.replace(target)

    sha256 = hashlib.sha256(data).hexdigest()
    storage_ruta = _relative_storage_path(target)

    return {
        "nombre_original": original_name,
        "mime_type": mime_type,
        "extension": extension,
        "tamano_bytes": len(data),
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
