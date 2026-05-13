import pytest

from utils.jwt import (
    QRTokenValidationError,
    extract_qr_token,
    generar_token_qr,
    verificar_token_qr,
)


def test_qr_token_accepts_jwt_url_json_and_bearer(monkeypatch):
    monkeypatch.setenv("JWT_SECRET", "qr_test_secret_0123456789abcdef012345")
    token = generar_token_qr(
        {"accion": "auto", "empresa_id": 7, "scope": "empresa"},
        vigencia_segundos=120,
    )

    assert extract_qr_token(token) == token
    assert extract_qr_token(f"Bearer {token}") == token
    assert extract_qr_token(f"https://app.example/scan?qr_token={token}") == token

    payload = verificar_token_qr(f'{{"qr_token":"{token}"}}')
    assert payload["type"] == "asistencia_qr"
    assert payload["empresa_id"] == 7


def test_qr_token_invalid_signature_has_specific_code(monkeypatch):
    monkeypatch.setenv("JWT_SECRET", "qr_test_secret_0123456789abcdef012345")
    token = generar_token_qr(
        {"accion": "auto", "empresa_id": 7, "scope": "empresa"},
        vigencia_segundos=120,
    )

    monkeypatch.setenv("JWT_SECRET", "other_secret_0123456789abcdef01234567")
    with pytest.raises(QRTokenValidationError) as exc:
        verificar_token_qr(token)

    assert exc.value.code == "qr_token_invalid_signature"


def test_qr_token_malformed_has_specific_code():
    with pytest.raises(QRTokenValidationError) as exc:
        extract_qr_token("esto no es un qr valido")

    assert exc.value.code == "qr_token_malformed"
