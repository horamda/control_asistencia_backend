"""Extracción de texto para el generador con IA: texto pegado, PDF, DOCX y TXT.

Todo archivo se trata como no confiable: se valida la firma real contra la extensión, el tamaño,
y solo se lee texto (no se ejecutan macros ni contenido activo). Un PDF escaneado, sin texto
seleccionable, se devuelve como bytes para que lo lea directamente el modelo de IA.
"""

import io
import re
import zipfile
from dataclasses import dataclass

MIN_CARACTERES = 200
MAX_PAGINAS_PDF = 300
MAX_PAGINAS_PDF_ESCANEADO = 100
_MAX_DOCX_DESCOMPRIMIDO = 100 * 1024 * 1024
_MAX_DOCX_ENTRADAS = 3000

EXTENSIONES = ("pdf", "docx", "txt")


class DocumentoError(ValueError):
    pass


@dataclass
class Contenido:
    texto: str
    origen: str                 # texto | pdf | pdf_escaneado | docx | txt
    pdf: bytes | None = None    # solo para PDF escaneado


def _limpiar(texto: str) -> str:
    texto = (texto or "").replace("\r\n", "\n").replace("\r", "\n")
    texto = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", "", texto)
    texto = re.sub(r"[ \t]+", " ", texto)
    texto = re.sub(r"\n{3,}", "\n\n", texto)
    return texto.strip()


def _validar_largo(texto: str, max_caracteres: int) -> str:
    if len(texto) < MIN_CARACTERES:
        raise DocumentoError(
            f"El contenido es demasiado corto para generar preguntas (mínimo {MIN_CARACTERES} caracteres).")
    if len(texto) > max_caracteres:
        raise DocumentoError(
            f"El contenido tiene {len(texto):,} caracteres y el máximo permitido es {max_caracteres:,}. "
            "Dividilo o cargá solo la parte que querés evaluar.".replace(",", "."))
    return texto


def desde_texto(texto: str, max_caracteres: int) -> Contenido:
    return Contenido(_validar_largo(_limpiar(texto), max_caracteres), "texto")


def _pdf(data: bytes, max_caracteres: int) -> Contenido:
    if b"%PDF-" not in data[:1024]:
        raise DocumentoError("El archivo no es un PDF válido.")
    try:
        from pypdf import PdfReader

        reader = PdfReader(io.BytesIO(data))
        if reader.is_encrypted and not reader.decrypt(""):
            raise DocumentoError("El PDF está protegido con contraseña.")
        paginas = len(reader.pages)
        if paginas == 0:
            raise DocumentoError("El PDF no tiene páginas.")
        if paginas > MAX_PAGINAS_PDF:
            raise DocumentoError(f"El PDF tiene {paginas} páginas; el máximo es {MAX_PAGINAS_PDF}.")
        texto = _limpiar("\n\n".join((p.extract_text() or "") for p in reader.pages))
    except DocumentoError:
        raise
    except Exception as exc:
        raise DocumentoError("No se pudo leer el PDF: el archivo está dañado o no es compatible.") from exc
    if len(texto) < MIN_CARACTERES:
        if paginas > MAX_PAGINAS_PDF_ESCANEADO:
            raise DocumentoError(
                f"El PDF es escaneado y tiene {paginas} páginas; el máximo para escaneados es "
                f"{MAX_PAGINAS_PDF_ESCANEADO}.")
        return Contenido("", "pdf_escaneado", pdf=data)
    return Contenido(_validar_largo(texto, max_caracteres), "pdf")


def _docx(data: bytes, max_caracteres: int) -> Contenido:
    if not data.startswith(b"PK\x03\x04"):
        raise DocumentoError("El archivo no es un documento Word (.docx) válido.")
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            infos = zf.infolist()
            if "word/document.xml" not in zf.namelist():
                raise DocumentoError("El archivo no es un documento Word (.docx) válido.")
            if len(infos) > _MAX_DOCX_ENTRADAS or sum(i.file_size for i in infos) > _MAX_DOCX_DESCOMPRIMIDO:
                raise DocumentoError("El documento Word es demasiado grande para procesarlo.")
        from docx import Document
        from docx.table import Table

        doc = Document(io.BytesIO(data))
        partes = []
        for bloque in doc.iter_inner_content():
            if isinstance(bloque, Table):
                for fila in bloque.rows:
                    celdas = [c.text.strip() for c in fila.cells]
                    partes.append(" | ".join(dict.fromkeys(c for c in celdas if c)))
            else:
                partes.append(bloque.text)
        texto = _limpiar("\n".join(partes))
    except DocumentoError:
        raise
    except Exception as exc:
        raise DocumentoError("No se pudo leer el documento Word: el archivo está dañado.") from exc
    return Contenido(_validar_largo(texto, max_caracteres), "docx")


def _txt(data: bytes, max_caracteres: int) -> Contenido:
    if b"\x00" in data or data.startswith((b"%PDF-", b"PK\x03\x04", b"\xd0\xcf\x11\xe0")):
        raise DocumentoError("El archivo no es un texto plano válido.")
    try:
        texto = data.decode("utf-8-sig")
    except UnicodeDecodeError:
        texto = data.decode("cp1252", errors="replace")
    return Contenido(_validar_largo(_limpiar(texto), max_caracteres), "txt")


def desde_archivo(nombre: str, data: bytes, *, max_caracteres: int, max_bytes: int) -> Contenido:
    ext = (nombre or "").rsplit(".", 1)[-1].lower() if "." in (nombre or "") else ""
    if ext == "doc":
        raise DocumentoError(
            "Los archivos Word antiguos (.doc) no se admiten. Abrilo en Word y guardalo como .docx.")
    if ext not in EXTENSIONES:
        raise DocumentoError("Formato no admitido. Usá PDF, Word (.docx) o TXT.")
    if not data:
        raise DocumentoError("El archivo está vacío.")
    if len(data) > max_bytes:
        raise DocumentoError(f"El archivo supera el máximo de {max_bytes // (1024 * 1024)} MB.")
    return {"pdf": _pdf, "docx": _docx, "txt": _txt}[ext](data, max_caracteres)
