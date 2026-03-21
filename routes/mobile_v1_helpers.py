"""
Helpers puros para mobile_v1_routes.
Solo lógica de parseo, validación y cálculo — sin llamadas a repositorios ni servicios.
Estos helpers son seguros de testear en aislamiento y no requieren mocking de DB.
"""
import datetime
import math


DEFAULT_INTERVALO_MINIMO_ENTRE_FICHADAS_MIN = 60
TIPO_MARCA_VALUES = {"jornada", "desayuno", "almuerzo", "merienda", "otro"}


# ---------------------------------------------------------------------------
# Utilidades de fecha/hora
# ---------------------------------------------------------------------------

def _today_iso():
    return datetime.date.today().isoformat()


def _now_hhmm():
    return datetime.datetime.now().strftime("%H:%M")


def _parse_date(value: str | None):
    raw = (value or "").strip()
    if not raw:
        return None
    datetime.date.fromisoformat(raw)
    return raw


def _parse_hhmm(value: str | None):
    raw = (value or "").strip()
    if not raw:
        return None
    candidates = [raw]
    if len(raw) == 5:
        candidates.append(f"{raw}:00")
    for candidate in candidates:
        try:
            parsed = datetime.time.fromisoformat(candidate)
            return parsed.strftime("%H:%M")
        except ValueError:
            pass
    raise ValueError("Hora invalida. Use HH:MM.")


def _parse_db_datetime(value):
    if value is None:
        return None
    if isinstance(value, datetime.datetime):
        return value
    text = str(value).strip()
    if not text:
        return None
    try:
        return datetime.datetime.fromisoformat(text.replace("Z", "+00:00")).replace(tzinfo=None)
    except ValueError:
        return None


def _to_hhmm(value):
    if value is None:
        return None
    if isinstance(value, datetime.timedelta):
        mins = int(value.total_seconds() // 60)
        return f"{(mins // 60) % 24:02d}:{mins % 60:02d}"
    if hasattr(value, "strftime"):
        return value.strftime("%H:%M")
    text = str(value).strip()
    if not text:
        return None
    if len(text) >= 5:
        return text[:5]
    return text


def _to_date_str(value):
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)


def _to_minutes(value):
    if value is None:
        return None
    if isinstance(value, datetime.timedelta):
        return int(value.total_seconds() // 60)
    if hasattr(value, "hour") and hasattr(value, "minute"):
        return int(value.hour) * 60 + int(value.minute)
    text = str(value).strip()
    if not text:
        return None
    try:
        hhmm = _parse_hhmm(text)
    except ValueError:
        return None
    if not hhmm:
        return None
    parts = hhmm.split(":")
    return int(parts[0]) * 60 + int(parts[1])


# ---------------------------------------------------------------------------
# Parsers de entrada (JSON/form)
# ---------------------------------------------------------------------------

def _parse_float(value, label):
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{label} invalido.") from exc


def _parse_int(value, label: str, default=None):
    if value is None or value == "":
        return default
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{label} invalido.") from exc


def _parse_bool(value, label: str, default=False):
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    raw = str(value).strip().lower()
    if raw in {"1", "true", "t", "yes", "y", "si", "sí", "on"}:
        return True
    if raw in {"0", "false", "f", "no", "off", ""}:
        return False
    raise ValueError(f"{label} invalido. Use true/false.")


def _parse_tipo_marca(value, *, default=None):
    raw = str(value or "").strip().lower()
    if not raw:
        return default
    if raw not in TIPO_MARCA_VALUES:
        raise ValueError("tipo_marca invalido. Use jornada, desayuno, almuerzo, merienda u otro.")
    return raw


def _safe_int(value):
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


# ---------------------------------------------------------------------------
# Validadores puros
# ---------------------------------------------------------------------------

def _validate_geo(lat, lon):
    if lat is not None and (lat < -90 or lat > 90):
        raise ValueError("Latitud fuera de rango.")
    if lon is not None and (lon < -180 or lon > 180):
        raise ValueError("Longitud fuera de rango.")


def _validar_cooldown_scan(ultima_marca: dict | None, cooldown_segundos: int):
    if not ultima_marca or cooldown_segundos <= 0:
        return

    last_dt = _parse_db_datetime(ultima_marca.get("fecha_creacion"))
    if last_dt is None:
        return

    now = datetime.datetime.now()
    elapsed = (now - last_dt).total_seconds()
    if elapsed < 0:
        return
    if elapsed < cooldown_segundos:
        restante = int(math.ceil(cooldown_segundos - elapsed))
        raise ValueError(f"Escaneo duplicado detectado. Espere {restante} segundos para volver a fichar.")


def _validar_intervalo_minimo_marcas(
    ultima_marca: dict | None,
    hora_actual: str | None,
    minutos_minimos: int = DEFAULT_INTERVALO_MINIMO_ENTRE_FICHADAS_MIN,
):
    if not ultima_marca or not hora_actual or minutos_minimos <= 0:
        return

    minutos_actual = _to_minutes(hora_actual)
    minutos_ultima = _to_minutes(ultima_marca.get("hora"))
    if minutos_actual is None or minutos_ultima is None:
        return

    diferencia = minutos_actual - minutos_ultima
    if diferencia < 0:
        raise ValueError("Secuencia invalida de marcas. La hora informada debe ser posterior a la ultima marca.")
    if diferencia < minutos_minimos:
        raise ValueError(
            f"Secuencia invalida de marcas. Debe esperar al menos {minutos_minimos} minutos entre fichadas."
        )


# ---------------------------------------------------------------------------
# Helpers de geolocalización (puros — sin repo)
# ---------------------------------------------------------------------------

def _haversine_m(lat1, lon1, lat2, lon2):
    r = 6371000.0
    p1 = math.radians(lat1)
    p2 = math.radians(lat2)
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = math.sin(dlat / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlon / 2) ** 2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return r * c


def _geo_ref_from_qr_payload(qr_payload):
    geo_ref = qr_payload.get("geo_ref") if isinstance(qr_payload, dict) else None
    if not isinstance(geo_ref, dict):
        return None
    lat = geo_ref.get("lat")
    lon = geo_ref.get("lon")
    radio_m = geo_ref.get("radio_m")
    if lat is None or lon is None or radio_m is None:
        return None
    try:
        return {
            "lat": float(lat),
            "lon": float(lon),
            "radio_m": float(radio_m),
            "sucursal_id": geo_ref.get("sucursal_id"),
        }
    except (TypeError, ValueError):
        return None


# ---------------------------------------------------------------------------
# Helpers de lógica de fichadas (puros)
# ---------------------------------------------------------------------------

def _get_scan_cooldown_segundos(config: dict | None):
    if not config:
        return 60
    raw = config.get("cooldown_scan_segundos")
    if raw is None:
        return 60
    try:
        return max(0, int(raw))
    except (TypeError, ValueError):
        return 60


def _get_intervalo_minimo_fichadas_min(config: dict | None):
    if not config:
        return DEFAULT_INTERVALO_MINIMO_ENTRE_FICHADAS_MIN
    raw = config.get("intervalo_minimo_fichadas_minutos")
    if raw is None:
        return DEFAULT_INTERVALO_MINIMO_ENTRE_FICHADAS_MIN
    try:
        return max(0, int(raw))
    except (TypeError, ValueError):
        return DEFAULT_INTERVALO_MINIMO_ENTRE_FICHADAS_MIN


def _decidir_accion_scan(accion_qr: str, resumen: dict | None, ultima_marca: dict | None):
    if accion_qr in {"ingreso", "egreso"}:
        accion = accion_qr
    elif ultima_marca:
        accion = "egreso" if str(ultima_marca.get("accion")) == "ingreso" else "ingreso"
    elif not resumen or resumen.get("hora_entrada") is None:
        accion = "ingreso"
    elif resumen.get("hora_salida") is None:
        accion = "egreso"
    else:
        # Si no hay marcas atomicas y el resumen del dia esta cerrado, asumimos nuevo ciclo.
        accion = "ingreso"

    if ultima_marca:
        ultima_accion = str(ultima_marca.get("accion") or "").strip().lower()
        if ultima_accion == accion:
            raise ValueError(f"Secuencia invalida de marcas. Ultima accion: {ultima_accion}.")
        if accion == "egreso" and ultima_accion != "ingreso":
            raise ValueError("No hay fichada de entrada para esa fecha.")
        return accion

    if accion == "egreso" and (not resumen or resumen.get("hora_entrada") is None):
        raise ValueError("No hay fichada de entrada para esa fecha.")
    if (
        accion == "ingreso"
        and resumen
        and resumen.get("hora_entrada") is not None
        and resumen.get("hora_salida") is None
    ):
        raise ValueError("Ya hay un ingreso abierto para esa fecha.")
    return accion


def _hora_entrada_para_egreso(resumen: dict | None, ultima_marca: dict | None):
    if ultima_marca and str(ultima_marca.get("accion")) == "ingreso":
        return _to_hhmm(ultima_marca.get("hora"))
    if resumen:
        return _to_hhmm(resumen.get("hora_entrada"))
    return None
