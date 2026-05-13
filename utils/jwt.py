import json
import os
import re
from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qs, urlparse

import jwt


_JWT_MIN_SECRET_LEN = 32
_JWT_PLACEHOLDER_VALUES = {"changeme", "secret", "your-secret", "jwt_secret", "test_secret"}
DEFAULT_QR_TTL_SECONDS = 30 * 86400
_QR_TOKEN_FIELDS = ("qr_token", "token", "qr")
_JWT_COMPACT_RE = re.compile(r"^[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+$")


class TokenValidationError(ValueError):
    def __init__(self, message: str, code: str, status_code: int = 400):
        super().__init__(message)
        self.code = code
        self.status_code = status_code


class QRTokenValidationError(TokenValidationError):
    pass


def _get_secret():
    secret = os.getenv("JWT_SECRET", "").strip()
    if not secret:
        raise RuntimeError("JWT_SECRET no configurada")
    if secret.lower() in _JWT_PLACEHOLDER_VALUES:
        raise RuntimeError(
            "JWT_SECRET tiene un valor inseguro de plantilla. Configure una clave real."
        )
    if len(secret) < _JWT_MIN_SECRET_LEN:
        raise RuntimeError(
            f"JWT_SECRET debe tener al menos {_JWT_MIN_SECRET_LEN} caracteres."
        )
    return secret


def generar_token(payload):
    if not isinstance(payload, dict):
        raise ValueError("Payload invalido")

    secret = _get_secret()

    token_payload = dict(payload)
    token_payload["exp"] = datetime.now(timezone.utc) + timedelta(
        minutes=int(os.getenv("JWT_EXPIRE_MINUTES", 720))
    )

    token = jwt.encode(
        token_payload,
        secret,
        algorithm="HS256"
    )

    return token


def verificar_token(token: str):
    if not token:
        raise TokenValidationError("Token requerido", "token_required")

    secret = _get_secret()

    try:
        payload = jwt.decode(token, secret, algorithms=["HS256"])
        return payload
    except jwt.ExpiredSignatureError as exc:
        raise TokenValidationError("Token expirado", "token_expired") from exc
    except jwt.InvalidSignatureError as exc:
        raise TokenValidationError("Token invalido", "token_invalid_signature") from exc
    except jwt.DecodeError as exc:
        raise TokenValidationError("Token invalido", "token_malformed") from exc
    except jwt.InvalidTokenError as exc:
        raise TokenValidationError("Token invalido", "token_invalid") from exc


def generar_token_qr(payload: dict, vigencia_segundos: int = DEFAULT_QR_TTL_SECONDS):
    if not isinstance(payload, dict):
        raise ValueError("Payload QR invalido")

    ttl = int(vigencia_segundos)
    if ttl < 30 or ttl > 315360000:
        raise ValueError("vigencia_segundos fuera de rango (30-315360000)")

    secret = _get_secret()
    token_payload = dict(payload)
    token_payload["type"] = "asistencia_qr"
    token_payload["exp"] = datetime.now(timezone.utc) + timedelta(seconds=ttl)

    return jwt.encode(token_payload, secret, algorithm="HS256")


def _looks_like_jwt(value: str) -> bool:
    return bool(_JWT_COMPACT_RE.fullmatch(value))


def extract_qr_token(raw_token: str | None) -> str:
    value = str(raw_token or "").strip()
    if not value:
        raise QRTokenValidationError(
            "qr_token requerido para metodo qr.",
            "qr_token_required",
        )

    if value.lower().startswith("bearer "):
        value = value[7:].strip()
        if _looks_like_jwt(value):
            return value

    if _looks_like_jwt(value):
        return value

    if value.startswith("{"):
        try:
            data = json.loads(value)
        except json.JSONDecodeError:
            data = None
        if isinstance(data, dict):
            for field in _QR_TOKEN_FIELDS:
                candidate = data.get(field)
                if isinstance(candidate, str) and candidate.strip():
                    return extract_qr_token(candidate)

    parsed = urlparse(value)
    query_sources = []
    if parsed.query:
        query_sources.append(parsed.query)
    if parsed.fragment:
        fragment = parsed.fragment.lstrip("?")
        query_sources.append(fragment)
        if "?" in fragment:
            query_sources.append(fragment.split("?", 1)[1])
    if "=" in value and not parsed.query:
        query_sources.append(value.lstrip("?"))

    for query in query_sources:
        params = parse_qs(query, keep_blank_values=False)
        for field in _QR_TOKEN_FIELDS:
            values = params.get(field) or params.get(field.replace("_", "-"))
            if values:
                return extract_qr_token(values[0])

    raise QRTokenValidationError(
        "QR invalido. Escanee un QR generado por el sistema.",
        "qr_token_malformed",
    )


def verificar_token_qr(token: str, accion_esperada: str | None = None):
    qr_token = extract_qr_token(token)
    try:
        payload = verificar_token(qr_token)
    except TokenValidationError as exc:
        if exc.code == "token_expired":
            raise QRTokenValidationError(
                "QR vencido. Genere un QR nuevo.",
                "qr_token_expired",
            ) from exc
        if exc.code == "token_invalid_signature":
            raise QRTokenValidationError(
                "QR invalido o generado en otro ambiente. Genere un QR nuevo desde este sistema.",
                "qr_token_invalid_signature",
            ) from exc
        raise QRTokenValidationError(
            "QR invalido. Escanee un QR generado por el sistema.",
            "qr_token_invalid",
        ) from exc

    if payload.get("type") != "asistencia_qr":
        raise QRTokenValidationError("Token QR invalido", "qr_token_wrong_type")

    empresa_id = payload.get("empresa_id")
    if not empresa_id:
        raise QRTokenValidationError("Token QR sin empresa_id", "qr_token_missing_empresa")

    accion = str(payload.get("accion") or "").strip().lower()
    if accion_esperada and accion not in {accion_esperada, "auto"}:
        raise QRTokenValidationError(
            "QR invalido para esta operacion.",
            "qr_token_wrong_action",
        )

    return payload
