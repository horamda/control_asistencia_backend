"""Geometria de graficos SVG renderizados en el servidor (sin librerias JS).

Las funciones devuelven coordenadas listas para dibujar en Jinja: escalas con
ticks redondos, trazos de lineas (cortados donde falta el dato), columnas con
extremo redondeado y areas de interaccion por punto para el tooltip.
"""
import math

_END_LABEL_MIN_GAP = 14  # px: con menos separacion las etiquetas finales se pisan


def _nice_ticks(low: float, high: float, target: int = 4) -> list[float]:
    if high <= low:
        high = low + 1
    raw = (high - low) / target
    magnitude = 10 ** math.floor(math.log10(raw))
    step = magnitude * 10
    for factor in (1, 2, 2.5, 5, 10):
        if factor * magnitude >= raw:
            step = factor * magnitude
            break
    first = math.floor(low / step) * step
    last = math.ceil(high / step) * step
    count = int(round((last - first) / step))
    return [round(first + i * step, 6) for i in range(count + 1)]


def _format_tick(value: float, suffix: str) -> str:
    return f"{value:g}{suffix}"


def _format_value(value: float, suffix: str, decimals: int = 1) -> str:
    return f"{value:.{decimals}f}{suffix}"


def _plot_box(width: int, height: int, *, left: int, right: int, top: int, bottom: int) -> dict:
    return {"left": left, "top": top, "right": width - right, "bottom": height - bottom}


def line_chart(
    labels: list[dict],
    series: list[dict],
    *,
    y_min: float | None = 0,
    y_max: float | None = None,
    suffix: str = "%",
    decimals: int = 1,
    width: int = 560,
    height: int = 240,
) -> dict:
    """labels: [{"label", "sub"}]; series: [{"key", "name", "values": [float|None]}]."""
    plot = _plot_box(width, height, left=44, right=64, top=14, bottom=44)
    values = [v for s in series for v in s["values"] if v is not None]
    if not values:
        return {"empty": True, "width": width, "height": height}
    low = max(0.0, min(values) - 5) if y_min is None else y_min
    high = max(values) if y_max is None else max(y_max, max(values))
    ticks = _nice_ticks(low, max(high, low + 1e-9) * (1 if y_max is not None else 1.1))
    if y_max is not None:
        ticks = [t for t in ticks if t <= y_max] or ticks
    t_low, t_high = ticks[0], ticks[-1]

    def y_of(value: float) -> float:
        span = (t_high - t_low) or 1
        return round(plot["bottom"] - (value - t_low) / span * (plot["bottom"] - plot["top"]), 2)

    count = len(labels)
    step = (plot["right"] - plot["left"]) / max(count - 1, 1)

    def x_of(index: int) -> float:
        return round(plot["left"] + index * step if count > 1 else (plot["left"] + plot["right"]) / 2, 2)

    out_series = []
    for item in series:
        points = []
        segments, current = [], []
        for index, value in enumerate(item["values"]):
            if value is None:
                if current:
                    segments.append(current)
                current = []
                continue
            point = {"x": x_of(index), "y": y_of(value), "value": value, "index": index}
            points.append(point)
            current.append(point)
        if current:
            segments.append(current)
        path = " ".join(
            "M" + " L".join(f"{p['x']},{p['y']}" for p in segment) for segment in segments
        )
        end = points[-1] if points else None
        out_series.append({
            **{k: v for k, v in item.items() if k != "values"},
            "path": path,
            "points": points,
            "end": end,
            "end_label": _format_value(end["value"], suffix, decimals) if end else "",
        })

    # Etiquetas directas al final de cada serie solo si no se pisan.
    ends = sorted((s["end"]["y"] for s in out_series if s["end"]), key=float)
    show_end_labels = all(b - a >= _END_LABEL_MIN_GAP for a, b in zip(ends, ends[1:]))

    half = step / 2 if count > 1 else (plot["right"] - plot["left"]) / 2
    columns = [
        {
            "index": i,
            "x": x_of(i),
            "x0": round(max(plot["left"] - 12, x_of(i) - half), 2),
            "width": round(min(x_of(i) + half, plot["right"] + 12) - max(plot["left"] - 12, x_of(i) - half), 2),
        }
        for i in range(count)
    ]
    return {
        "empty": False,
        "width": width,
        "height": height,
        "plot": plot,
        "y_ticks": [{"y": y_of(t), "label": _format_tick(t, suffix)} for t in ticks],
        "x_labels": [{"x": x_of(i), **label} for i, label in enumerate(labels)],
        "series": out_series,
        "show_end_labels": show_end_labels,
        "columns": columns,
    }


def _rounded_top_bar(x0: float, x1: float, y_top: float, y_base: float, radius: float = 4) -> str:
    """Columna con extremo de datos redondeado y base recta."""
    radius = max(0.0, min(radius, (x1 - x0) / 2, y_base - y_top))
    return (
        f"M{x0},{y_base} V{y_top + radius} Q{x0},{y_top} {x0 + radius},{y_top} "
        f"H{x1 - radius} Q{x1},{y_top} {x1},{y_top + radius} V{y_base} Z"
    )


def column_chart(bars: list[dict], *, suffix: str = "%", decimals: int = 1, width: int = 560, height: int = 240) -> dict:
    """bars: [{"label", "value": float|None, ...}]; una sola serie."""
    plot = _plot_box(width, height, left=44, right=16, top=22, bottom=30)
    values = [b["value"] for b in bars if b["value"] is not None]
    if not values:
        return {"empty": True, "width": width, "height": height}
    ticks = _nice_ticks(0, max(values) * 1.1 or 1)
    t_high = ticks[-1] or 1
    band = (plot["right"] - plot["left"]) / len(bars)
    bar_width = min(24, band * 0.6)

    def y_of(value: float) -> float:
        return round(plot["bottom"] - value / t_high * (plot["bottom"] - plot["top"]), 2)

    out = []
    for index, bar in enumerate(bars):
        center = plot["left"] + band * (index + 0.5)
        x0, x1 = round(center - bar_width / 2, 2), round(center + bar_width / 2, 2)
        value = bar["value"]
        y_top = y_of(value) if value is not None else plot["bottom"]
        out.append({
            **bar,
            "x": round(center, 2),
            "path": _rounded_top_bar(x0, x1, y_top, plot["bottom"]) if value else "",
            "y_top": y_top,
            "value_label": _format_value(value, suffix, decimals) if value is not None else "s/d",
            "hit_x0": round(center - band / 2, 2),
            "hit_width": round(band, 2),
        })
    return {
        "empty": False,
        "width": width,
        "height": height,
        "plot": plot,
        "y_ticks": [{"y": y_of(t), "label": _format_tick(t, suffix)} for t in ticks],
        "bars": out,
        # Con muchas columnas los valores se superponen: quedan en el tooltip y la tabla.
        "show_values": len(out) <= 12,
    }
