import datetime

from extensions import get_db


def _to_minutes(value):
    if isinstance(value, datetime.time):
        return value.hour * 60 + value.minute
    text = str(value or "").strip()
    if not text:
        return None
    if len(text) == 5:
        text = f"{text}:00"
    parsed = datetime.time.fromisoformat(text)
    return parsed.hour * 60 + parsed.minute


def _normalize_time(value, field_name: str):
    text = str(value or "").strip()
    if not text:
        raise ValueError(f"{field_name} es requerido.")
    candidates = [text]
    if len(text) == 5:
        candidates.append(f"{text}:00")
    for raw in candidates:
        try:
            parsed = datetime.time.fromisoformat(raw)
            return parsed.strftime("%H:%M:%S")
        except ValueError:
            pass
    raise ValueError(f"{field_name} invalido. Use HH:MM.")


def _normalize_bloques(raw_bloques):
    if not raw_bloques:
        return []
    if not isinstance(raw_bloques, list):
        raise ValueError("bloques debe ser una lista.")

    parsed = []
    for i, bloque in enumerate(raw_bloques, start=1):
        if not isinstance(bloque, dict):
            raise ValueError(f"Bloque {i} invalido.")
        entrada = _normalize_time(
            bloque.get("entrada", bloque.get("hora_entrada")),
            f"Entrada bloque {i}",
        )
        salida = _normalize_time(
            bloque.get("salida", bloque.get("hora_salida")),
            f"Salida bloque {i}",
        )
        if _to_minutes(entrada) >= _to_minutes(salida):
            raise ValueError(f"Bloque {i}: entrada debe ser menor a salida.")
        parsed.append({
            "hora_entrada": entrada,
            "hora_salida": salida,
        })

    parsed.sort(key=lambda b: _to_minutes(b["hora_entrada"]))
    last_end = None
    for i, bloque in enumerate(parsed, start=1):
        start = _to_minutes(bloque["hora_entrada"])
        end = _to_minutes(bloque["hora_salida"])
        if last_end is not None and start < last_end:
            raise ValueError("No se permiten bloques superpuestos.")
        last_end = end
        bloque["orden"] = i
    return parsed


def create_excepcion(data: dict, bloques: list[dict] | None = None):
    bloques_norm = _normalize_bloques(bloques or [])
    tipo = str(data.get("tipo") or "").strip()
    if tipo == "CAMBIO_HORARIO" and not bloques_norm:
        raise ValueError("CAMBIO_HORARIO requiere al menos un bloque.")

    db = get_db()
    cursor = db.cursor()
    try:
        db.start_transaction()
        cursor.execute("""
            INSERT INTO empleado_excepciones
            (
                empresa_id,
                empleado_id,
                fecha,
                tipo,
                descripcion,
                anula_horario
            )
            VALUES (%s,%s,%s,%s,%s,%s)
        """, (
            data.get("empresa_id"),
            data.get("empleado_id"),
            data.get("fecha"),
            tipo,
            data.get("descripcion"),
            1 if data.get("anula_horario") else 0,
        ))
        excepcion_id = cursor.lastrowid

        if tipo == "CAMBIO_HORARIO":
            for b in bloques_norm:
                cursor.execute("""
                    INSERT INTO excepcion_bloques
                    (
                        empresa_id,
                        excepcion_id,
                        orden,
                        hora_entrada,
                        hora_salida
                    )
                    VALUES (%s,%s,%s,%s,%s)
                """, (
                    data.get("empresa_id"),
                    excepcion_id,
                    b["orden"],
                    b["hora_entrada"],
                    b["hora_salida"],
                ))

        db.commit()
        return excepcion_id
    except Exception:
        db.rollback()
        raise
    finally:
        cursor.close()
        db.close()


def update_excepcion(excepcion_id: int, data: dict, bloques: list[dict] | None = None):
    bloques_norm = _normalize_bloques(bloques or [])
    tipo = str(data.get("tipo") or "").strip()
    if tipo == "CAMBIO_HORARIO" and not bloques_norm:
        raise ValueError("CAMBIO_HORARIO requiere al menos un bloque.")

    db = get_db()
    cursor = db.cursor(dictionary=True)
    try:
        db.start_transaction()
        cursor.execute("""
            SELECT id
            FROM empleado_excepciones
            WHERE id = %s
            FOR UPDATE
        """, (excepcion_id,))
        if not cursor.fetchone():
            raise ValueError("Excepcion no encontrada.")

        cursor.execute("""
            UPDATE empleado_excepciones
            SET
                empresa_id = %s,
                empleado_id = %s,
                fecha = %s,
                tipo = %s,
                descripcion = %s,
                anula_horario = %s
            WHERE id = %s
        """, (
            data.get("empresa_id"),
            data.get("empleado_id"),
            data.get("fecha"),
            tipo,
            data.get("descripcion"),
            1 if data.get("anula_horario") else 0,
            excepcion_id,
        ))

        cursor.execute("DELETE FROM excepcion_bloques WHERE excepcion_id = %s", (excepcion_id,))
        if tipo == "CAMBIO_HORARIO":
            for b in bloques_norm:
                cursor.execute("""
                    INSERT INTO excepcion_bloques
                    (
                        empresa_id,
                        excepcion_id,
                        orden,
                        hora_entrada,
                        hora_salida
                    )
                    VALUES (%s,%s,%s,%s,%s)
                """, (
                    data.get("empresa_id"),
                    excepcion_id,
                    b["orden"],
                    b["hora_entrada"],
                    b["hora_salida"],
                ))

        db.commit()
        return True
    except Exception:
        db.rollback()
        raise
    finally:
        cursor.close()
        db.close()
