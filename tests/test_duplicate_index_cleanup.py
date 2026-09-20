import copy
import importlib.util
from pathlib import Path
import pytest

spec = importlib.util.spec_from_file_location('cleanup_indexes', Path(__file__).parents[1] / 'scripts/migrate_20260920_01_duplicate_indexes.py')
migration = importlib.util.module_from_spec(spec)
spec.loader.exec_module(migration)


def index(name='a'):
    return [{'INDEX_NAME': name, 'NON_UNIQUE': 1, 'SEQ_IN_INDEX': 1, 'COLUMN_NAME': 'empleado_id',
             'COLLATION': 'A', 'SUB_PART': None, 'INDEX_TYPE': 'BTREE', 'IS_VISIBLE': 'YES', 'EXPRESSION': None}]


def test_exact_duplicates_and_repeat():
    assert migration.verify_pair(index('old'), index('retained'))
    assert migration.verify_pair([], index()) is False
    with pytest.raises(ValueError): migration.verify_pair(index(), [])


@pytest.mark.parametrize('field,value', [('NON_UNIQUE',0),('COLUMN_NAME','empresa_id'),('COLLATION','D'),('SUB_PART',10),('IS_VISIBLE','NO'),('INDEX_TYPE','HASH'),('EXPRESSION','lower(name)')])
def test_refuses_non_equivalent_indexes(field,value):
    changed=copy.deepcopy(index()); changed[0][field]=value
    with pytest.raises(ValueError): migration.verify_pair(changed,index())


def test_startup_requires_retained_index_names():
    from extensions import REQUIRED_INDEXES
    for table, removed, retained in migration.CANDIDATES:
        if table == 'asistencias':
            assert removed not in REQUIRED_INDEXES[table]
            assert retained in REQUIRED_INDEXES[table]
