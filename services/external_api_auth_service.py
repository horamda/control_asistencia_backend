import hmac
import os
import uuid
from datetime import datetime, timedelta, timezone

import jwt
from werkzeug.security import check_password_hash, generate_password_hash


EXTERNAL_API_ISSUER = "control-asistencia-external"
EXTERNAL_API_AUDIENCE = "control-asistencia-reports"
EXTERNAL_API_SCOPE = "external:read reports:read"
_MIN_SECRET_LENGTH = 32
_PLACEHOLDER_SECRETS = {
    "changeme",
    "secret",
    "test_secret",
    "your-secret",
}
_DUMMY_PASSWORD_HASH = generate_password_hash("__external_api_dummy_password__")


class ExternalApiAuthConfigError(RuntimeError):
    pass


class ExternalApiTokenError(ValueError):
    pass


def external_credentials_configured() -> bool:
    username = str(os.getenv("EXTERNAL_API_USERNAME") or "").strip()
    password_hash = str(os.getenv("EXTERNAL_API_PASSWORD_HASH") or "").strip()
    return bool(username and password_hash)


def _configured_credentials() -> tuple[str, str]:
    username = str(os.getenv("EXTERNAL_API_USERNAME") or "").strip()
    password_hash = str(os.getenv("EXTERNAL_API_PASSWORD_HASH") or "").strip()
    if not username or not password_hash:
        raise ExternalApiAuthConfigError(
            "EXTERNAL_API_USERNAME o EXTERNAL_API_PASSWORD_HASH no configurados."
        )
    return username, password_hash


def _token_secret() -> str:
    secret = str(
        os.getenv("EXTERNAL_API_JWT_SECRET")
        or os.getenv("JWT_SECRET")
        or ""
    ).strip()
    if not secret:
        raise ExternalApiAuthConfigError(
            "EXTERNAL_API_JWT_SECRET o JWT_SECRET no configurado."
        )
    if secret.lower() in _PLACEHOLDER_SECRETS or len(secret) < _MIN_SECRET_LENGTH:
        raise ExternalApiAuthConfigError(
            "El secreto JWT de la API externa debe tener al menos 32 caracteres y no ser un valor de plantilla."
        )
    return secret


def external_token_ttl_minutes() -> int:
    raw = str(os.getenv("EXTERNAL_API_TOKEN_TTL_MINUTES") or "60").strip()
    try:
        ttl = int(raw)
    except (TypeError, ValueError) as exc:
        raise ExternalApiAuthConfigError(
            "EXTERNAL_API_TOKEN_TTL_MINUTES debe ser numerico."
        ) from exc
    if ttl < 5 or ttl > 1440:
        raise ExternalApiAuthConfigError(
            "EXTERNAL_API_TOKEN_TTL_MINUTES debe estar entre 5 y 1440."
        )
    return ttl


def authenticate_external_credentials(username: str, password: str) -> bool:
    expected_username, password_hash = _configured_credentials()
    provided_username = str(username or "").strip()
    provided_password = str(password or "")

    username_ok = hmac.compare_digest(provided_username, expected_username)
    try:
        password_ok = check_password_hash(password_hash, provided_password)
    except (TypeError, ValueError):
        check_password_hash(_DUMMY_PASSWORD_HASH, provided_password)
        raise ExternalApiAuthConfigError(
            "EXTERNAL_API_PASSWORD_HASH no contiene un hash valido."
        )
    return username_ok and password_ok


def issue_external_access_token(username: str) -> tuple[str, int]:
    ttl_minutes = external_token_ttl_minutes()
    now = datetime.now(timezone.utc)
    expires_at = now + timedelta(minutes=ttl_minutes)
    payload = {
        "sub": str(username).strip(),
        "type": "external_api",
        "scope": EXTERNAL_API_SCOPE,
        "iss": EXTERNAL_API_ISSUER,
        "aud": EXTERNAL_API_AUDIENCE,
        "iat": now,
        "exp": expires_at,
        "jti": uuid.uuid4().hex,
    }
    token = jwt.encode(payload, _token_secret(), algorithm="HS256")
    return token, ttl_minutes * 60


def verify_external_access_token(token: str) -> dict:
    if not token:
        raise ExternalApiTokenError("Token requerido.")
    try:
        payload = jwt.decode(
            token,
            _token_secret(),
            algorithms=["HS256"],
            audience=EXTERNAL_API_AUDIENCE,
            issuer=EXTERNAL_API_ISSUER,
            options={
                "require": ["sub", "type", "scope", "iss", "aud", "iat", "exp"],
            },
        )
    except jwt.ExpiredSignatureError as exc:
        raise ExternalApiTokenError("Token expirado.") from exc
    except jwt.InvalidTokenError as exc:
        raise ExternalApiTokenError("Token invalido.") from exc

    scopes = set(str(payload.get("scope") or "").split())
    if payload.get("type") != "external_api" or "external:read" not in scopes:
        raise ExternalApiTokenError("Token invalido.")
    return payload
