import pytest

from scripts.optimize_database_indexes import validate_pair


def row(**overrides):
    return dict(Seq_in_index=1, Column_name='empleado_id', Sub_part=None,
                Collation='A', Index_type='BTREE', Visible='YES',
                Expression=None, Non_unique=1, **overrides)


def test_equivalent_nonunique_indexes_are_accepted():
    validate_pair({'old': [row()], 'keep': [row()]}, 'old', 'keep')


@pytest.mark.parametrize('field,value', [
    ('Column_name', 'empresa_id'), ('Collation', 'D'), ('Sub_part', 3),
    ('Visible', 'NO'), ('Non_unique', 0), ('Expression', 'lower(nombre)'),
])
def test_different_definition_is_rejected(field, value):
    changed = row()
    changed[field] = value
    with pytest.raises(ValueError):
        validate_pair({'old': [row()], 'keep': [changed]}, 'old', 'keep')


def test_unique_indexes_are_never_removed():
    unique = row()
    unique['Non_unique'] = 0
    with pytest.raises(ValueError):
        validate_pair({'old': [unique], 'keep': [unique]}, 'old', 'keep')


def test_missing_replacement_is_rejected():
    with pytest.raises(ValueError):
        validate_pair({'old': [row()]}, 'old', 'keep')
