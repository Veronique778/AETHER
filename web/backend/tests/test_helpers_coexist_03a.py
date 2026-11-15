"""03A — Backend №2 owns tests/helpers_15.py; Backend №3's helpers live in tests/helpers_be3_signals_15.py.
Both must import in ONE tree without shadowing each other."""
import importlib


def test_both_helper_modules_import_side_by_side():
    be2 = importlib.import_module('helpers_15')
    be3 = importlib.import_module('helpers_be3_signals_15')
    assert be2 is not be3
    assert hasattr(be2, 'account') and hasattr(be2, 'measurement')          # Backend №2 API intact
    assert hasattr(be3, 'hr_series') and hasattr(be3, 'P1')                 # Backend №3 API
    assert not hasattr(be3, 'account') and not hasattr(be2, 'hr_series')    # no accidental merge/overwrite
    assert be2.__file__.endswith('helpers_15.py') and be3.__file__.endswith('helpers_be3_signals_15.py')


def test_be3_fixture_ids_are_personal_uuids_not_demo_ids():
    from app import identity
    from helpers_be3_signals_15 import P1, P2, P3, P4
    assert len({P1, P2, P3, P4}) == 4
    assert all(identity.astronaut_kind(p) == 'personal' for p in (P1, P2, P3, P4))
