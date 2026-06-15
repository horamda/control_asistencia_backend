from __future__ import annotations

import argparse
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from extensions import init_db
from services.skap_seed_service import (
    build_example_evaluacion_payload,
    importar_preguntas_desde_csv,
    seed_base_questions,
)


def _parse_sector_ids(values: list[str] | None) -> list[int]:
    result: list[int] = []
    for value in values or []:
        for item in str(value or "").split(","):
            item = item.strip()
            if item:
                result.append(int(item))
    return result


def _build_parser():
    parser = argparse.ArgumentParser(
        description="Carga inicial de preguntas SKAP y ejemplo de payload de evaluacion."
    )
    parser.add_argument("--empresa-id", type=int, help="Limita la carga a una empresa.")
    parser.add_argument(
        "--sector-id",
        action="append",
        help="Limita la carga a uno o mas sectores. Acepta multiples usos o coma: --sector-id 1,2.",
    )
    parser.add_argument(
        "--include-inactive-sectors",
        action="store_true",
        help="Incluye sectores inactivos al cargar preguntas base.",
    )
    parser.add_argument(
        "--reactivate",
        action="store_true",
        help="Reactiva preguntas existentes inactivas si coinciden por sector, categoria y descripcion.",
    )
    parser.add_argument("--dry-run", action="store_true", help="Simula la carga sin escribir en la base.")
    parser.add_argument("--csv", type=pathlib.Path, help="Importa preguntas desde un CSV en lugar del set base.")
    parser.add_argument(
        "--example-only",
        action="store_true",
        help="No carga preguntas; solo imprime el payload de evaluacion de ejemplo.",
    )
    parser.add_argument(
        "--no-example",
        action="store_true",
        help="No imprime el payload de evaluacion de ejemplo.",
    )
    parser.add_argument("--example-sector-id", type=int, help="Sector usado para el payload de ejemplo.")
    parser.add_argument("--example-empleado-id", type=int, help="Empleado objetivo usado para el payload de ejemplo.")
    parser.add_argument("--anio", type=int, help="Anio del payload de evaluacion de ejemplo.")
    return parser


def main() -> int:
    args = _build_parser().parse_args()
    init_db()

    if not args.example_only:
        if args.csv:
            with args.csv.open("rb") as fh:
                result = importar_preguntas_desde_csv(
                    fh,
                    reactivate=args.reactivate,
                    dry_run=args.dry_run,
                )
        else:
            result = seed_base_questions(
                empresa_id=args.empresa_id,
                sector_ids=_parse_sector_ids(args.sector_id),
                include_inactive_sectors=args.include_inactive_sectors,
                reactivate=args.reactivate,
                dry_run=args.dry_run,
            )
        print(json.dumps({"seed": result}, ensure_ascii=False, indent=2, default=str))

    if not args.no_example:
        try:
            example = build_example_evaluacion_payload(
                sector_id=args.example_sector_id or (_parse_sector_ids(args.sector_id)[:1] or [None])[0],
                empleado_id=args.example_empleado_id,
                anio=args.anio,
            )
            print(json.dumps({"example": example}, ensure_ascii=False, indent=2, default=str))
        except Exception as exc:
            print(json.dumps({"example_error": str(exc)}, ensure_ascii=False, indent=2))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
