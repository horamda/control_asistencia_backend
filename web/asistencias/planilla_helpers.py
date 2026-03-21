import datetime


DEFAULT_INTERVALO_MINIMO_ENTRE_FICHADAS_MIN = 60


def _to_hhmm(value):
    if value is None:
        return None
    if hasattr(value, "strftime"):
        return value.strftime("%H:%M")
    text = str(value).strip()
    if not text:
        return None
    candidates = [text]
    if len(text) >= 7 and text[1] == ":":
        candidates.append(f"0{text}")
    if len(text) == 4 and text[1] == ":":
        candidates.append(f"0{text}")
    if len(text) == 5:
        candidates.append(f"{text}:00")
    for candidate in candidates:
        try:
            parsed = datetime.time.fromisoformat(candidate)
            return parsed.strftime("%H:%M")
        except ValueError:
            continue
    parts = text.split(":")
    if len(parts) >= 2 and parts[0].isdigit() and parts[1].isdigit():
        return f"{int(parts[0]):02d}:{int(parts[1]):02d}"
    return text[:5] if len(text) >= 5 else text


def _parse_hhmm(value: str | None):
    raw = (value or "").strip()
    if not raw:
        raise ValueError("Hora requerida. Use HH:MM.")
    candidates = [raw]
    if len(raw) == 5:
        candidates.append(f"{raw}:00")
    for candidate in candidates:
        try:
            parsed = datetime.time.fromisoformat(candidate)
            return parsed.strftime("%H:%M")
        except ValueError:
            continue
    raise ValueError("Hora invalida. Use HH:MM.")


def _to_date_iso(value):
    if value is None:
        return None
    if hasattr(value, "isoformat"):
        return value.isoformat()
    text = str(value).strip()
    return text or None


def _to_minutes(hhmm: str | None):
    if not hhmm:
        return None
    try:
        hours, mins = hhmm.split(":")
        return int(hours) * 60 + int(mins)
    except (ValueError, TypeError):
        return None


def _to_bool_flag(value):
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return int(value) != 0
    text = str(value).strip().lower()
    if text in {"1", "true", "t", "si", "s", "yes", "y"}:
        return True
    if text in {"0", "false", "f", "no", "n"}:
        return False
    return None


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


def _build_planilla_pares(marcas: list[dict], intervalo_minimo_fichadas: int):
    pares = []
    errores = []
    ultima_accion = None
    ultima_hora = None
    ingreso_pendiente = None

    for marca in marcas:
        accion = str(marca.get("accion") or "").strip().lower()
        hora = _to_hhmm(marca.get("hora"))
        asistencia_id = marca.get("asistencia_id")
        marca_id = marca.get("id")
        gps_ok = _to_bool_flag(marca.get("gps_ok"))
        hora_min = _to_minutes(hora)

        if accion not in {"ingreso", "egreso"}:
            continue

        if ultima_hora and hora_min is not None:
            ultima_hora_min = _to_minutes(ultima_hora)
            if ultima_hora_min is not None:
                delta = hora_min - ultima_hora_min
                if delta < 0:
                    errores.append(
                        f"Orden horario invalido entre {ultima_accion} {ultima_hora} y {accion} {hora}."
                    )
                elif intervalo_minimo_fichadas > 0 and delta < intervalo_minimo_fichadas:
                    errores.append(
                        f"Intervalo corto: {ultima_accion} {ultima_hora} -> {accion} {hora} ({delta} min)."
                    )

        if accion == "ingreso":
            if ingreso_pendiente:
                pares.append(
                    {
                        "ingreso": ingreso_pendiente["hora"],
                        "egreso": None,
                        "asistencia_id": ingreso_pendiente.get("asistencia_id"),
                        "ingreso_marca_id": ingreso_pendiente.get("marca_id"),
                        "ingreso_gps_ok": ingreso_pendiente.get("gps_ok"),
                        "egreso_marca_id": None,
                        "egreso_gps_ok": None,
                        "error": "Ingreso sin egreso.",
                    }
                )
                errores.append("Ingreso sin egreso.")
            ingreso_pendiente = {
                "hora": hora,
                "asistencia_id": asistencia_id,
                "marca_id": marca_id,
                "gps_ok": gps_ok,
            }
        else:
            if not ingreso_pendiente:
                pares.append(
                    {
                        "ingreso": None,
                        "egreso": hora,
                        "asistencia_id": asistencia_id,
                        "ingreso_marca_id": None,
                        "ingreso_gps_ok": None,
                        "egreso_marca_id": marca_id,
                        "egreso_gps_ok": gps_ok,
                        "error": "Egreso sin ingreso previo.",
                    }
                )
                errores.append("Egreso sin ingreso previo.")
            else:
                par_error = None
                ingreso_min = _to_minutes(ingreso_pendiente["hora"])
                if ingreso_min is not None and hora_min is not None and hora_min < ingreso_min:
                    par_error = "Egreso anterior al ingreso."
                    errores.append(par_error)
                pares.append(
                    {
                        "ingreso": ingreso_pendiente["hora"],
                        "egreso": hora,
                        "asistencia_id": ingreso_pendiente.get("asistencia_id") or asistencia_id,
                        "ingreso_marca_id": ingreso_pendiente.get("marca_id"),
                        "ingreso_gps_ok": ingreso_pendiente.get("gps_ok"),
                        "egreso_marca_id": marca_id,
                        "egreso_gps_ok": gps_ok,
                        "error": par_error,
                    }
                )
                ingreso_pendiente = None

        ultima_accion = accion
        ultima_hora = hora

    if ingreso_pendiente:
        pares.append(
            {
                "ingreso": ingreso_pendiente["hora"],
                "egreso": None,
                "asistencia_id": ingreso_pendiente.get("asistencia_id"),
                "ingreso_marca_id": ingreso_pendiente.get("marca_id"),
                "ingreso_gps_ok": ingreso_pendiente.get("gps_ok"),
                "egreso_marca_id": None,
                "egreso_gps_ok": None,
                "error": "Ingreso sin egreso.",
            }
        )
        errores.append("Ingreso sin egreso.")

    # Unifica mensajes repetidos manteniendo orden.
    dedup = []
    seen = set()
    for err in errores:
        if err in seen:
            continue
        seen.add(err)
        dedup.append(err)
    return pares, dedup


def _build_marcas_from_asistencias(asistencias: list[dict]):
    marcas = []
    for asistencia in asistencias or []:
        asistencia_id = asistencia.get("id")
        fecha = _to_date_iso(asistencia.get("fecha"))

        hora_entrada = _to_hhmm(asistencia.get("hora_entrada"))
        if hora_entrada:
            marcas.append(
                {
                    "id": None,
                    "asistencia_id": asistencia_id,
                    "fecha": fecha,
                    "hora": hora_entrada,
                    "accion": "ingreso",
                    "gps_ok": asistencia.get("gps_ok_entrada"),
                }
            )

        hora_salida = _to_hhmm(asistencia.get("hora_salida"))
        if hora_salida:
            marcas.append(
                {
                    "id": None,
                    "asistencia_id": asistencia_id,
                    "fecha": fecha,
                    "hora": hora_salida,
                    "accion": "egreso",
                    "gps_ok": asistencia.get("gps_ok_salida"),
                }
            )
    return marcas


