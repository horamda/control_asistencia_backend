import jwt
import os
from datetime import datetime, timedelta


def _get_secret():
    secret = os.getenv("JWT_SECRET")
    if not secret:
        raise RuntimeError("JWT_SECRET no configurada")
    return secret


def generar_token(payload):
    if not isinstance(payload, dict):
        raise ValueError("Payload invalido")

    secret = _get_secret()

    token_payload = dict(payload)
    token_payload["exp"] = datetime.utcnow() + timedelta(
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
        raise ValueError("Token requerido")

    secret = _get_secret()

    try:
        payload = jwt.decode(token, secret, algorithms=["HS256"])
        return payload
    except jwt.ExpiredSignatureError as exc:
        raise ValueError("Token expirado") from exc
    except jwt.InvalidTokenError as exc:
        raise ValueError("Token invalido") from exc


def generar_token_qr(payload: dict, vigencia_segundos: int = 120):
    if not isinstance(payload, dict):
        raise ValueError("Payload QR invalido")

    ttl = int(vigencia_segundos)
    if ttl < 30 or ttl > 315360000:
        raise ValueError("vigencia_segundos fuera de rango (30-315360000)")

    secret = _get_secret()
    token_payload = dict(payload)
    token_payload["type"] = "asistencia_qr"
    token_payload["exp"] = datetime.utcnow() + timedelta(seconds=ttl)

    return jwt.encode(token_payload, secret, algorithm="HS256")


def verificar_token_qr(token: str, accion_esperada: str | None = None):
    payload = verificar_token(token)
    if payload.get("type") != "asistencia_qr":
        raise ValueError("Token QR invalido")

    empresa_id = payload.get("empresa_id")
    if not empresa_id:
        raise ValueError("Token QR sin empresa_id")

    accion = str(payload.get("accion") or "").strip().lower()
    if accion_esperada and accion not in {accion_esperada, "auto"}:
        raise ValueError("QR invalido para esta operacion.")

    return payload
