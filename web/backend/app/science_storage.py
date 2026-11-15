"""Storage adapter boundary between the scientific backend (Backend №3) and the central database (Backend №2).

Backend №3 does NOT own a database for personal data. Every scientific module talks to ONE protocol — the storage API of
API Contract 1.5 §2.3 plus the amendments A-3 and A-11 — and this module finds the implementation Backend №2 provides:

    1. an object injected with set_storage()                 (tests: tests/fakes/storage_fake.FakeStorage)
    2. module  app.storage.api                                 (name used in API Contract 1.5)
    3. module  app.persistence  exposing  science_storage()  or  SCIENCE_STORAGE
                                                               (Backend №2's package; see BACKEND_INTEGRATION_REQUESTS.md)
    4. app.science_storage_be2.Be2ScienceStorage — Backend №3's adapter over Backend №2's REAL repository functions
       (03A); used when Backend №2's persistence imports, no table or SQL of its own

Nothing else is tried: there is no fallback to a fake, to SQLite files of Backend №3 or to demo data. If no conforming
implementation exists, StorageUnavailable (503) is raised and nothing is analysed or recorded.

`conformance(obj)` checks the required callables and their keyword parameters, so an incompatible adapter fails at
startup with a precise list instead of failing in the middle of a recording.
"""
from __future__ import annotations

import importlib
import inspect

from .science_errors import StorageUnavailable

# method → required parameter names (positional order after ctx is part of the contract)
REQUIRED: dict[str, dict[str, tuple[str, ...]]] = {
    'measurements': {
        'save_measurements': ('ctx', 'items'),
        'query_measurements': ('ctx', 'astronaut_id'),            # + keywords signals, start, end, session_id, include_invalid, limit, cursor
    },
    'sessions': {
        'create_session': ('ctx', 'astronaut_id', 'source_type', 'source'),   # + device_id, mission_id, metadata
        'finish_session': ('ctx', 'session_id', 'status'),                   # + metadata
        'get_session': ('ctx', 'session_id'),
        'list_sessions': ('ctx',),                                           # + status
    },
    'analyses': {
        'save_analysis_bundle': ('ctx', 'kind', 'astronaut_id', 'payload'),  # + record, audit, idempotency_key (keyword-only)
        'get_analysis': ('ctx', 'analysis_id'),
        'list_analyses': ('ctx',),
    },
    'devices': {
        'upsert_device': ('ctx', 'device'),
        'get_device': ('ctx', 'device_id'),
        'list_devices': ('ctx',),
    },
    'history': {
        'log_record': ('ctx', 'kind', 'ref_ids', 'astronaut_id', 'data_class', 'summary'),
        'audit': ('ctx', 'action', 'target_kind', 'target_id', 'outcome'),
    },
}
KEYWORDS = {
    'query_measurements': ('signals', 'start', 'end', 'session_id', 'include_invalid', 'limit', 'cursor'),
    'create_session': ('device_id', 'mission_id', 'metadata'),
    'list_sessions': ('status',),
    'save_analysis_bundle': ('record', 'audit', 'idempotency_key', 'input_ids'),
}

_INJECTED = None


def set_storage(obj) -> None:
    global _INJECTED
    _INJECTED = obj


def _accepts(fn, names) -> list[str]:
    try:
        sig = inspect.signature(fn)
    except (TypeError, ValueError):
        return []
    params = sig.parameters
    if any(p.kind == p.VAR_KEYWORD for p in params.values()):
        return []
    plist = [p for p in params.values() if p.name != 'self']
    return [n for n in names if n not in {p.name for p in plist}]


def conformance(obj, features=tuple(REQUIRED)) -> list[str]:
    """→ list of problems (empty = conforming) for the requested feature groups."""
    problems = []
    for feat in features:
        for name, params in REQUIRED[feat].items():
            fn = getattr(obj, name, None)
            if not callable(fn):
                problems.append(f'{feat}: missing {name}()')
                continue
            missing = _accepts(fn, params[1:] + KEYWORDS.get(name, ()))   # ctx is positional in every method
            if missing:
                problems.append(f'{feat}: {name}() lacks parameter(s) {", ".join(missing)}')
    return problems


def _candidates():
    if _INJECTED is not None:
        yield 'injected', _INJECTED
        return
    try:
        yield 'app.storage.api', importlib.import_module('app.storage.api')
    except ImportError:
        pass
    try:
        mod = importlib.import_module('app.persistence')
    except ImportError:
        return
    if callable(getattr(mod, 'science_storage', None)):
        yield 'app.persistence.science_storage()', mod.science_storage()
    elif getattr(mod, 'SCIENCE_STORAGE', None) is not None:
        yield 'app.persistence.SCIENCE_STORAGE', mod.SCIENCE_STORAGE
    # 03A: Backend №3's own adapter over Backend №2's real repository (app/science_storage_be2.py). Requires Backend №2's
    # persistence and auth to import (argon2-cffi installed); otherwise nothing is yielded and resolve() fails closed.
    try:
        importlib.import_module('app.persistence.repository')
        from .science_storage_be2 import Be2ScienceStorage
        yield 'app.science_storage_be2.Be2ScienceStorage', Be2ScienceStorage()
    except ImportError:
        return


def resolve(features=('measurements',)):
    """Return the first conforming storage implementation for `features`, else raise StorageUnavailable."""
    seen = []
    for where, obj in _candidates():
        problems = conformance(obj, features)
        if not problems:
            return obj
        seen.append(f'{where}: ' + '; '.join(problems))
    detail = ' | '.join(seen) if seen else 'no app.storage.api and no app.persistence science adapter is installed'
    raise StorageUnavailable(f'Personal-data storage (Backend №2) is not available for {", ".join(features)} — {detail}')
