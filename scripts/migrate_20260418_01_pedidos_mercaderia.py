import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from extensions import get_db, init_db


DDL_ARTICULOS = """
CREATE TABLE IF NOT EXISTS articulos_catalogo_pedidos (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  codigo_articulo VARCHAR(64) NOT NULL,
  descripcion VARCHAR(255) NOT NULL,
  unidades_por_bulto INT UNSIGNED NOT NULL,
  bultos_por_pallet INT UNSIGNED NULL,
  presentacion_bulto VARCHAR(128) NULL,
  descripcion_presentacion_bulto VARCHAR(255) NULL,
  presentacion_unidad VARCHAR(128) NULL,
  descripcion_presentacion_unidad VARCHAR(255) NULL,
  marca VARCHAR(120) NULL,
  familia VARCHAR(120) NULL,
  sabor VARCHAR(120) NULL,
  division VARCHAR(120) NULL,
  codigo_barras VARCHAR(64) NULL,
  codigo_barras_unidad VARCHAR(64) NULL,
  activo_fuente TINYINT(1) NOT NULL DEFAULT 1,
  anulado_fuente TINYINT(1) NOT NULL DEFAULT 0,
  movil_fuente TINYINT(1) NOT NULL DEFAULT 1,
  tipo_producto_fuente VARCHAR(80) NOT NULL,
  habilitado_pedido TINYINT(1) NOT NULL DEFAULT 1,
  last_import_at DATETIME NOT NULL,
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  UNIQUE KEY uk_articulos_catalogo_pedidos_codigo (codigo_articulo),
  KEY idx_articulos_catalogo_pedidos_habilitado (habilitado_pedido),
  KEY idx_articulos_catalogo_pedidos_descripcion (descripcion)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;
"""

DDL_PEDIDOS = """
CREATE TABLE IF NOT EXISTS pedidos_mercaderia (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  empresa_id INT NOT NULL,
  empleado_id INT NOT NULL,
  periodo_year SMALLINT NOT NULL,
  periodo_month TINYINT UNSIGNED NOT NULL,
  fecha_pedido DATE NOT NULL,
  estado ENUM('pendiente', 'aprobado', 'rechazado', 'cancelado') NOT NULL DEFAULT 'pendiente',
  resuelto_by_usuario_id INT NULL,
  resuelto_at DATETIME NULL,
  motivo_rechazo VARCHAR(255) NULL,
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  UNIQUE KEY uk_pedidos_mercaderia_empleado_periodo (empleado_id, periodo_year, periodo_month),
  KEY idx_pedidos_mercaderia_empresa_periodo (empresa_id, periodo_year, periodo_month),
  KEY idx_pedidos_mercaderia_estado (estado),
  KEY idx_pedidos_mercaderia_resuelto_by (resuelto_by_usuario_id),
  CONSTRAINT fk_pedidos_mercaderia_empresa FOREIGN KEY (empresa_id) REFERENCES empresas (id),
  CONSTRAINT fk_pedidos_mercaderia_empleado_empresa FOREIGN KEY (empleado_id, empresa_id)
    REFERENCES empleados (id, empresa_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;
"""

DDL_PEDIDOS_ITEMS = """
CREATE TABLE IF NOT EXISTS pedidos_mercaderia_items (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  pedido_id BIGINT UNSIGNED NOT NULL,
  articulo_id BIGINT UNSIGNED NOT NULL,
  cantidad_bultos INT UNSIGNED NOT NULL,
  codigo_articulo_snapshot VARCHAR(64) NOT NULL,
  descripcion_snapshot VARCHAR(255) NOT NULL,
  unidades_por_bulto_snapshot INT UNSIGNED NOT NULL,
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  UNIQUE KEY uk_pedidos_mercaderia_items_pedido_articulo (pedido_id, articulo_id),
  KEY idx_pedidos_mercaderia_items_articulo (articulo_id),
  CONSTRAINT fk_pedidos_mercaderia_items_pedido FOREIGN KEY (pedido_id) REFERENCES pedidos_mercaderia (id),
  CONSTRAINT fk_pedidos_mercaderia_items_articulo FOREIGN KEY (articulo_id) REFERENCES articulos_catalogo_pedidos (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;
"""


def migrate():
    init_db()
    db = get_db()
    cursor = db.cursor()
    try:
        cursor.execute(DDL_ARTICULOS)
        cursor.execute(DDL_PEDIDOS)
        cursor.execute(DDL_PEDIDOS_ITEMS)
        db.commit()
        print("[done] migration 20260418_01_pedidos_mercaderia")
    finally:
        cursor.close()
        db.close()


if __name__ == "__main__":
    migrate()
