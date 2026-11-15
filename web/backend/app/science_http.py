"""HTTP glue between Backend №2's single 1.5 dispatcher (app/api_15.py) and the scientific routes (Backend №3, 03A).

Backend №2 owns route registration. It needs ONE call in api_15.dispatch, before the "not matched → 410" branch:

    from .science_http import handle as science_handle
    science = science_handle(method, path, headers, raw, query, peer)
    if science is not None:
        return science

`handle` returns None for every path that is not a scientific route (so Backend №2's own routes, including the device
REGISTRY GET/POST /api/devices, are never shadowed), otherwise (status, json) with Backend №2's error envelope.
Authentication uses Backend №2's auth.authenticate (Bearer); the launch token is checked earlier by app.security for
both servers. No session, user or role is created here, and no system context can be requested over HTTP.
"""
from __future__ import annotations

import json

from . import api15_science
from .science_errors import InvalidInput, ScienceError, Unauthenticated

MAX_BODY = 16 * 1024


def _token(headers: dict) -> str:
    h = headers.get('authorization', '')
    return h[7:] if h.startswith('Bearer ') else ''


def is_science_path(method: str, path: str) -> bool:
    return api15_science.match(method, path) is not None


def handle(method, path, headers, raw, query, peer='local'):
    if not is_science_path(method, path):
        return None
    from .science_storage_be2 import Be2Context
    try:
        ctx = Be2Context(_token(headers))
        if raw and len(raw) > MAX_BODY:
            raise InvalidInput('Request body exceeds 16 KB', code='payload_too_large', status=413)
        if raw and headers.get('content-type', '').split(';')[0].strip().lower() != 'application/json':
            raise InvalidInput('Content-Type must be application/json', code='content_type', status=415)
        try:
            body = json.loads(raw) if raw else {}
        except (ValueError, UnicodeDecodeError):
            raise InvalidInput('Invalid JSON request', code='invalid_request', status=400) from None
        if not isinstance(body, dict):
            raise InvalidInput('Expected a JSON object', code='json_object')
        if any(len(v) != 1 for v in (query or {}).values()):
            raise InvalidInput('Duplicate query parameter', code='query_duplicate')
    except Unauthenticated as err:
        return 401, {'error': {'code': 'unauthenticated', 'detail': 'A valid personal session is required'}}
    except ScienceError as err:
        return err.status, err.envelope()
    return api15_science.dispatch(ctx, method, path, query or {}, body)


def capabilities() -> list[str]:
    """Flags Backend №2 may add to /api/health once `handle` is wired AND the storage resolves."""
    from . import science_storage
    try:
        science_storage.resolve(('measurements', 'analyses', 'sessions', 'devices', 'history'))
    except ScienceError:
        return []
    return ['signals-registry', 'phantom-analyses', 'devices-ble']
