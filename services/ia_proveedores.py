"""Clientes de los proveedores de IA (Anthropic, OpenAI, Gemini) detrás de una única interfaz.

Las claves se leen solo de variables de entorno del servidor y nunca se devuelven ni se registran.
Los SDK se importan dentro de cada función: si falta uno, el resto de FichaYa sigue funcionando.
Cada error del proveedor se traduce a IAError con un tipo estable para mostrarlo en el panel.
"""

import base64
import json
import os
from dataclasses import dataclass

PROVEEDORES = {
    "anthropic": {"nombre": "Anthropic (Claude)", "env": "ANTHROPIC_API_KEY", "modelo": "claude-opus-5-5"},
    "openai": {"nombre": "OpenAI", "env": "OPENAI_API_KEY", "modelo": ""},
    "gemini": {"nombre": "Gemini (Google)", "env": "GEMINI_API_KEY", "modelo": ""},
}

# Modelos de Anthropic que pueden declinar por clasificadores de seguridad: se pide el
# reintento automático del lado del servidor para que una negativa no corte la generación.
_ANTHROPIC_CON_FALLBACK = {
    "claude-opus-5-5", "claude-opus-5", "claude-sonnet-5-5", "claude-fable-5-2", "claude-fable-5-1",
}

MENSAJES = {
    "config": "El proveedor de IA no está configurado en el servidor.",
    "auth": "Error de autenticación: la clave de API es inválida o no tiene permisos.",
    "cuota": "Cuota insuficiente o límite de solicitudes alcanzado en el proveedor.",
    "modelo": "El modelo indicado no existe o no está disponible para esta cuenta.",
    "timeout": "El proveedor tardó demasiado en responder. Probá de nuevo o con menos contenido.",
    "red": "No se pudo conectar con el proveedor de IA.",
    "rechazo": "El proveedor se negó a procesar este contenido.",
    "respuesta": "El proveedor devolvió una respuesta incompleta o inválida.",
    "solicitud": "El proveedor rechazó la solicitud (contenido o parámetros no admitidos).",
    "proveedor": "El proveedor de IA devolvió un error. Probá de nuevo más tarde.",
}


class IAError(Exception):
    def __init__(self, tipo: str, detalle: str | None = None):
        self.tipo = tipo if tipo in MENSAJES else "proveedor"
        self.detalle = detalle
        super().__init__(MENSAJES[self.tipo])


@dataclass
class Respuesta:
    texto: str
    tokens_entrada: int = 0
    tokens_salida: int = 0

    def json(self) -> dict:
        raw = (self.texto or "").strip()
        if raw.startswith("```"):
            raw = raw.strip("`")
            raw = raw[4:] if raw[:4].lower() == "json" else raw
        try:
            data = json.loads(raw)
        except ValueError as exc:
            raise IAError("respuesta") from exc
        if not isinstance(data, dict):
            raise IAError("respuesta")
        return data


def clave(proveedor: str) -> str | None:
    info = PROVEEDORES.get(proveedor)
    return (os.getenv(info["env"]) or "").strip() or None if info else None


def configurado(proveedor: str) -> bool:
    return bool(clave(proveedor))


def timeout_segundos() -> float:
    # Menor que el timeout de Gunicorn (120 s) para responder con un error claro.
    try:
        return float(min(110, max(10, int(os.getenv("IA_TIMEOUT_SEGUNDOS", "100")))))
    except ValueError:
        return 100.0


def _exigir(proveedor: str, modelo: str) -> str:
    if proveedor not in PROVEEDORES:
        raise IAError("config")
    key = clave(proveedor)
    if not key or not modelo:
        raise IAError("config")
    return key


def _por_texto(mensaje: str, defecto: str) -> str:
    bajo = (mensaje or "").lower()
    if any(p in bajo for p in ("credit", "billing", "quota", "spend limit", "insufficient")):
        return "cuota"
    if "api key" in bajo or "api_key" in bajo:
        return "auth"
    return defecto


def _por_codigo(codigo, mensaje: str) -> str:
    if codigo in (401, 403):
        return "auth"
    if codigo == 404:
        return "modelo"
    if codigo == 429:
        return "cuota"
    if codigo == 400:
        return _por_texto(mensaje, "solicitud")
    return _por_texto(mensaje, "proveedor")


# ---------------------------------------------------------------------------
# Anthropic
# ---------------------------------------------------------------------------

def _anthropic(key, modelo, sistema, usuario, pdf, esquema, max_tokens, tolerar_corte):
    import anthropic

    client = anthropic.Anthropic(api_key=key, timeout=timeout_segundos(), max_retries=0)
    contenido = []
    if pdf:
        contenido.append({"type": "document", "source": {
            "type": "base64", "media_type": "application/pdf",
            "data": base64.standard_b64encode(pdf).decode("ascii"),
        }})
    contenido.append({"type": "text", "text": usuario})
    kwargs = dict(model=modelo, max_tokens=max_tokens, messages=[{"role": "user", "content": contenido}])
    if sistema:
        kwargs["system"] = sistema
    if esquema:
        kwargs["output_config"] = {"format": {"type": "json_schema", "schema": esquema}}
    try:
        if modelo in _ANTHROPIC_CON_FALLBACK:
            try:
                resp = client.beta.messages.create(
                    betas=["server-side-fallback-2026-07-01"], fallbacks="default", **kwargs)
            except anthropic.BadRequestError:
                # Cuentas o combinaciones que no admiten el reintento del servidor.
                resp = client.messages.create(**kwargs)
        else:
            resp = client.messages.create(**kwargs)
    except anthropic.APITimeoutError as exc:
        raise IAError("timeout") from exc
    except anthropic.APIConnectionError as exc:
        raise IAError("red") from exc
    except (anthropic.AuthenticationError, anthropic.PermissionDeniedError) as exc:
        raise IAError(_por_texto(str(exc), "auth")) from exc
    except anthropic.NotFoundError as exc:
        raise IAError("modelo") from exc
    except anthropic.RateLimitError as exc:
        raise IAError("cuota") from exc
    except anthropic.APIStatusError as exc:
        raise IAError(_por_codigo(exc.status_code, str(exc))) from exc

    uso = resp.usage
    entrada = int((uso.input_tokens or 0) + (getattr(uso, "cache_read_input_tokens", 0) or 0)
                  + (getattr(uso, "cache_creation_input_tokens", 0) or 0))
    salida = int(uso.output_tokens or 0)
    if resp.stop_reason == "refusal":
        raise IAError("rechazo")
    if resp.stop_reason == "max_tokens" and not tolerar_corte:
        raise IAError("respuesta")
    texto = next((b.text for b in resp.content if b.type == "text"), "")
    return Respuesta(texto, entrada, salida)


def _anthropic_modelos(key):
    import anthropic

    client = anthropic.Anthropic(api_key=key, timeout=20.0, max_retries=0)
    return [m.id for m in client.models.list(limit=100)]


# ---------------------------------------------------------------------------
# OpenAI
# ---------------------------------------------------------------------------

def _openai(key, modelo, sistema, usuario, pdf, esquema, max_tokens, tolerar_corte):
    import openai

    client = openai.OpenAI(api_key=key, timeout=timeout_segundos(), max_retries=0)
    partes = []
    if pdf:
        partes.append({"type": "file", "file": {
            "filename": "documento.pdf",
            "file_data": "data:application/pdf;base64," + base64.standard_b64encode(pdf).decode("ascii"),
        }})
    partes.append({"type": "text", "text": usuario})
    mensajes = ([{"role": "system", "content": sistema}] if sistema else []) + [{"role": "user", "content": partes}]
    kwargs = dict(model=modelo, messages=mensajes, max_completion_tokens=max_tokens)
    if esquema:
        kwargs["response_format"] = {"type": "json_schema", "json_schema": {
            "name": "trivia", "strict": True, "schema": esquema}}
    try:
        resp = client.chat.completions.create(**kwargs)
    except openai.APITimeoutError as exc:
        raise IAError("timeout") from exc
    except openai.APIConnectionError as exc:
        raise IAError("red") from exc
    except (openai.AuthenticationError, openai.PermissionDeniedError) as exc:
        raise IAError("auth") from exc
    except openai.NotFoundError as exc:
        raise IAError("modelo") from exc
    except openai.RateLimitError as exc:
        raise IAError("cuota") from exc
    except openai.APIStatusError as exc:
        raise IAError(_por_codigo(exc.status_code, str(exc))) from exc

    uso = resp.usage
    entrada = int(getattr(uso, "prompt_tokens", 0) or 0)
    salida = int(getattr(uso, "completion_tokens", 0) or 0)
    opcion = resp.choices[0] if resp.choices else None
    if opcion is None:
        raise IAError("respuesta")
    if getattr(opcion.message, "refusal", None) or opcion.finish_reason == "content_filter":
        raise IAError("rechazo")
    if opcion.finish_reason == "length" and not tolerar_corte:
        raise IAError("respuesta")
    return Respuesta(opcion.message.content or "", entrada, salida)


def _openai_modelos(key):
    import openai

    client = openai.OpenAI(api_key=key, timeout=20.0, max_retries=0)
    return [m.id for m in client.models.list()]


# ---------------------------------------------------------------------------
# Gemini
# ---------------------------------------------------------------------------

def _gemini_error(exc):
    from google.genai import errors

    if isinstance(exc, errors.APIError):
        return IAError(_por_codigo(getattr(exc, "code", None), str(getattr(exc, "message", "") or exc)))
    return IAError("timeout" if "timeout" in type(exc).__name__.lower() else "red")


def _gemini(key, modelo, sistema, usuario, pdf, esquema, max_tokens, tolerar_corte):
    from google import genai
    from google.genai import types

    client = genai.Client(api_key=key, http_options=types.HttpOptions(timeout=int(timeout_segundos() * 1000)))
    contenido = []
    if pdf:
        contenido.append(types.Part.from_bytes(data=pdf, mime_type="application/pdf"))
    contenido.append(usuario)
    config = {}
    if sistema:
        config["system_instruction"] = sistema
    if esquema:
        config["response_mime_type"] = "application/json"
        config["response_json_schema"] = esquema
    try:
        resp = client.models.generate_content(
            model=modelo, contents=contenido, config=types.GenerateContentConfig(**config))
    except Exception as exc:  # el SDK mezcla errores propios y del cliente HTTP
        raise _gemini_error(exc) from exc

    uso = getattr(resp, "usage_metadata", None)
    entrada = int(getattr(uso, "prompt_token_count", 0) or 0)
    salida = int((getattr(uso, "candidates_token_count", 0) or 0) + (getattr(uso, "thoughts_token_count", 0) or 0))
    candidato = resp.candidates[0] if getattr(resp, "candidates", None) else None
    motivo = str(getattr(candidato, "finish_reason", "") or "").upper()
    if candidato is None or any(p in motivo for p in ("SAFETY", "PROHIBITED", "BLOCKLIST", "RECITATION")):
        raise IAError("rechazo")
    if "MAX_TOKENS" in motivo and not tolerar_corte:
        raise IAError("respuesta")
    return Respuesta(resp.text or "", entrada, salida)


def _gemini_modelos(key):
    from google import genai
    from google.genai import types

    client = genai.Client(api_key=key, http_options=types.HttpOptions(timeout=20000))
    try:
        return [str(m.name).removeprefix("models/") for m in client.models.list()]
    except Exception as exc:
        raise _gemini_error(exc) from exc


_COMPLETAR = {"anthropic": _anthropic, "openai": _openai, "gemini": _gemini}
_MODELOS = {"anthropic": _anthropic_modelos, "openai": _openai_modelos, "gemini": _gemini_modelos}


# ---------------------------------------------------------------------------
# Interfaz pública
# ---------------------------------------------------------------------------

def completar(proveedor: str, modelo: str, *, sistema: str, usuario: str, pdf: bytes | None = None,
              esquema: dict | None = None, max_tokens: int = 16000, tolerar_corte: bool = False) -> Respuesta:
    key = _exigir(proveedor, modelo)
    try:
        return _COMPLETAR[proveedor](key, modelo, sistema, usuario, pdf, esquema, max_tokens, tolerar_corte)
    except IAError:
        raise
    except ImportError as exc:
        raise IAError("config", "Falta instalar la librería del proveedor.") from exc
    except Exception as exc:
        raise IAError("proveedor") from exc


def probar(proveedor: str, modelo: str) -> Respuesta:
    """Solicitud real mínima para verificar clave, cuota y modelo."""
    return completar(proveedor, modelo, sistema="", usuario="Respondé únicamente: OK",
                     max_tokens=256, tolerar_corte=True)


def listar_modelos(proveedor: str) -> list[str]:
    if proveedor not in PROVEEDORES or not clave(proveedor):
        raise IAError("config")
    try:
        return sorted(set(_MODELOS[proveedor](clave(proveedor))))
    except IAError:
        raise
    except ImportError as exc:
        raise IAError("config") from exc
    except Exception as exc:
        nombre = type(exc).__name__
        if "Authentication" in nombre or "PermissionDenied" in nombre:
            raise IAError("auth") from exc
        if "RateLimit" in nombre:
            raise IAError("cuota") from exc
        if "Timeout" in nombre:
            raise IAError("timeout") from exc
        raise IAError("red" if "Connection" in nombre else "proveedor") from exc
