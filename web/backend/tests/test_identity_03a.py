"""03A — astronaut identifiers: syntax (app.identity) vs existence/access (Backend №2 RequestContext / access_control).

Syntax is decided locally; existence and access ONLY server-side through Be2Context.can → access_control.profile.
"""
import uuid

import pytest

from app import identity
from app.science_errors import InvalidInput
from be3_real_backend import Account, crew, real_db, revoke  # noqa: F401

GOOD_UUID = '3f2b8c1e-9a4d-4e7b-8c2a-1d5e6f7a8b9c'


@pytest.mark.parametrize('value,kind', [('A01', 'legacy_demo'), ('A04', 'legacy_demo'), ('A1234', 'legacy_demo'),
                                        (GOOD_UUID, 'personal'), (str(uuid.uuid4()), 'personal')])
def test_valid_syntax(value, kind):
    assert identity.validate_astronaut_id(value) == (value, kind)


@pytest.mark.parametrize('value', ['', None, 'A1', 'A12345', 'a01', ' A01', 'A01 ', GOOD_UUID.upper(), '{' + GOOD_UUID + '}',
                                   GOOD_UUID.replace('-', ''), GOOD_UUID[:-1], GOOD_UUID + '0',
                                   '3f2b8c1e-9a4d-0e7b-8c2a-1d5e6f7a8b9c',          # version 0
                                   '3f2b8c1e-9a4d-4e7b-7c2a-1d5e6f7a8b9c',          # variant 7
                                   'A01;DROP', '../A01', 'u' * 32, 0, 1.0, True, ['A01'], {'id': 'A01'}])
def test_invalid_syntax_is_422_and_never_normalised(value):
    with pytest.raises(InvalidInput) as e:
        identity.validate_astronaut_id(value)
    assert e.value.status == 422 and e.value.field == 'astronaut_id'


def test_legacy_ids_are_demo_only():
    with pytest.raises(InvalidInput) as e:
        identity.validate_astronaut_id('A01', allow_legacy=False)
    assert e.value.code == 'legacy_id_not_allowed'
    identity.check_data_classes('legacy_demo', ['synthetic'])
    for classes in (['real_wearable'], ['manual'], ['synthetic', 'manual']):
        with pytest.raises(InvalidInput):
            identity.check_data_classes('legacy_demo', classes)
    identity.check_data_classes('personal', ['real_wearable', 'manual', 'synthetic'])


@pytest.mark.parametrize('value', ['abc-1', 'x' * 80, 'a.b:c_d-e'])
def test_object_ids(value):
    assert identity.validate_object_id(value, 'device_id') == value


@pytest.mark.parametrize('value', ['', 'x' * 81, 'a b', 'a/b', 'é', None, 5])
def test_object_ids_invalid(value):
    with pytest.raises(InvalidInput):
        identity.validate_object_id(value, 'device_id')


# ------------------------------------------------------------------ existence / access on the REAL Backend №2 store
def test_access_is_decided_server_side(real_db):
    alice, med, adm, mid = crew()
    bob = Account('bob')
    a, b = alice.ctx(), bob.ctx()
    assert identity.astronaut_kind(alice.astronaut_id) == 'personal' and alice.astronaut_id != alice.id   # user ≠ astronaut
    assert a.can('measurement:read', alice.astronaut_id) and a.can('measurement:write', alice.astronaut_id)
    # two users, each only their own profile
    assert not a.can('measurement:read', bob.astronaut_id) and not b.can('measurement:read', alice.astronaut_id)
    # a syntactically valid but nonexistent UUID is not "allowed": no auto-created profile
    ghost = str(uuid.uuid4())
    assert not a.can('measurement:read', ghost) and not a.can('measurement:write', ghost)
    from app import db
    with db.connect() as c:
        assert c.execute('SELECT 1 FROM astronaut_profiles WHERE id=?', (ghost,)).fetchone() is None
    # user id used as an astronaut id → nothing
    assert not a.can('measurement:read', alice.id)
    # legacy ids are never personal profiles, even though Backend №2 seeds A01–A04 as legacy_demo rows
    assert not a.can('measurement:read', 'A01') and not adm.ctx().can('measurement:read', 'A01')
    # administrator is not a medical superuser
    assert not adm.ctx().can('measurement:read', alice.astronaut_id)
    assert not adm.ctx().can('measurement:read', alice.astronaut_id, mid)
    # medical officer: read with grant + mission only; never write
    m = med.ctx()
    assert m.can('measurement:read', alice.astronaut_id, mid)
    assert not m.can('measurement:read', alice.astronaut_id)                    # no mission → no access
    assert not m.can('measurement:read', alice.astronaut_id, str(uuid.uuid4()))
    assert not m.can('measurement:write', alice.astronaut_id, mid) and not m.can('phantom:run', alice.astronaut_id, mid)
    revoke(adm, mid, med, alice)
    assert not m.can('measurement:read', alice.astronaut_id, mid)               # revocation is immediate


def test_officer_without_grant_has_nothing(real_db):
    alice, med, adm, mid = crew(grant=False)
    assert not med.ctx().can('measurement:read', alice.astronaut_id, mid)


def test_invalid_or_expired_bearer_is_401(real_db):
    from app.science_errors import Unauthenticated
    from app.science_storage_be2 import Be2Context
    for tok in ('', 'x', 'x' * 43, 'Bearer abc'):
        with pytest.raises(Unauthenticated):
            Be2Context(tok)
    alice = Account('alice')
    ctx = alice.ctx()
    alice.logout()
    with pytest.raises(Unauthenticated):
        ctx.can('measurement:read', alice.astronaut_id)
    assert 'redacted' in repr(ctx) and alice.token not in repr(ctx) and alice.token not in repr(alice)
