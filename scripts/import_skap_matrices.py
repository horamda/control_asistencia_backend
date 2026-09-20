"""Import operational workbooks. Default: read-only preview. --apply creates a batch."""
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from db import init_orm
from repositories import skap_matriz_repository as repo
from services.skap_excel_service import match_employees, name_key, parse_workbook


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('files',nargs='+',type=Path)
    parser.add_argument('--empresa-id',required=True,type=int)
    parser.add_argument('--mapping',type=Path,help='JSON: original names -> existing employee IDs, manually confirmed')
    parser.add_argument('--exclude-sheet',action='append',default=[])
    parser.add_argument('--apply',action='store_true')
    parser.add_argument('--report',type=Path,required=True,help='Private JSON report outside version control')
    args = parser.parse_args()
    init_orm()
    staff = repo.employee_options(args.empresa_id)
    branches = repo.branch_options(args.empresa_id)
    aliases = repo.name_aliases(args.empresa_id)
    manual = json.loads(args.mapping.read_text(encoding='utf-8')) if args.mapping else {}
    manual = {' '.join(name_key(k)):v for k,v in manual.items()}
    payloads = []
    for file in args.files:
        payload = parse_workbook(file.read_bytes(),file.name)
        overrides = {ev['clave']:manual[' '.join(name_key(ev['nombre_original']))]
                     for ev in payload['evaluaciones'] if ' '.join(name_key(ev['nombre_original'])) in manual}
        match_employees(payload,staff,branches,overrides,aliases)
        for ev in payload['evaluaciones']:
            ev['excluir'] = ev['hoja'].strip() in args.exclude_sheet
            if ev['excluir']:
                ev['motivo_exclusion'] = 'Exclusión indicada por el operador.'
        selected = [ev for ev in payload['evaluaciones'] if not ev['excluir']]
        if any(ev['vinculo'] != 'resuelto' for ev in selected):
            payloads.append({'payload':payload,'error':'Quedan legajos por resolver.'})
        else:
            payloads.append({'payload':payload})
    args.report.parent.mkdir(parents=True,exist_ok=True)
    args.report.write_text(repo.dumps(payloads),encoding='utf-8')
    if any(p.get('error') for p in payloads):
        raise SystemExit('No se cargó ningún archivo: revise los vínculos del informe.')
    actor = {'id':None,'empresa_id':args.empresa_id,'rol':'admin','origen':'CLI autorizado'}
    for item in payloads:
        payload = item['payload']
        selected = {ev['clave'] for ev in payload['evaluaciones'] if not ev['excluir']}
        if args.apply:
            batch = repo.save_preview(payload,args.empresa_id,None)
            item['importacion_id'] = batch
            # Each file is atomic; the report is saved after every successful batch.
            item['resultado'] = repo.commit_import(batch,payload,actor,selected)
            args.report.write_text(repo.dumps(payloads),encoding='utf-8')
        print(f"{payload['archivo']}: {len(selected)} evaluaciones {'procesadas' if args.apply else 'listas para importar'}.")


if __name__ == '__main__':
    main()
