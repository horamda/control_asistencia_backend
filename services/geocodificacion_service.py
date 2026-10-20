"""Buscar una direccion para ubicar una sucursal (panel). Consulta OpenStreetMap (Nominatim) desde el servidor:
la CSP del panel no deja que el navegador llame a otros sitios.

Politica de uso de Nominatim: un pedido por segundo como maximo, identificarse con User-Agent y cachear. Solo se usa
al tipear en el buscador del formulario de sucursal (admin), con resultados de Argentina."""

import json
import threading
import time
import urllib.parse
import urllib.request

from services.carga_service import CargaError as Error

URL = "https://nominatim.openstreetmap.org/search"
AGENTE = "FichaYa-panel/1.0 (ubicacion de sucursales)"
TIMEOUT_S = 6
MAX_RESULTADOS = 5
_cache = {}
_CACHE_MAX = 200
_ultimo = {"t": 0.0}
_lock = threading.Lock()


def buscar(texto):
    """[{nombre, lat, lon}] para la direccion; Error si es muy corta o el servicio no responde."""
    consulta = " ".join(str(texto or "").split())[:200]
    if len(consulta) < 4:
        raise Error("Escribí al menos 4 letras de la dirección.")
    clave = consulta.lower()
    if clave in _cache:
        return _cache[clave]
    with _lock:  # un pedido por segundo como maximo (politica de Nominatim)
        espera = 1.0 - (time.monotonic() - _ultimo["t"])
        if espera > 0:
            time.sleep(espera)
        _ultimo["t"] = time.monotonic()
    parametros = urllib.parse.urlencode({"q": consulta, "format": "jsonv2", "countrycodes": "ar",
                                         "limit": MAX_RESULTADOS, "accept-language": "es"})
    pedido = urllib.request.Request(f"{URL}?{parametros}", headers={"User-Agent": AGENTE})
    try:
        with urllib.request.urlopen(pedido, timeout=TIMEOUT_S) as respuesta:  # noqa: S310 (URL fija de OpenStreetMap)
            filas = json.loads(respuesta.read().decode("utf-8"))
    except Exception:
        raise Error("No se pudo consultar el buscador de direcciones. Probá de nuevo o ubicá el pin a mano.", 502) from None
    resultados = [dict(nombre=f.get("display_name") or consulta, lat=round(float(f["lat"]), 7), lon=round(float(f["lon"]), 7))
                  for f in filas if f.get("lat") and f.get("lon")][:MAX_RESULTADOS]
    if len(_cache) >= _CACHE_MAX:
        _cache.pop(next(iter(_cache)))
    _cache[clave] = resultados
    return resultados
