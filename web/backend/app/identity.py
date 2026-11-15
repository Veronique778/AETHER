"""AETHER 1.5 identifier policy for the scientific backend (Backend №3, package 03A).

Two kinds of astronaut identifiers exist and must never be confused:

    personal      canonical lowercase UUID created by Backend №2 (astronaut_profiles.id, data_class 'personal')
    legacy_demo   'A01'…'A9999' — the synthetic 1.4 crew; carries SYNTHETIC data only

Rules
* Syntax is checked here; EXISTENCE and ACCESS are never decided here — they are decided by the server-side
  RequestContext / storage (Backend №2 `access_control.profile`), which hides foreign resources as 404.
* user_id ≠ astronaut_id: a user id is never accepted where an astronaut id is expected (the storage resolves the
  caller's own profile; this module only refuses malformed values).
* Non-canonical UUID spellings (upper case, braces, missing dashes) are REFUSED rather than normalised, so that two
  spellings can never address the same object through different checks.
* A legacy demo id may only be combined with data_class 'synthetic'; a personal id never upgrades demo data.
* No profile is ever created automatically.
"""
from __future__ import annotations

import re

from .science_errors import InvalidInput

UUID_RE = re.compile(r'^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$')
LEGACY_RE = re.compile(r'^A[0-9]{2,4}$')
# Backend №2 schemas_15.Identifier — used for device / session / mission / measurement ids
OBJECT_ID_RE = re.compile(r'^[a-zA-Z0-9_.:-]{1,80}$')
PERSONAL, LEGACY_DEMO = 'personal', 'legacy_demo'


def astronaut_kind(value) -> str | None:
    if not isinstance(value, str):
        return None
    if UUID_RE.match(value):
        return PERSONAL
    if LEGACY_RE.match(value):
        return LEGACY_DEMO
    return None


def validate_astronaut_id(value, field: str = 'astronaut_id', *, allow_legacy: bool = True) -> tuple[str, str]:
    """→ (astronaut_id, kind). Raises InvalidInput for empty / malformed / non-canonical ids."""
    if value is None or value == '':
        raise InvalidInput('astronaut_id is required', field=field)
    kind = astronaut_kind(value)
    if kind is None:
        hint = ' (UUIDs must be lowercase canonical 8-4-4-4-12)' if isinstance(value, str) and re.fullmatch(
            r'[{(]?[0-9A-Fa-f-]{32,38}[})]?', value) else ''
        raise InvalidInput(f'astronaut_id is not a valid personal UUID or legacy demo id{hint}', field=field)
    if kind == LEGACY_DEMO and not allow_legacy:
        raise InvalidInput('Legacy demo astronaut ids (A01–A04) carry synthetic data only and cannot be used here',
                           field=field, code='legacy_id_not_allowed')
    return value, kind


def check_data_classes(kind: str, data_classes, field: str = 'data_classes') -> None:
    """Demo identities never carry real data; mixing is refused instead of guessed."""
    if kind == LEGACY_DEMO and any(c != 'synthetic' for c in data_classes):
        raise InvalidInput('Legacy demo astronaut ids carry synthetic data only; request data_classes ["synthetic"]',
                           field=field, code='legacy_id_not_allowed')


def validate_object_id(value, field: str) -> str:
    if not isinstance(value, str) or not OBJECT_ID_RE.match(value):
        raise InvalidInput(f'{field} must be 1–80 characters [a-zA-Z0-9_.:-]', field=field)
    return value
