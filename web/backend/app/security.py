"""Local-API access control for the AETHER desktop backend (1.5).

Threat model: AETHER listens on 127.0.0.1. Any web page the user opens in an
ordinary browser can *send* requests to localhost (CSRF) and, through DNS
rebinding, may even read responses. CORS headers alone do not stop either.

Controls, applied identically by both HTTP servers (app.devserver and app.main):

1. Host allow-list   - the Host header must be a loopback name (blocks DNS rebinding).
2. Origin policy     - a browser Origin must be the server's own origin or an
                       explicitly configured developer origin; Sec-Fetch-Site
                       'cross-site' is always refused.
3. Session token     - every /api route except the public health/bootstrap
                       routes requires the per-launch secret in the
                       ``X-AETHER-Token`` header. The token is generated at server
                       start, injected into the same-origin index.html and is
                       never written to disk or logs. A custom header also forces
                       a CORS preflight, which foreign origins never pass.
4. Body limits       - request bodies are bounded per route before parsing.

This is a localhost research prototype control set, not a certified security
boundary. Other software running under the same OS account is out of scope.
"""
from __future__ import annotations

import hmac
import os
import secrets
import re
from ipaddress import ip_address
from dataclasses import dataclass, field

TOKEN_HEADER = 'x-aether-token'
LOOPBACK_HOSTS = {'127.0.0.1', 'localhost', '[::1]', '::1'}
# Routes that must work before the page has the token (or for liveness checks).
PUBLIC_PATHS = {'/api/health', '/api/session'}
DEFAULT_BODY_LIMIT = 256 * 1024
BODY_LIMITS = {
    '/api/nasa/analyze-csv': 3_200_000,
    '/api/nasa/local-csv': 3_200_000,
    '/api/biosignals/': 16_384,
}
DEV_ORIGINS = ('http://localhost:5173', 'http://127.0.0.1:5173',
               'http://localhost:4173', 'http://127.0.0.1:4173')


def _truthy(value: str | None) -> bool:
    return str(value or '').strip().lower() in ('1', 'true', 'yes', 'on')


@dataclass
class Policy:
    """Per-server security policy. One instance per running server."""
    token: str = field(default_factory=lambda: os.environ.get('AETHER_SESSION_TOKEN') or secrets.token_urlsafe(32))
    require_token: bool = field(default_factory=lambda: not _truthy(os.environ.get('AETHER_DISABLE_TOKEN')))
    extra_origins: tuple[str, ...] = field(default_factory=lambda: tuple(
        o.strip().rstrip('/') for o in os.environ.get('AETHER_CORS_ORIGINS', ','.join(DEV_ORIGINS)).split(',') if o.strip()))

    remote: bool = field(default_factory=lambda: _truthy(os.environ.get('AETHER_REMOTE')))
    remote_hosts: tuple[str, ...] = field(default_factory=lambda: tuple(x.strip().lower() for x in os.environ.get('AETHER_ALLOWED_HOSTS','').split(',') if x.strip()))

    def __post_init__(self):
        if not self.require_token:
            raise ValueError('AETHER local API protection cannot be disabled')
        if _truthy(os.environ.get('AETHER_RELEASE')) and os.environ.get('AETHER_LEGACY_DEMO')=='1':
            raise ValueError('Legacy demo mode is prohibited in release configuration')
        if self.remote:
            if not self.remote_hosts or any('*' in h or '/' in h for h in self.remote_hosts):
                raise ValueError('Remote mode requires explicit AETHER_ALLOWED_HOSTS')
            if os.environ.get('AETHER_LEGACY_DEMO')=='1':
                raise ValueError('Legacy mode cannot be exposed remotely')
            # Vite defaults are local development only; explicitly supplied remote origins must use TLS.
            self.extra_origins = tuple(x for x in self.extra_origins if x not in DEV_ORIGINS)
            if any(not x.startswith('https://') for x in self.extra_origins):
                raise ValueError('Remote origins must use HTTPS')

    def allowed_origins(self, host_header: str) -> set[str]:
        scheme = 'https' if self.remote else 'http'
        own = {f'{scheme}://{host_header}'} if host_header else set()
        return own | set(self.extra_origins)


def host_ok(host_header: str | None) -> bool:
    if not host_header: return False
    host = host_header.lower()
    if host == '::1': return True
    match = re.fullmatch(r'(localhost|127\.0\.0\.1|\[::1\])(?::([0-9]{1,5}))?',host)
    return bool(match and (match[2] is None or 0 < int(match[2]) <= 65535))


def body_limit(path: str) -> int:
    for prefix, limit in BODY_LIMITS.items():
        if path == prefix or (prefix.endswith('/') and path.startswith(prefix)):
            return limit
    return DEFAULT_BODY_LIMIT


def check(policy: Policy, method: str, path: str, headers: dict[str, str], content_length: int | None = None, secure_transport: bool = False):
    """Return None when the request may proceed, else (status, detail).

    ``headers`` must have lower-case keys.
    """
    host = headers.get('host','').lower()
    permitted = host in policy.remote_hosts if policy.remote else host_ok(host)
    if not permitted: return (421, 'Invalid Host header for AETHER server')
    if policy.remote and not secure_transport: return (403, 'HTTPS is required')
    if headers.get('transfer-encoding'): return (400, 'Transfer-Encoding is not supported')
    if headers.get('content-encoding'): return (415, 'Encoded request bodies are not supported')
    if not path.startswith('/api/'):
        return None
    if headers.get('sec-fetch-site') == 'cross-site':
        return (403, 'Cross-site requests to the local AETHER API are refused')
    origin = (headers.get('origin') or '').rstrip('/')
    if origin and origin != 'null' and origin not in policy.allowed_origins(headers.get('host', '')):
        return (403, 'Origin not allowed for the local AETHER API')
    if origin == 'null':
        return (403, 'Opaque origins are not allowed for the local AETHER API')
    if method == 'OPTIONS':
        return None
    if content_length is not None and content_length > body_limit(path):
        return (413, 'Request body exceeds limit')
    if content_length is not None and content_length < 0:
        return (400, 'Invalid Content-Length')
    if path in PUBLIC_PATHS or policy.remote:
        return None
    supplied = headers.get(TOKEN_HEADER, '')
    if not supplied or not hmac.compare_digest(supplied.encode(), policy.token.encode()):
        return (401, 'Missing or invalid AETHER session token')
    return None


def cors_headers(policy: Policy, headers: dict[str, str]) -> dict[str, str]:
    """CORS response headers: echo only allow-listed origins, never '*'."""
    origin = (headers.get('origin') or '').rstrip('/')
    if not origin or origin not in policy.allowed_origins(headers.get('host', '')):
        return {}
    return {'Access-Control-Allow-Origin': origin, 'Vary': 'Origin',
            'Access-Control-Allow-Headers': 'Content-Type, X-AETHER-Token, Authorization',
            'Access-Control-Allow-Methods': 'GET, POST, PATCH, DELETE, OPTIONS'}


def session_payload(policy: Policy) -> dict:
    if policy.remote: return {'header': 'Authorization', 'type': 'Bearer', 'required': True}
    return {'token': policy.token, 'header': 'X-AETHER-Token', 'required': policy.require_token}


def inject_token(html: str, policy: Policy) -> str:
    if policy.remote: return html
    from html import escape
    meta = f'<meta name="aether-session-token" content="{escape(policy.token, quote=True)}">'
    return html.replace('<head>', '<head>\n' + meta, 1) if '<head>' in html else meta + html


_CSV_TRIGGERS = ('=', '+', '-', '@', '\t', '\r', '|')


def csv_safe(value):
    """Neutralise spreadsheet formula injection (CWE-1236) in exported cells.

    Numbers are left unchanged. Text that a spreadsheet would evaluate gets a
    leading apostrophe, which spreadsheet software displays but does not run.
    """
    if value is None or isinstance(value, (int, float)):
        return value
    text = str(value)
    if text and text[0] in _CSV_TRIGGERS:
        try:
            float(text)
            return text
        except ValueError:
            return "'" + text
    return text


class ASGISecurity:
    """Pure ASGI middleware applying :func:`check` and CORS for app.main (FastAPI)."""

    def __init__(self, app, policy: Policy):
        self.app = app
        self.policy = policy

    async def __call__(self, scope, receive, send):
        if scope.get('type') != 'http':
            return await self.app(scope, receive, send)
        headers = {k.decode('latin-1').lower(): v.decode('latin-1') for k, v in scope.get('headers', [])}
        try:
            length = int(headers['content-length']) if 'content-length' in headers else None
        except ValueError:
            length = -1
        denied = check(self.policy, scope.get('method', 'GET'), scope.get('path', ''), headers, length, secure_transport=scope.get('scheme')=='https')
        sensitive = {b'host',b'authorization',b'content-length',b'x-aether-token'}
        raw_names = [k.lower() for k,v in scope.get('headers',[])]
        if any(raw_names.count(k)>1 for k in sensitive): denied=(400,'Duplicate security header')
        peer = (scope.get('client') or ('',0))[0]
        try:
            external_peer = not ip_address(peer).is_loopback
        except ValueError:
            external_peer = False  # In-process ASGI tests may have no numeric network peer.
        if not self.policy.remote and external_peer:
            denied=(403,'Local mode accepts only loopback connections')
        cors = cors_headers(self.policy, headers)
        if denied is None and scope.get('method') == 'OPTIONS' and scope.get('path', '').startswith('/api/'):
            denied = (204, '')
        if denied is not None:
            import json
            status, detail = denied
            body = b'' if status == 204 else json.dumps({'detail': detail}).encode()
            raw = [(b'content-type', b'application/json'), (b'content-length', str(len(body)).encode())]
            raw += [(k.lower().encode(), v.encode()) for k, v in cors.items()]
            await send({'type': 'http.response.start', 'status': status, 'headers': raw})
            await send({'type': 'http.response.body', 'body': body})
            return

        chunks = []
        size = 0
        while True:
            message = await receive()
            if message.get('type') == 'http.disconnect': return
            chunk = message.get('body', b''); size += len(chunk)
            if size > body_limit(scope.get('path','')):
                import json
                body = json.dumps({'detail':'Request body exceeds limit'}).encode()
                await send({'type':'http.response.start','status':413,'headers':[(b'content-type',b'application/json'),(b'content-length',str(len(body)).encode())]})
                await send({'type':'http.response.body','body':body})
                return
            chunks.append(chunk)
            if not message.get('more_body'): break
        raw_body = b''.join(chunks)
        if length is not None and length != len(raw_body):
            body = b'{"detail":"Content-Length mismatch"}'
            await send({'type':'http.response.start','status':400,'headers':[(b'content-type',b'application/json')]})
            await send({'type':'http.response.body','body':body})
            return

        async def replay():
            return {'type':'http.request','body':raw_body,'more_body':False}

        async def send_with_cors(message):
            if message['type'] == 'http.response.start' and cors:
                message = {**message, 'headers': list(message.get('headers', [])) +
                           [(k.lower().encode(), v.encode()) for k, v in cors.items()]}
            await send(message)
        return await self.app(scope, replay, send_with_cors)
