import io
import os
from ftplib import FTP, all_errors
from pathlib import Path

from PIL import Image, ImageOps, UnidentifiedImageError

from extensions import get_db


_ALLOWED_MIMES = {
    "image/jpeg": "jpg",
    "image/jpg": "jpg",
    "image/png": "png",
    "image/webp": "webp",
}
_ALLOWED_EXTS = ("jpg", "png", "webp")
_OUTPUT_FORMATS = {
    "jpg": ("JPEG", "image/jpeg"),
    "jpeg": ("JPEG", "image/jpeg"),
    "png": ("PNG", "image/png"),
    "webp": ("WEBP", "image/webp"),
}
_RESAMPLING_LANCZOS = (
    Image.Resampling.LANCZOS
    if hasattr(Image, "Resampling")
    else Image.LANCZOS
)


def _parse_bool_env(name: str, default: bool = True):
    raw = str(os.getenv(name, "1" if default else "0")).strip().lower()
    return raw in {"1", "true", "yes", "on"}


def _parse_int_env(name: str, default: int, minimum: int | None = None, maximum: int | None = None):
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


def _safe_dni(raw):
    digits = "".join(ch for ch in str(raw or "") if ch.isdigit())
    return digits or "empleado"


def _detect_image_ext(data: bytes):
    if not data:
        return None
    if data.startswith(b"\xff\xd8\xff"):
        return "jpg"
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png"
    if len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "webp"
    return None


def _join_url(base: str, suffix: str):
    return f"{base.rstrip('/')}/{suffix.lstrip('/')}"


def _storage_backend():
    raw = str(
        os.getenv("FOTO_STORAGE_BACKEND")
        or os.getenv("FOTO_STORAGE")
        or "local"
    ).strip().lower()
    if raw in {"local", "ftp", "db"}:
        return raw
    raise ValueError("FOTO_STORAGE_BACKEND invalido. Use 'local', 'ftp' o 'db'.")


def _project_root():
    return Path(__file__).resolve().parent.parent


def _local_config():
    local_dir = str(
        os.getenv("FOTO_LOCAL_DIR") or "static/uploads/empleados"
    ).strip()
    local_path = Path(local_dir)
    if not local_path.is_absolute():
        local_path = (_project_root() / local_path).resolve()
    public_base_url = str(os.getenv("FOTO_PUBLIC_BASE_URL") or "").strip()
    public_prefix = str(
        os.getenv("FOTO_PUBLIC_PREFIX") or "static/uploads/empleados"
    ).strip()
    return {
        "dir": local_path,
        "public_base_url": public_base_url,
        "public_prefix": public_prefix,
    }


def _db_public_base_url_or_raise():
    public_base_url = str(
        os.getenv("FOTO_PUBLIC_BASE_URL")
        or os.getenv("API_PUBLIC_BASE_URL")
        or ""
    ).strip()
    return public_base_url


def _ftp_change_dir(ftp: FTP, remote_dir: str):
    path = str(remote_dir or "").strip()
    if not path:
        return
    normalized = path.replace("\\", "/")
    if normalized.startswith("/"):
        ftp.cwd("/")
    for part in [segment for segment in normalized.split("/") if segment]:
        try:
            ftp.cwd(part)
        except all_errors:
            ftp.mkd(part)
            ftp.cwd(part)


def _ftp_config_or_raise():
    ftp_host = os.getenv("FOTO_FTP_HOST")
    ftp_user = os.getenv("FOTO_FTP_USER")
    ftp_password = os.getenv("FOTO_FTP_PASSWORD")
    ftp_dir = os.getenv("FOTO_FTP_DIR", "/htdocs/")
    public_base_url = os.getenv("FOTO_PUBLIC_BASE_URL")
    public_prefix = os.getenv("FOTO_PUBLIC_PREFIX", "")
    ftp_port = int(os.getenv("FOTO_FTP_PORT", "21"))
    ftp_timeout = float(os.getenv("FOTO_FTP_TIMEOUT", "30"))
    ftp_passive = _parse_bool_env("FOTO_FTP_PASSIVE", True)

    if not ftp_host or not ftp_user or not ftp_password or not public_base_url:
        raise ValueError(
            "Servicio de fotos no configurado. Defina FOTO_FTP_HOST, FOTO_FTP_USER, "
            "FOTO_FTP_PASSWORD y FOTO_PUBLIC_BASE_URL."
        )

    return {
        "host": ftp_host,
        "user": ftp_user,
        "password": ftp_password,
        "dir": ftp_dir,
        "public_base_url": public_base_url,
        "public_prefix": public_prefix,
        "port": ftp_port,
        "timeout": ftp_timeout,
        "passive": ftp_passive,
    }


def _ftp_connect(cfg):
    ftp = FTP()
    ftp.connect(cfg["host"], cfg["port"], timeout=cfg["timeout"])
    ftp.login(cfg["user"], cfg["password"])
    ftp.set_pasv(cfg["passive"])
    _ftp_change_dir(ftp, cfg["dir"])
    return ftp


def _cleanup_dni_variants(ftp: FTP, dni: str, keep_ext: str | None = None):
    base = _safe_dni(dni)
    keep = str(keep_ext or "").strip().lower()
    for ext in _ALLOWED_EXTS:
        if keep and ext == keep:
            continue
        filename = f"{base}.{ext}"
        try:
            ftp.delete(filename)
        except all_errors:
            # Limpieza best-effort: puede no existir el archivo.
            pass


def _cleanup_local_dni_variants(base_dir: Path, dni: str, keep_ext: str | None = None):
    base = _safe_dni(dni)
    keep = str(keep_ext or "").strip().lower()
    for ext in _ALLOWED_EXTS:
        if keep and ext == keep:
            continue
        target = base_dir / f"{base}.{ext}"
        try:
            target.unlink(missing_ok=True)
        except Exception:
            pass


def _public_url(filename: str, public_base_url: str, public_prefix: str):
    public_path = (
        f"{public_prefix.strip('/')}/{filename}"
        if public_prefix.strip("/")
        else filename
    )
    if public_base_url:
        return _join_url(public_base_url, public_path)
    return f"/{public_path.lstrip('/')}"


def _preferred_output_ext():
    output = str(os.getenv("FOTO_OUTPUT_FORMAT", "webp")).strip().lower()
    if output not in _OUTPUT_FORMATS:
        raise ValueError("FOTO_OUTPUT_FORMAT invalido. Use jpg, png o webp.")
    if output == "jpeg":
        return "jpg"
    return output


def _prepare_image_mode(image: Image.Image, output_ext: str):
    has_alpha = "A" in image.getbands()
    if output_ext == "jpg":
        if has_alpha:
            base = Image.new("RGB", image.size, (255, 255, 255))
            base.paste(image, mask=image.getchannel("A"))
            return base
        return image.convert("RGB")
    if output_ext == "png":
        return image.convert("RGBA" if has_alpha else "RGB")
    return image.convert("RGBA" if has_alpha else "RGB")


def _resize_to_limits(image: Image.Image, max_width: int, max_height: int):
    if image.width <= max_width and image.height <= max_height:
        return image.copy()
    resized = image.copy()
    resized.thumbnail((max_width, max_height), _RESAMPLING_LANCZOS)
    return resized


def _encode_image_bytes(image: Image.Image, output_ext: str, quality: int, compress_level: int):
    fmt, mime_type = _OUTPUT_FORMATS[output_ext]
    buffer = io.BytesIO()
    save_kwargs = {}
    if output_ext == "jpg":
        save_kwargs.update(
            {
                "quality": quality,
                "optimize": True,
                "progressive": True,
                "subsampling": "4:2:0",
            }
        )
    elif output_ext == "webp":
        save_kwargs.update(
            {
                "quality": quality,
                "method": 6,
                "optimize": True,
            }
        )
    elif output_ext == "png":
        save_kwargs.update(
            {
                "optimize": True,
                "compress_level": compress_level,
            }
        )
    image.save(buffer, format=fmt, **save_kwargs)
    return buffer.getvalue(), mime_type


def _normalize_profile_photo(data: bytes, output_max_bytes: int):
    output_ext = _preferred_output_ext()
    quality = _parse_int_env("FOTO_OUTPUT_QUALITY", 82, minimum=35, maximum=95)
    compress_level = _parse_int_env("FOTO_PNG_COMPRESS_LEVEL", 9, minimum=0, maximum=9)
    max_width = _parse_int_env("FOTO_MAX_WIDTH", 720, minimum=128, maximum=4000)
    max_height = _parse_int_env("FOTO_MAX_HEIGHT", 720, minimum=128, maximum=4000)

    try:
        with Image.open(io.BytesIO(data)) as opened:
            if ((opened.format or "").strip().lower() not in {"jpeg", "png", "webp"}):
                raise ValueError("Archivo invalido. No se detecta imagen JPG/PNG/WEBP.")
            transposed = ImageOps.exif_transpose(opened)
            base = _prepare_image_mode(transposed, output_ext)
    except UnidentifiedImageError as exc:
        raise ValueError("Archivo invalido. No se detecta imagen JPG/PNG/WEBP.") from exc

    image = _resize_to_limits(base, max_width, max_height)
    encoded, mime_type = _encode_image_bytes(
        image=image,
        output_ext=output_ext,
        quality=quality,
        compress_level=compress_level,
    )

    if len(encoded) <= output_max_bytes:
        return encoded, output_ext, mime_type

    if output_ext in {"jpg", "webp"}:
        current_quality = quality
        while len(encoded) > output_max_bytes and current_quality > 40:
            current_quality = max(40, current_quality - 7)
            encoded, mime_type = _encode_image_bytes(
                image=image,
                output_ext=output_ext,
                quality=current_quality,
                compress_level=compress_level,
            )
        if len(encoded) <= output_max_bytes:
            return encoded, output_ext, mime_type

    shrink_image = image
    while len(encoded) > output_max_bytes and min(shrink_image.size) > 240:
        next_size = (
            max(240, int(shrink_image.width * 0.88)),
            max(240, int(shrink_image.height * 0.88)),
        )
        if next_size == shrink_image.size:
            break
        shrink_image = shrink_image.resize(next_size, _RESAMPLING_LANCZOS)
        encoded, mime_type = _encode_image_bytes(
            image=shrink_image,
            output_ext=output_ext,
            quality=40 if output_ext in {"jpg", "webp"} else quality,
            compress_level=compress_level,
        )
    if len(encoded) > output_max_bytes:
        raise ValueError(
            f"La imagen excede el maximo permitido de {output_max_bytes} bytes luego de optimizar."
        )
    return encoded, output_ext, mime_type


def _ensure_db_photo_table(cursor):
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS empleado_fotos (
            dni VARCHAR(32) NOT NULL PRIMARY KEY,
            mime_type VARCHAR(32) NOT NULL,
            ext VARCHAR(8) NOT NULL,
            data LONGBLOB NOT NULL,
            updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """
    )


def _db_upsert_photo(dni: str, mime_type: str, ext: str, data: bytes):
    db = get_db()
    cursor = db.cursor()
    try:
        _ensure_db_photo_table(cursor)
        cursor.execute(
            """
            INSERT INTO empleado_fotos (dni, mime_type, ext, data)
            VALUES (%s, %s, %s, %s)
            ON DUPLICATE KEY UPDATE
                mime_type = VALUES(mime_type),
                ext = VALUES(ext),
                data = VALUES(data)
            """,
            (dni, mime_type, ext, data),
        )
        db.commit()
        return True
    finally:
        cursor.close()
        db.close()


def _db_delete_photo(dni: str):
    db = get_db()
    cursor = db.cursor()
    try:
        _ensure_db_photo_table(cursor)
        cursor.execute("DELETE FROM empleado_fotos WHERE dni = %s", (dni,))
        db.commit()
        return True
    finally:
        cursor.close()
        db.close()


def get_profile_photo_bytes_by_dni(dni: str | None):
    safe_dni = _safe_dni(dni)
    if not safe_dni or safe_dni == "empleado":
        return None

    db = get_db()
    cursor = db.cursor(dictionary=True)
    try:
        _ensure_db_photo_table(cursor)
        cursor.execute(
            """
            SELECT mime_type, ext, data, updated_at
            FROM empleado_fotos
            WHERE dni = %s
            """,
            (safe_dni,),
        )
        row = cursor.fetchone()
        if not row:
            return None
        return {
            "mime_type": row.get("mime_type") or "application/octet-stream",
            "ext": row.get("ext"),
            "data": row.get("data"),
            "updated_at": row.get("updated_at"),
        }
    finally:
        cursor.close()
        db.close()


def upload_profile_photo(file_storage, dni: str | None):
    if not file_storage:
        raise ValueError("foto_file requerido.")

    data = file_storage.read() or b""
    try:
        file_storage.stream.seek(0)
    except Exception:
        pass

    if not data:
        raise ValueError("La imagen esta vacia.")

    max_bytes = _parse_int_env("FOTO_MAX_BYTES", 5242880, minimum=65536, maximum=52428800)
    input_max_default = max(10485760, max_bytes * 2)
    input_max_bytes = _parse_int_env(
        "FOTO_INPUT_MAX_BYTES",
        input_max_default,
        minimum=max_bytes,
        maximum=104857600,
    )
    if len(data) > input_max_bytes:
        raise ValueError(f"La imagen supera el maximo permitido de entrada de {input_max_bytes} bytes.")

    mimetype = str(getattr(file_storage, "mimetype", "") or "").strip().lower()
    if mimetype and mimetype not in _ALLOWED_MIMES and mimetype != "application/octet-stream":
        raise ValueError("Tipo de imagen no permitido. Use JPG, PNG o WEBP.")

    if mimetype in _ALLOWED_MIMES:
        detected_ext = _detect_image_ext(data)
        expected_ext = _ALLOWED_MIMES.get(mimetype)
        if detected_ext and expected_ext and expected_ext != detected_ext:
            raise ValueError("La extension de imagen no coincide con el contenido del archivo.")

    optimized_data, detected_ext, detected_mime = _normalize_profile_photo(
        data=data,
        output_max_bytes=max_bytes,
    )

    if mimetype in _ALLOWED_MIMES and mimetype != detected_mime:
        # Permitimos solo si el mimetype difiere porque normalizamos el archivo.
        pass

    if detected_ext not in _ALLOWED_EXTS:
        raise ValueError("La extension de imagen no coincide con el contenido del archivo.")

    filename = f"{_safe_dni(dni)}.{detected_ext}"
    safe_dni = _safe_dni(dni)
    backend = _storage_backend()

    if backend == "ftp":
        cfg = _ftp_config_or_raise()
        ftp = None
        try:
            ftp = _ftp_connect(cfg)
            _cleanup_dni_variants(ftp, dni or "", keep_ext=detected_ext)
            ftp.storbinary(f"STOR {filename}", io.BytesIO(optimized_data))
            ftp.quit()
        except all_errors as exc:
            try:
                if ftp is not None:
                    ftp.close()
            except Exception:
                pass
            raise RuntimeError("No se pudo subir la imagen al servidor FTP.") from exc
        return _public_url(filename, cfg["public_base_url"], cfg["public_prefix"])

    if backend == "db":
        try:
            _db_upsert_photo(
                dni=safe_dni,
                mime_type=detected_mime,
                ext=detected_ext,
                data=optimized_data,
            )
        except Exception as exc:
            raise RuntimeError("No se pudo guardar la imagen en base de datos.") from exc
        public_base = _db_public_base_url_or_raise()
        path = f"/media/empleados/foto/{safe_dni}"
        if public_base:
            return _join_url(public_base, path)
        return path

    cfg = _local_config()
    base_dir: Path = cfg["dir"]
    try:
        base_dir.mkdir(parents=True, exist_ok=True)
        _cleanup_local_dni_variants(base_dir, dni or "", keep_ext=detected_ext)
        target = base_dir / filename
        tmp_target = base_dir / f"{filename}.tmp"
        tmp_target.write_bytes(optimized_data)
        tmp_target.replace(target)
    except Exception as exc:
        raise RuntimeError("No se pudo guardar la imagen localmente.") from exc
    return _public_url(filename, cfg["public_base_url"], cfg["public_prefix"])


def delete_profile_photo_for_dni(dni: str | None):
    backend = _storage_backend()
    if backend == "ftp":
        cfg = _ftp_config_or_raise()
        ftp = None
        try:
            ftp = _ftp_connect(cfg)
            _cleanup_dni_variants(ftp, dni or "", keep_ext=None)
            ftp.quit()
            return True
        except all_errors as exc:
            try:
                if ftp is not None:
                    ftp.close()
            except Exception:
                pass
            raise RuntimeError("No se pudo eliminar la imagen del servidor FTP.") from exc

    if backend == "db":
        try:
            _db_delete_photo(_safe_dni(dni))
            return True
        except Exception as exc:
            raise RuntimeError("No se pudo eliminar la imagen de base de datos.") from exc

    cfg = _local_config()
    base_dir: Path = cfg["dir"]
    try:
        if not base_dir.exists():
            return True
        _cleanup_local_dni_variants(base_dir, dni or "", keep_ext=None)
        return True
    except Exception as exc:
        raise RuntimeError("No se pudo eliminar la imagen localmente.") from exc
