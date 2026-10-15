"""Cierra jornadas con ingreso y sin egreso de dias anteriores (egreso automatico).

Uso:
    python scripts/cerrar_jornadas_sin_egreso.py            # simulacion, no escribe
    python scripts/cerrar_jornadas_sin_egreso.py --aplicar  # cierra las jornadas
La tarea programada (utils/egreso_automatico_scheduler.py) hace lo mismo cada noche.
"""
import json
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from extensions import init_db
from services.egreso_automatico_service import cerrar_jornadas_abiertas

if __name__ == "__main__":
    init_db()
    aplicar = "--aplicar" in sys.argv
    resumen = cerrar_jornadas_abiertas(dry_run=not aplicar)
    print(("APLICADO" if aplicar else "SIMULACION (use --aplicar para escribir)") + ":")
    print(json.dumps({k: v for k, v in resumen.items() if k != "detalle"}, indent=2))
    for item in resumen["detalle"][:10]:
        print("  ", item)
