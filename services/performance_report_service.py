"""Reporte del modulo Rendimiento: indicadores, graficos y ranking de rutas a
partir de request_metrics_hourly (tiempos medidos dentro de la app)."""
from datetime import datetime, timedelta

from repositories.request_metrics_repository import get_report_data
from services.svg_chart_service import column_chart, line_chart
from utils.request_metrics import ARGENTINA, BUCKET_COLUMNS, BUCKET_LIMITS

PERIODOS = {
    "24h": {"titulo": "Últimas 24 horas", "por_dia": False, "puntos": 24},
    "7d": {"titulo": "Últimos 7 días", "por_dia": True, "puntos": 7},
    "30d": {"titulo": "Últimos 30 días", "por_dia": True, "puntos": 30},
}
LENTO_MS = 1000
# Cubetas con pedidos de mas de LENTO_MS (b2000, b5000, binf).
_LENTAS = slice(BUCKET_LIMITS.index(LENTO_MS) + 1, None)


def _num(value) -> str:
    return f"{int(value or 0):,}".replace(",", ".")


def _ratio(part, total, factor=1.0):
    return part * factor / total if total else None


def _fmt(value, suffix, decimals=1):
    return "s/d" if value is None else f"{value:.{decimals}f}{suffix}"


def percentile_label(buckets: list[int], p: float) -> str:
    """Percentil aproximado: limite superior de la cubeta que lo contiene."""
    total = sum(buckets)
    if not total:
        return "s/d"
    acumulado = 0
    for index, count in enumerate(buckets):
        acumulado += count
        if acumulado >= p * total:
            if index >= len(BUCKET_LIMITS):
                return f"> {BUCKET_LIMITS[-1] / 1000:g} s"
            limite = BUCKET_LIMITS[index]
            return f"≤ {limite} ms" if limite < 1000 else f"≤ {limite / 1000:g} s"
    return "s/d"


def resumir(row: dict) -> dict:
    pedidos = int(row.get("pedidos") or 0)
    buckets = [int(row.get(c) or 0) for c in BUCKET_COLUMNS]
    ms_total = float(row.get("ms_total") or 0)
    db_ms = float(row.get("db_ms_total") or 0)
    consultas = int(row.get("db_consultas") or 0)
    return {
        "pedidos": pedidos,
        "errores": int(row.get("errores") or 0),
        "promedio_s": _ratio(ms_total, pedidos, 1 / 1000),
        "p50": percentile_label(buckets, 0.5),
        "p95": percentile_label(buckets, 0.95),
        "lentos_pct": _ratio(sum(buckets[_LENTAS]), pedidos, 100),
        "db_pct": _ratio(db_ms, ms_total, 100),
        "ms_por_consulta": _ratio(db_ms, consultas),
        "consultas_por_pedido": _ratio(consultas, pedidos),
        "max_s": float(row.get("ms_max") or 0) / 1000,
    }


def _periodos(periodo: dict, ahora: datetime):
    if periodo["por_dia"]:
        hoy = ahora.date()
        dias = [hoy - timedelta(days=i) for i in range(periodo["puntos"] - 1, -1, -1)]
        desde = datetime.combine(dias[0], datetime.min.time())
        return desde, dias
    hora = ahora.replace(minute=0, second=0, microsecond=0)
    horas = [hora - timedelta(hours=i) for i in range(periodo["puntos"] - 1, -1, -1)]
    return horas[0], horas


def _clave(valor):
    if isinstance(valor, datetime):
        return valor.replace(minute=0, second=0, microsecond=0)
    return valor


def build_report(periodo_key: str, *, ahora: datetime | None = None, fetch=None) -> dict:
    periodo = PERIODOS.get(periodo_key) or PERIODOS["24h"]
    ahora = ahora or datetime.now(ARGENTINA).replace(tzinfo=None)
    desde, puntos = _periodos(periodo, ahora)
    data = (fetch or get_report_data)(desde, por_dia=periodo["por_dia"])

    por_periodo = {_clave(row["periodo"]): resumir(row) for row in data["serie"]}
    filas, labels, nombres = [], [], []
    salto = max(1, len(puntos) // 8)  # pocas etiquetas en el eje para que no se pisen
    for index, punto in enumerate(puntos):
        resumen = por_periodo.get(_clave(punto)) or resumir({})
        if periodo["por_dia"]:
            nombre = f"{punto:%d/%m}"
            etiqueta = nombre if index % salto == 0 or index == len(puntos) - 1 else ""
            sub = ""
        else:
            nombre = f"{punto:%d/%m %H}:00"
            etiqueta = f"{punto:%H}" if index % 3 == 0 or index == len(puntos) - 1 else ""
            sub = f"{punto:%d/%m}" if index == 0 or punto.hour == 0 else ""
        filas.append({"nombre": nombre, **resumen})
        labels.append({"label": etiqueta, "sub": sub})
        nombres.append(nombre)

    def serie(key, name, campo):
        return [{"key": key, "name": name, "values": [f[campo] for f in filas]}]

    graficos = {
        # Los graficos anchos usan un viewBox de 880 (texto casi 1:1 en escritorio).
        "tiempo": line_chart(labels, serie("promedio", "Tiempo promedio", "promedio_s"), suffix=" s", decimals=2,
                             width=880, height=260),
        "lentos": line_chart(labels, serie("lentos", "Pedidos lentos", "lentos_pct"), suffix="%"),
        "base": line_chart(labels, serie("base", "Latencia por consulta", "ms_por_consulta"), suffix=" ms"),
        "volumen": column_chart(
            [{"label": l["label"], "value": f["pedidos"] or None} for l, f in zip(labels, filas)],
            suffix="", decimals=0, width=880, height=260,
        ),
    }
    tooltips = {
        "tiempo": [_tip(f, "promedio", "Tiempo promedio", _fmt(f["promedio_s"], " s", 2),
                        f"p95 {f['p95']} · {_num(f['pedidos'])} pedidos") for f in filas],
        "lentos": [_tip(f, "lentos", "Pedidos lentos (> 1 s)", _fmt(f["lentos_pct"], "%"),
                        f"de {_num(f['pedidos'])} pedidos") for f in filas],
        "base": [_tip(f, "base", "Latencia por consulta", _fmt(f["ms_por_consulta"], " ms"),
                      f"{_fmt(f['consultas_por_pedido'], ' consultas', 1)} por pedido") for f in filas],
        "volumen": [_tip(f, "pedidos", "Pedidos", _num(f["pedidos"]),
                         f"{_num(f['errores'])} con error 5xx") for f in filas],
    }
    tabla_periodos = [
        [f["nombre"], _num(f["pedidos"]), _fmt(f["promedio_s"], " s", 2), f["p95"],
         _fmt(f["lentos_pct"], "%"), _fmt(f["ms_por_consulta"], " ms")]
        for f in filas
    ]

    totales = resumir(data["totales"] or {})
    tiempo_total = sum(float(r.get("ms_total") or 0) for r in data["rutas"]) or 1
    rutas = []
    for row in data["rutas"]:
        r = resumir(row)
        r.update({"ruta": row["ruta"], "metodo": row["metodo"],
                  "impacto_pct": float(row.get("ms_total") or 0) * 100 / tiempo_total})
        rutas.append(r)

    return {
        "periodo": periodo_key if periodo_key in PERIODOS else "24h",
        "titulo": periodo["titulo"],
        "periodos": [(k, v["titulo"]) for k, v in PERIODOS.items()],
        "totales": totales,
        "hay_datos": totales["pedidos"] > 0,
        "graficos": graficos,
        "tooltips": tooltips,
        "tabla_periodos": tabla_periodos,
        "rutas": rutas,
        "fmt": _fmt,
        "num": _num,
    }


def _tip(fila, key, nombre, valor, nota):
    return {
        "title": fila["nombre"],
        "rows": [{"key": key, "name": nombre, "value": valor}],
        "note": nota,
        "aria": f"{fila['nombre']}: {nombre.lower()} {valor}",
    }
