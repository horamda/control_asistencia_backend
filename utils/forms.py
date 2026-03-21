"""
Utilidades compartidas para manejo de formularios web.
Centraliza parsers y helpers usados en múltiples routes.
"""
import datetime
from urllib.parse import urlparse


def parse_int(value) -> int | None:
    value = (value or "").strip()
    if not value:
        return None
    try:
        return int(value)
    except ValueError:
        return None


def parse_float(value) -> float | None:
    value = (value or "").strip()
    if not value:
        return None
    try:
        return float(value)
    except ValueError:
        return None


def parse_date(raw) -> str | None:
    """Valida y retorna la fecha en formato ISO (YYYY-MM-DD), o None si está vacía."""
    value = (raw or "").strip()
    if not value:
        return None
    return datetime.date.fromisoformat(value).isoformat()


def safe_next_url(value) -> str | None:
    """Retorna la URL solo si es relativa e interna. Evita open redirects."""
    raw = str(value or "").strip()
    if not raw:
        return None
    parsed = urlparse(raw)
    if parsed.scheme or parsed.netloc:
        return None
    if not raw.startswith("/"):
        return None
    return raw
