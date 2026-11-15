"""AETHER 1.5 scientific routes — declarative table for Backend №2 (API Contract 1.5 §2.2).

Backend №3 does not edit app/main.py or app/devserver.py. Backend №2 registers ROUTES once in BOTH servers
(app/routing15.py) after the launch-token, Bearer and astronaut-scope checks, and passes a RequestContext.
Both servers must call the same `dispatch` so JSON, status codes and error messages are identical.

Handler signature: handler(ctx, match: dict, query: dict[str, list[str] | str], body: dict | None)
                   → dict (200) or (status, dict).
Errors: app.science_errors.ScienceError → `dispatch` returns Backend №2's envelope {"error": {"code", "detail"}} (03A).

Status of each route (CHANGESET.md): implemented + automated_tested against tests/fakes/storage_fake.py;
integration_pending until Backend №2 registers it and provides app/storage.
"""
from __future__ import annotations

import re

from . import phantom_analyses, science_storage, signals
from .science_errors import NotFound, ScienceError

def set_storage(storage) -> None:
    """Tests (fake) or Backend №2 (real) inject the storage implementation (app.science_storage)."""
    science_storage.set_storage(storage)


def get_storage(features=('measurements', 'analyses')):
    """Resolve Backend №2's storage through the adapter boundary (app.storage.api or app.persistence); never a fake."""
    return science_storage.resolve(features)


def h_signals(ctx, match, query, body):
    return signals.registry()


def h_phantom_run(ctx, match, query, body):
    return phantom_analyses.run(ctx, body or {}, get_storage())


def h_phantom_list(ctx, match, query, body):
    return phantom_analyses.list_analyses(ctx, query or {}, get_storage())


def h_phantom_get(ctx, match, query, body):
    return phantom_analyses.get_analysis(ctx, match['analysis_id'], get_storage())


# (method, path regex, handler, access policy) — astronaut_scope as defined in contract §2.2
ROUTES = [
    ('GET', r'^/api/signals$', h_signals, {'auth': 'launch_token', 'astronaut_scope': None, 'capability': 'signals-registry'}),
    ('POST', r'^/api/phantom-analyses$', h_phantom_run,
     {'auth': 'bearer', 'astronaut_scope': 'body', 'permission': 'phantom:run', 'capability': 'phantom-analyses'}),
    ('GET', r'^/api/phantom-analyses$', h_phantom_list,
     {'auth': 'bearer', 'astronaut_scope': 'query?', 'permission': 'measurement:read', 'capability': 'phantom-analyses'}),
    ('GET', r'^/api/phantom-analyses/(?P<analysis_id>[a-zA-Z0-9_.:-]{1,80})$', h_phantom_get,
     {'auth': 'bearer', 'astronaut_scope': None, 'permission': 'measurement:read', 'resource_check': 'storage',
      'capability': 'phantom-analyses'}),
]
_COMPILED = [(m, re.compile(p), h, pol) for m, p, h, pol in ROUTES]


def register_extra(routes: list) -> None:
    """Later packages (devices, package 03) append their routes here instead of editing this table."""
    for m, p, h, pol in routes:
        ROUTES.append((m, p, h, pol))
        _COMPILED.append((m, re.compile(p), h, pol))


def match(method: str, path: str):
    for m, rx, h, pol in _COMPILED:
        mm = rx.match(path)
        if mm and m == method:
            return h, mm.groupdict(), pol
    return None


def dispatch(ctx, method: str, path: str, query: dict | None = None, body: dict | None = None) -> tuple[int, dict]:
    """Single entry point for both servers. Returns (status, json_body); never raises ScienceError."""
    found = match(method, path)
    if found is None:
        return NotFound('Not Found').status, NotFound('Not Found').envelope()
    handler, params, _ = found
    try:
        out = handler(ctx, params, query or {}, body)
    except ScienceError as err:
        return err.status, err.envelope()          # 03A: Backend №2 error format {"error": {"code", "detail"}}
    if isinstance(out, tuple):
        return out
    return 200, out


def _register_devices():
    from .devices import api as devices_api   # package 03: BLE device routes (contract §3.6)
    register_extra(devices_api.ROUTES)


_register_devices()
