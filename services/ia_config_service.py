"""Configuración de IA del panel: proveedor, modelo, activación, límites y registro de uso.

Los valores se guardan en system_config (claves ia_*). Las claves de API no pasan por acá:
solo se informa si la variable de entorno correspondiente está cargada.
"""

import logging
import time

import repositories.ia_repository as repo
from services import ia_proveedores as prov

logger = logging.getLogger(__name__)

# clave: (valor por defecto, mínimo, máximo)
_ENTEROS = {
    "ia_max_preguntas": (20, 1, 50),
    "ia_max_generaciones_dia": (30, 0, 10000),
    "ia_max_caracteres": (60000, 1000, 400000),
    "ia_max_archivo_mb": (10, 1, 25),
}
_DECIMALES = {"ia_presupuesto_mensual_usd": (0.0, 0.0, 100000.0)}


class LimiteIAError(Exception):
    """La generación está desactivada o se alcanzó un límite configurado."""


def _entero(raw, clave):
    defecto, minimo, maximo = _ENTEROS[clave]
    try:
        return min(maximo, max(minimo, int(str(raw).strip())))
    except (TypeError, ValueError):
        return defecto


def _decimal(raw, defecto=0.0, minimo=0.0, maximo=100000.0):
    try:
        return min(maximo, max(minimo, float(str(raw).strip().replace(",", "."))))
    except (TypeError, ValueError):
        return defecto


def cargar() -> dict:
    try:
        raw = repo.get_config()
    except Exception:
        # Sin la tabla o sin base, la IA queda apagada y el resto del panel no se ve afectado.
        logger.exception("[ia] no se pudo leer la configuración")
        raw = {}
    proveedor = raw.get("ia_proveedor") if raw.get("ia_proveedor") in prov.PROVEEDORES else "anthropic"
    cfg = {
        "proveedor": proveedor,
        "trivias_activa": raw.get("ia_trivias_activa") == "1",
        "modelos": {}, "precios": {},
    }
    for codigo, info in prov.PROVEEDORES.items():
        cfg["modelos"][codigo] = (raw.get(f"ia_modelo_{codigo}") or info["modelo"]).strip()
        cfg["precios"][codigo] = {
            "entrada": _decimal(raw.get(f"ia_precio_entrada_{codigo}"), maximo=10000.0),
            "salida": _decimal(raw.get(f"ia_precio_salida_{codigo}"), maximo=10000.0),
        }
    cfg["modelo"] = cfg["modelos"][proveedor]
    for clave in _ENTEROS:
        cfg[clave.removeprefix("ia_")] = _entero(raw.get(clave), clave)
    for clave, (defecto, minimo, maximo) in _DECIMALES.items():
        cfg[clave.removeprefix("ia_")] = _decimal(raw.get(clave), defecto, minimo, maximo)
    cfg["configurado"] = prov.configurado(proveedor) and bool(cfg["modelo"])
    cfg["disponible"] = cfg["trivias_activa"] and cfg["configurado"]
    return cfg


def guardar(form) -> list[str]:
    """Valida y guarda el formulario del panel. Devuelve la lista de errores (vacía si guardó)."""
    errores = []
    proveedor = (form.get("proveedor") or "").strip()
    if proveedor not in prov.PROVEEDORES:
        errores.append("Seleccioná un proveedor válido.")
    valores = {"ia_proveedor": proveedor, "ia_trivias_activa": "1" if form.get("trivias_activa") else "0"}
    for codigo in prov.PROVEEDORES:
        modelo = (form.get(f"modelo_{codigo}") or "").strip()
        if len(modelo) > 120 or any(c.isspace() for c in modelo):
            errores.append(f"El modelo de {prov.PROVEEDORES[codigo]['nombre']} no es válido.")
        valores[f"ia_modelo_{codigo}"] = modelo
        for lado in ("entrada", "salida"):
            valores[f"ia_precio_{lado}_{codigo}"] = str(_decimal(form.get(f"precio_{lado}_{codigo}"), maximo=10000.0))
    for clave in _ENTEROS:
        valores[clave] = str(_entero(form.get(clave.removeprefix("ia_")), clave))
    for clave, (defecto, minimo, maximo) in _DECIMALES.items():
        valores[clave] = str(_decimal(form.get(clave.removeprefix("ia_")), defecto, minimo, maximo))
    if not errores and valores["ia_trivias_activa"] == "1":
        if not prov.configurado(proveedor):
            errores.append("No se puede activar: falta la clave del proveedor elegido en el servidor.")
        elif not (valores[f"ia_modelo_{proveedor}"] or prov.PROVEEDORES[proveedor]["modelo"]):
            errores.append("No se puede activar: indicá el modelo del proveedor elegido.")
    if not errores:
        repo.set_config(valores)
    return errores


def estado_proveedores() -> list[dict]:
    return [
        {"codigo": c, "nombre": i["nombre"], "variable": i["env"], "configurado": prov.configurado(c)}
        for c, i in prov.PROVEEDORES.items()
    ]


def costo(cfg: dict, proveedor: str, tokens_entrada: int, tokens_salida: int) -> float:
    precio = cfg["precios"].get(proveedor, {})
    return round((tokens_entrada * precio.get("entrada", 0) + tokens_salida * precio.get("salida", 0)) / 1_000_000, 4)


def verificar_limites(cfg: dict):
    """Lanza LimiteIAError si la generación no está permitida ahora."""
    if not cfg["trivias_activa"]:
        raise LimiteIAError("La generación de trivias con IA está desactivada.")
    if not cfg["configurado"]:
        raise LimiteIAError("El proveedor de IA no está configurado. Avisá a un administrador.")
    uso = repo.resumen_uso()
    limite = cfg["max_generaciones_dia"]
    if limite and uso["generaciones_hoy"] >= limite:
        raise LimiteIAError(f"Se alcanzó el límite diario de {limite} generaciones con IA.")
    presupuesto = cfg["presupuesto_mensual_usd"]
    if presupuesto and uso["costo_mes"] >= presupuesto:
        raise LimiteIAError("Se alcanzó el presupuesto mensual configurado para IA.")


def ejecutar(cfg: dict, operacion: str, usuario_id, llamada, *, proveedor=None, modelo=None):
    """Ejecuta una llamada al proveedor y registra su uso (tokens, costo, resultado), sin contenido."""
    proveedor = proveedor or cfg["proveedor"]
    modelo = modelo or cfg["modelos"][proveedor]
    inicio = time.monotonic()
    fila = {"usuario_id": usuario_id, "proveedor": proveedor, "modelo": modelo or "-",
            "operacion": operacion, "estado": "ok"}
    try:
        respuesta = llamada(proveedor, modelo)
        fila.update(tokens_entrada=respuesta.tokens_entrada, tokens_salida=respuesta.tokens_salida,
                    costo_usd=costo(cfg, proveedor, respuesta.tokens_entrada, respuesta.tokens_salida))
        return respuesta
    except prov.IAError as exc:
        fila.update(estado="error", error_tipo=exc.tipo)
        logger.warning("[ia] %s falló: proveedor=%s modelo=%s tipo=%s", operacion, proveedor, modelo, exc.tipo)
        raise
    finally:
        fila["duracion_ms"] = int((time.monotonic() - inicio) * 1000)
        try:
            repo.registrar_uso(fila)
        except Exception:
            logger.exception("[ia] no se pudo registrar el uso")


def probar_conexion(cfg: dict, proveedor: str, modelo: str, usuario_id) -> dict:
    try:
        ejecutar(cfg, "prueba", usuario_id, prov.probar, proveedor=proveedor, modelo=modelo)
        return {"ok": True, "tipo": "ok", "mensaje": "Conexión correcta: el proveedor respondió con este modelo."}
    except prov.IAError as exc:
        return {"ok": False, "tipo": exc.tipo, "mensaje": str(exc)}


def panel() -> dict:
    cfg = cargar()
    try:
        uso, ultimos = repo.resumen_uso(), repo.ultimos_usos()
    except Exception:
        logger.exception("[ia] no se pudo leer el uso")
        uso, ultimos = None, []
    return {"cfg": cfg, "proveedores": estado_proveedores(), "uso": uso, "ultimos": ultimos}
