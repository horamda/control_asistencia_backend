"""Inteligencia artificial: configuración (tabla existente system_config) y registro de uso (ia_uso)."""

from extensions import get_db

PREFIJO = "ia_"


def get_config() -> dict[str, str]:
    db = get_db()
    cur = db.cursor(dictionary=True)
    try:
        cur.execute(
            "SELECT config_key, config_value FROM system_config WHERE config_key LIKE %s",
            (PREFIJO + "%",),
        )
        return {r["config_key"]: r["config_value"] for r in cur.fetchall() or []}
    finally:
        cur.close(); db.close()


def set_config(valores: dict[str, str]):
    db = get_db()
    cur = db.cursor()
    try:
        cur.executemany(
            """
            INSERT INTO system_config (config_key, config_value) VALUES (%s, %s)
            ON DUPLICATE KEY UPDATE config_value = VALUES(config_value)
            """,
            [(str(k), str(v)) for k, v in valores.items() if str(k).startswith(PREFIJO)],
        )
        db.commit()
    finally:
        cur.close(); db.close()


def registrar_uso(data: dict):
    db = get_db()
    cur = db.cursor()
    try:
        cur.execute(
            """
            INSERT INTO ia_uso
                (usuario_id, proveedor, modelo, operacion, estado, error_tipo,
                 tokens_entrada, tokens_salida, costo_usd, duracion_ms)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            """,
            (
                data.get("usuario_id"), data["proveedor"], data["modelo"][:120],
                data["operacion"], data["estado"], data.get("error_tipo"),
                int(data.get("tokens_entrada") or 0), int(data.get("tokens_salida") or 0),
                data.get("costo_usd") or 0, int(data.get("duracion_ms") or 0),
            ),
        )
        db.commit()
    finally:
        cur.close(); db.close()


def resumen_uso() -> dict:
    """Generaciones de hoy y consumo del mes en curso (las pruebas de conexión no cuentan como generación)."""
    db = get_db()
    cur = db.cursor(dictionary=True)
    try:
        cur.execute(
            """
            SELECT
              COALESCE(SUM(creado_en >= CURDATE() AND operacion <> 'prueba'), 0) AS generaciones_hoy,
              COALESCE(SUM(operacion <> 'prueba'), 0) AS generaciones_mes,
              COALESCE(SUM(estado = 'error'), 0) AS errores_mes,
              COALESCE(SUM(tokens_entrada), 0) AS tokens_entrada_mes,
              COALESCE(SUM(tokens_salida), 0) AS tokens_salida_mes,
              COALESCE(SUM(costo_usd), 0) AS costo_mes
            FROM ia_uso
            WHERE creado_en >= DATE_FORMAT(CURDATE(), '%Y-%m-01')
            """
        )
        row = cur.fetchone() or {}
        return {
            "generaciones_hoy": int(row.get("generaciones_hoy") or 0),
            "generaciones_mes": int(row.get("generaciones_mes") or 0),
            "errores_mes": int(row.get("errores_mes") or 0),
            "tokens_entrada_mes": int(row.get("tokens_entrada_mes") or 0),
            "tokens_salida_mes": int(row.get("tokens_salida_mes") or 0),
            "costo_mes": float(row.get("costo_mes") or 0),
        }
    finally:
        cur.close(); db.close()


def ultimos_usos(limite: int = 30) -> list[dict]:
    db = get_db()
    cur = db.cursor(dictionary=True)
    try:
        cur.execute(
            """
            SELECT u.creado_en, u.proveedor, u.modelo, u.operacion, u.estado, u.error_tipo,
                   u.tokens_entrada, u.tokens_salida, u.costo_usd, u.duracion_ms,
                   w.usuario AS usuario
            FROM ia_uso u
            LEFT JOIN usuarios w ON w.id = u.usuario_id
            ORDER BY u.id DESC
            LIMIT %s
            """,
            (int(limite),),
        )
        return cur.fetchall() or []
    finally:
        cur.close(); db.close()
