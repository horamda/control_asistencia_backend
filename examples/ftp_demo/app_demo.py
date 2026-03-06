import io
import os
import sqlite3
import uuid
from datetime import datetime
from ftplib import FTP, all_errors
from pathlib import Path

from dotenv import load_dotenv
from flask import Flask, Response, abort, redirect, render_template_string, request, url_for
from werkzeug.utils import secure_filename

load_dotenv()

app = Flask(__name__)
ROOT = Path(__file__).resolve().parent

ALLOWED_EXTENSIONS = {"jpg", "jpeg", "png", "webp", "pdf"}
ALLOWED_MIMES = {
    "image/jpeg",
    "image/png",
    "image/webp",
    "application/pdf",
}

DB_PATH = ROOT / (os.getenv("DEMO_DB_PATH") or "demo_ftp.sqlite3")


def _parse_bool(raw: str | None, default: bool = True) -> bool:
    value = str(raw or ("1" if default else "0")).strip().lower()
    return value in {"1", "true", "yes", "on"}


def _cfg():
    host = os.getenv("DEMO_FTP_HOST")
    user = os.getenv("DEMO_FTP_USER")
    password = os.getenv("DEMO_FTP_PASSWORD")
    if not host or not user or not password:
        raise RuntimeError("Faltan credenciales FTP del demo. Revise .env")
    return {
        "host": host,
        "port": int(os.getenv("DEMO_FTP_PORT", "21")),
        "user": user,
        "password": password,
        "timeout": float(os.getenv("DEMO_FTP_TIMEOUT", "30")),
        "passive": _parse_bool(os.getenv("DEMO_FTP_PASSIVE"), True),
        "public_base_url": str(os.getenv("DEMO_PUBLIC_BASE_URL") or "").strip(),
        "public_dir": str(os.getenv("DEMO_FTP_PUBLIC_DIR") or "/htdocs/uploads/demo/public").strip(),
        "private_dir": str(os.getenv("DEMO_FTP_PRIVATE_DIR") or "/htdocs/uploads/demo/private").strip(),
        "private_key": str(os.getenv("DEMO_PRIVATE_KEY") or "").strip(),
    }


def _init_db():
    con = sqlite3.connect(DB_PATH)
    try:
        cur = con.cursor()
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS private_files (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              original_name TEXT NOT NULL,
              mime_type TEXT NOT NULL,
              remote_path TEXT NOT NULL,
              created_at TEXT NOT NULL
            )
            """
        )
        con.commit()
    finally:
        con.close()


def _ftp_connect():
    cfg = _cfg()
    ftp = FTP()
    ftp.connect(cfg["host"], cfg["port"], timeout=cfg["timeout"])
    ftp.login(cfg["user"], cfg["password"])
    ftp.set_pasv(cfg["passive"])
    return ftp


def _ftp_mkdirs(ftp: FTP, remote_dir: str):
    normalized = str(remote_dir or "").replace("\\", "/").strip()
    if not normalized:
        return
    if normalized.startswith("/"):
        ftp.cwd("/")
    for part in [segment for segment in normalized.split("/") if segment]:
        try:
            ftp.cwd(part)
        except all_errors:
            ftp.mkd(part)
            ftp.cwd(part)


def _upload_to_ftp(remote_dir: str, filename: str, payload: bytes):
    ftp = None
    try:
        ftp = _ftp_connect()
        _ftp_mkdirs(ftp, remote_dir)
        ftp.storbinary(f"STOR {filename}", io.BytesIO(payload))
        ftp.quit()
    except all_errors as exc:
        if ftp is not None:
            try:
                ftp.close()
            except Exception:
                pass
        raise RuntimeError(f"Error FTP al subir archivo: {exc}") from exc


def _download_from_ftp(remote_path: str):
    normalized = str(remote_path or "").replace("\\", "/").strip()
    if not normalized or "/" not in normalized:
        raise RuntimeError("Ruta remota invalida.")
    remote_dir, filename = normalized.rsplit("/", 1)

    ftp = None
    buffer = io.BytesIO()
    try:
        ftp = _ftp_connect()
        _ftp_mkdirs(ftp, remote_dir)
        ftp.retrbinary(f"RETR {filename}", buffer.write)
        ftp.quit()
    except all_errors as exc:
        if ftp is not None:
            try:
                ftp.close()
            except Exception:
                pass
        raise RuntimeError(f"Error FTP al descargar archivo: {exc}") from exc
    return buffer.getvalue()


def _allowed(file_storage) -> tuple[bool, str]:
    filename = secure_filename(str(file_storage.filename or "").strip())
    if not filename or "." not in filename:
        return False, "Nombre de archivo invalido."
    ext = filename.rsplit(".", 1)[-1].lower()
    if ext not in ALLOWED_EXTENSIONS:
        return False, "Extension no permitida."
    mime = str(getattr(file_storage, "mimetype", "") or "").lower().strip()
    if mime and mime not in ALLOWED_MIMES and mime != "application/octet-stream":
        return False, "MIME no permitido."
    return True, filename


def _join_url(base: str, path: str) -> str:
    return f"{base.rstrip('/')}/{path.lstrip('/')}"


def _save_private_metadata(original_name: str, mime_type: str, remote_path: str) -> int:
    con = sqlite3.connect(DB_PATH)
    try:
        cur = con.cursor()
        cur.execute(
            """
            INSERT INTO private_files (original_name, mime_type, remote_path, created_at)
            VALUES (?, ?, ?, ?)
            """,
            (original_name, mime_type, remote_path, datetime.utcnow().isoformat()),
        )
        con.commit()
        return int(cur.lastrowid)
    finally:
        con.close()


def _get_private_metadata(file_id: int):
    con = sqlite3.connect(DB_PATH)
    try:
        cur = con.cursor()
        cur.execute(
            """
            SELECT id, original_name, mime_type, remote_path, created_at
            FROM private_files
            WHERE id = ?
            """,
            (file_id,),
        )
        row = cur.fetchone()
        if not row:
            return None
        return {
            "id": row[0],
            "original_name": row[1],
            "mime_type": row[2],
            "remote_path": row[3],
            "created_at": row[4],
        }
    finally:
        con.close()


def _list_private_metadata(limit: int = 20):
    con = sqlite3.connect(DB_PATH)
    try:
        cur = con.cursor()
        cur.execute(
            """
            SELECT id, original_name, mime_type, remote_path, created_at
            FROM private_files
            ORDER BY id DESC
            LIMIT ?
            """,
            (limit,),
        )
        rows = cur.fetchall()
        return [
            {
                "id": row[0],
                "original_name": row[1],
                "mime_type": row[2],
                "remote_path": row[3],
                "created_at": row[4],
            }
            for row in rows
        ]
    finally:
        con.close()


@app.route("/", methods=["GET"])
def index():
    cfg = _cfg()
    items = _list_private_metadata(limit=30)
    return render_template_string(
        """
<!doctype html>
<html lang="es">
  <head>
    <meta charset="utf-8">
    <title>Demo FTP Media</title>
    <style>
      body { font-family: Arial, sans-serif; margin: 24px; max-width: 980px; }
      .card { border: 1px solid #d0d7de; border-radius: 8px; padding: 16px; margin-bottom: 16px; }
      .ok { color: #0a7f3f; }
      .mono { font-family: Consolas, monospace; font-size: 12px; }
      table { border-collapse: collapse; width: 100%; margin-top: 8px; }
      th, td { border: 1px solid #ddd; padding: 8px; text-align: left; }
    </style>
  </head>
  <body>
    <h1>Demo FTP + Media</h1>
    <p class="ok">Este demo es aislado. No usa rutas del proyecto principal.</p>

    <div class="card">
      <h3>1) Subir archivo publico (URL directa)</h3>
      <form action="{{ url_for('upload_public') }}" method="post" enctype="multipart/form-data">
        <input type="file" name="file" required>
        <button type="submit">Subir publico</button>
      </form>
      <p class="mono">Directorio FTP: {{ cfg.public_dir }}</p>
    </div>

    <div class="card">
      <h3>2) Subir archivo privado (solo backend)</h3>
      <form action="{{ url_for('upload_private') }}" method="post" enctype="multipart/form-data">
        <input type="file" name="file" required>
        <button type="submit">Subir privado</button>
      </form>
      <p class="mono">Directorio FTP: {{ cfg.private_dir }}</p>
      <p class="mono">Clave de descarga privada (query ?key=...): {{ cfg.private_key or '(no definida)' }}</p>
    </div>

    <div class="card">
      <h3>Archivos privados cargados</h3>
      {% if items %}
      <table>
        <tr>
          <th>ID</th><th>Nombre</th><th>MIME</th><th>Descarga segura</th><th>Creado</th>
        </tr>
        {% for it in items %}
        <tr>
          <td>{{ it.id }}</td>
          <td>{{ it.original_name }}</td>
          <td>{{ it.mime_type }}</td>
          <td>
            <a target="_blank" href="{{ url_for('media_private', file_id=it.id) }}?key={{ cfg.private_key }}">Abrir por backend</a>
          </td>
          <td>{{ it.created_at }}</td>
        </tr>
        {% endfor %}
      </table>
      {% else %}
      <p>No hay archivos privados cargados.</p>
      {% endif %}
    </div>
  </body>
</html>
        """,
        cfg=cfg,
        items=items,
    )


@app.route("/upload/public", methods=["POST"])
def upload_public():
    file_storage = request.files.get("file")
    if not file_storage:
        abort(400, "Archivo requerido.")
    ok, info = _allowed(file_storage)
    if not ok:
        abort(400, info)
    filename_clean = info

    payload = file_storage.read() or b""
    if not payload:
        abort(400, "Archivo vacio.")

    cfg = _cfg()
    unique_name = f"{uuid.uuid4().hex}_{filename_clean}"
    _upload_to_ftp(cfg["public_dir"], unique_name, payload)

    rel_path = f"{cfg['public_dir'].strip('/').replace('htdocs/', '')}/{unique_name}"
    public_url = _join_url(cfg["public_base_url"], rel_path)
    return render_template_string(
        """
        <h3>Archivo publico subido</h3>
        <p><a href="{{ public_url }}" target="_blank">{{ public_url }}</a></p>
        <p><a href="{{ url_for('index') }}">Volver</a></p>
        """,
        public_url=public_url,
    )


@app.route("/upload/private", methods=["POST"])
def upload_private():
    file_storage = request.files.get("file")
    if not file_storage:
        abort(400, "Archivo requerido.")
    ok, info = _allowed(file_storage)
    if not ok:
        abort(400, info)
    filename_clean = info

    payload = file_storage.read() or b""
    if not payload:
        abort(400, "Archivo vacio.")

    cfg = _cfg()
    unique_name = f"{uuid.uuid4().hex}_{filename_clean}"
    _upload_to_ftp(cfg["private_dir"], unique_name, payload)

    remote_path = f"{cfg['private_dir'].rstrip('/')}/{unique_name}"
    mime_type = str(getattr(file_storage, "mimetype", "") or "application/octet-stream").strip()
    file_id = _save_private_metadata(
        original_name=filename_clean,
        mime_type=mime_type or "application/octet-stream",
        remote_path=remote_path,
    )
    return redirect(url_for("index", created=file_id))


@app.route("/media/private/<int:file_id>", methods=["GET"])
def media_private(file_id: int):
    cfg = _cfg()
    if not cfg["private_key"]:
        abort(500, "DEMO_PRIVATE_KEY no configurada.")
    if request.args.get("key") != cfg["private_key"]:
        abort(403, "Clave invalida.")

    item = _get_private_metadata(file_id)
    if not item:
        abort(404)

    payload = _download_from_ftp(item["remote_path"])
    response = Response(payload, mimetype=item["mime_type"] or "application/octet-stream")
    response.headers["Content-Disposition"] = f'inline; filename="{item["original_name"]}"'
    response.headers["Cache-Control"] = "private, max-age=0, no-store"
    return response


if __name__ == "__main__":
    _init_db()
    app.run(host="127.0.0.1", port=5055, debug=True)
