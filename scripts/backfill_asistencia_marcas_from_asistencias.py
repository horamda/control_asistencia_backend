import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import app as app_module
from repositories.asistencia_marca_repository import backfill_from_asistencias


def main():
    app_module.create_app()
    inserted_ingresos, inserted_egresos = backfill_from_asistencias()
    print(f"Backfill completo. Ingresos: {inserted_ingresos}, Egresos: {inserted_egresos}")


if __name__ == "__main__":
    main()
