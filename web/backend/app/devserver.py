"""Zero-dependency fallback server (Python stdlib + pydantic).

Serves the same /api routes as app.main via app.service, for machines where
FastAPI/uvicorn cannot be installed. Optionally serves the built frontend.

    python -m app.devserver --port 8000 [--static ../frontend/dist]

FastAPI (app.main) remains the primary server; this exists for offline use and tests.
"""
import argparse
import json
import mimetypes
import re
import ssl
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

from pydantic import BaseModel, ValidationError

from . import connectors, db, nasa_research as nasa, security, service
from .mission_engine import ConditionCompare, ReplanRequest, CoorbitApply, CoorbitReject, EngineCompare, EngineControl, EngineRunRequest
from .science.hazards import MissionProfile
from .schemas import RadiationRequest, Experiment, Measurement, PlanRequest, ProjectionRequest, RecoverySession, SimulationRequest


class QueryError(Exception):
    pass


class NasaCsv(BaseModel):
    csv: str = ''
    column: str = ''

class NasaVerifiedCsv(BaseModel):
    study_id: int
    filename: str
    column: str = ''
    label_column: str = ''


class NasaLocalCsv(BaseModel):
    study_id: int
    filename: str
    content: str
    column: str = ''
    label_column: str = ''



def q_int(qs, name, default, lo=None, hi=None):
    raw = qs.get(name, [None])[0]
    if raw is None:
        return default
    try:
        v = int(raw)
    except ValueError as exc:
        raise QueryError(f'{name} must be an integer') from exc
    if (lo is not None and v < lo) or (hi is not None and v > hi):
        raise QueryError(f'{name} out of range')
    return v


def q_float(qs, name, default, lo=None, hi=None):
    raw = qs.get(name, [None])[0]
    if raw is None:
        return default
    try:
        v = float(raw)
    except ValueError as exc:
        raise QueryError(f'{name} must be a number') from exc
    if (lo is not None and v < lo) or (hi is not None and v >= hi):
        raise QueryError(f'{name} out of range')
    return v


def q_bool(qs, name):
    return qs.get(name, ['false'])[0].lower() in ('1', 'true', 'yes')


def body(model: type[BaseModel]):
    return ('body', model)


ROUTES = [
    ('GET', r'/api/health$', lambda m, qs: service.health()),
    ('GET', r'/api/session$', 'session'),  # per-launch token bootstrap; resolved by the handler (needs its policy)
    ('GET', r'/api/human-systems/(?P<id>[^/]+)/quality$', lambda m, qs: __import__('app.human_systems', fromlist=['summary']).summary(m['id'], q_int(qs, 'day', 67, 1), q_int(qs, 'window', 14, 3, 366))),
    ('GET', r'/api/astronauts$', lambda m, qs: service.get_astronauts()),
    ('GET', r'/api/astronauts/(?P<id>[^/]+)/timeline$', lambda m, qs: service.get_timeline(m['id'], q_int(qs, 'day', 67, 1))),
    ('POST', r'/api/astronauts/(?P<id>[^/]+)/measurements$', (Measurement, lambda m, qs, b: service.post_measurement(m['id'], b))),
    ('GET', r'/api/phantom/(?P<id>[^/]+)$', lambda m, qs: service.phantom(m['id'], q_int(qs, 'day', 67, 1))),
    ('GET', r'/api/phantom/(?P<id>[^/]+)/history$', lambda m, qs: service.phantom_history(m['id'], q_int(qs, 'day', 67, 1), q_int(qs, 'start', 41, 1))),
    ('GET', r'/api/phantom/(?P<id>[^/]+)/correlations$', lambda m, qs: service.phantom_correlations(m['id'], q_int(qs, 'day', 67, 1), q_int(qs, 'window', 30, 8, 365))),
    ('GET', r'/api/symbiosis$', lambda m, qs: service.symbiosis(q_int(qs, 'day', 67, 1))),
    ('GET', r'/api/symbiosis/history$', lambda m, qs: service.symbiosis_history(qs.get('zone', ['habitat'])[0], q_int(qs, 'start', 1, 1), q_int(qs, 'end', 67, 1))),
    ('GET', r'/api/ship$', lambda m, qs: service.ship(q_int(qs, 'day', 67, 1), q_float(qs, 'hour', 10.0, 0, 24))),
    ('GET', r'/api/co-orbit$', lambda m, qs: service.co_orbit(q_bool(qs, 'reduce_a01'))),
    ('GET', r'/api/co-orbit/calendar$', lambda m, qs: service.co_orbit_calendar(q_int(qs, 'day', 67, 1))),
    ('POST', r'/api/co-orbit/plan$', (PlanRequest, lambda m, qs, b: service.co_orbit_plan(b))),
    ('GET', r'/api/mission-lab/scenarios$', lambda m, qs: service.scenarios()),
    ('POST', r'/api/mission-lab/run$', (SimulationRequest, lambda m, qs, b: service.simulate(b))),
    ('POST', r'/api/mission-lab/project$', (ProjectionRequest, lambda m, qs, b: service.projection(b))),
    ('POST', r'/api/recovery/sessions$', (RecoverySession, lambda m, qs, b: service.save_recovery(b))),
    ('GET', r'/api/recovery/sessions/(?P<id>[^/]+)$', lambda m, qs: service.get_recovery(m['id'])),
    # v0.8 integration
    ('GET', r'/api/symbiosis/crew-association$', lambda m, qs: service.crew_association(q_int(qs, 'day', 67, 1), qs.get('zone', ['habitat'])[0])),
    ('GET', r'/api/recovery/biofeedback$', lambda m, qs: service.biofeedback(qs.get('astronaut_id', ['A01'])[0])),
    ('GET', r'/api/mission-lab/experiments$', lambda m, qs: service.list_experiments()),
    ('POST', r'/api/mission-lab/experiments$', (Experiment, lambda m, qs, b: service.save_experiment(b))),
    ('DELETE', r'/api/mission-lab/experiments/(?P<id>[^/]+)$', lambda m, qs: service.delete_experiment(m['id'])),
    ('GET', r'/api/engine/status$', lambda m, qs: service.engine_status()),
    ('GET', r'/api/engine/templates$', lambda m, qs: service.engine_templates()),
    ('GET', r'/api/engine/runs$', lambda m, qs: service.engine_runs()),
    ('POST', r'/api/engine/runs$', (EngineRunRequest, lambda m, qs, b: service.engine_run(b))),
    ('GET', r'/api/engine/runs/(?P<id>[^/]+)$', lambda m, qs: service.engine_get(m['id'])),
    ('POST', r'/api/engine/runs/(?P<id>[^/]+)/control$', (EngineControl, lambda m, qs, b: service.engine_control(m['id'], b))),
    ('GET', r'/api/engine/runs/(?P<id>[^/]+)/evaluation$', lambda m, qs: service.engine_evaluation(m['id'])),
    ('POST', r'/api/engine/compare$', (EngineCompare, lambda m, qs, b: service.engine_compare(b))),
    ('GET', r'/api/phantom2/(?P<id>[^/]+)$', lambda m, qs: service.phantom2_daily(m['id'], q_int(qs, 'day', 67, 1))),
    ('GET', r'/api/engine/runs/(?P<id>[^/]+)/symbiosis$', lambda m, qs: service.engine_symbiosis(m['id'], qs.get('env_metric', ['co2'])[0], qs.get('metric', ['fatigue'])[0], q_int(qs, 'crew_id', 1, 1))),
    ('POST', r'/api/symbiosis/compare-conditions$', (ConditionCompare, lambda m, qs, b: service.symbiosis_compare_conditions(b))),
    ('POST', r'/api/engine/runs/(?P<id>[^/]+)/replan$', (ReplanRequest, lambda m, qs, b: service.engine_replan(m['id'], b))),
    ('GET', r'/api/science/evidence$', lambda m, qs: service.science_evidence()),
    ('GET', r'/api/science/hazards$', lambda m, qs: service.science_hazards()),
    ('POST', r'/api/science/graph$', (MissionProfile, lambda m, qs, b: service.science_graph(b))),
    ('GET', r'/api/science/radiation/presets$', lambda m, qs: service.science_radiation_presets()),
    ('POST', r'/api/science/radiation$', (RadiationRequest, lambda m, qs, b: service.science_radiation(b))),
    ('GET', r'/api/engine/plan-profiles$', lambda m, qs: service.engine_plan_profiles()),
    ('GET', r'/api/engine/runs/(?P<id>[^/]+)/coorbit$', lambda m, qs: service.engine_coorbit(m['id'])),
    ('POST', r'/api/engine/runs/(?P<id>[^/]+)/coorbit/apply$', (CoorbitApply, lambda m, qs, b: service.engine_coorbit_apply(m['id'], b))),
    ('GET', r'/api/engine/runs/(?P<id>[^/]+)/environment$', lambda m, qs: service.engine_environment(m['id'], q_float(qs, 'cabin_pressure_mmhg', 760.0, 200, 800.0001))),
    ('POST', r'/api/engine/runs/(?P<id>[^/]+)/coorbit/reject$', (CoorbitReject, lambda m, qs, b: service.engine_coorbit_reject(m['id'], b))),
    # NASA OSDR research data (parity with app.main; needs internet only when refreshing)
    ('GET', r'/api/nasa/catalog$', lambda m, qs: __import__('app.nasa_research', fromlist=['catalog']).catalog(qs.get('term', ['human physiology'])[0], q_bool(qs, 'refresh'))),
    ('GET', r'/api/nasa/studies/(?P<id>\d+)/files$', lambda m, qs: __import__('app.nasa_research', fromlist=['files']).files(int(m['id']))),
    ('POST', r'/api/nasa/analyze-csv$', (NasaCsv, lambda m, qs, b: __import__('app.nasa_research', fromlist=['summarize_csv']).summarize_csv(b.csv, b.column))),
    ('GET', r'/api/nasa/imports$', lambda m, qs: __import__('app.nasa_research', fromlist=['imports']).imports()),
    ('POST', r'/api/nasa/verified-csv$', (NasaVerifiedCsv, lambda m, qs, b: nasa.verified_csv(b.study_id, b.filename, b.column, b.label_column))),
    # 1.4: offline user-supplied file, study metadata, PHANTOM reference context, connector registry
    ('POST', r'/api/nasa/local-csv$', (NasaLocalCsv, lambda m, qs, b: nasa.local_csv(b.study_id, b.filename, b.content, b.column, b.label_column))),
    ('GET', r'/api/nasa/studies/(?P<id>\d+)$', lambda m, qs: nasa.study_metadata(int(m['id']))),
    ('GET', r'/api/nasa/reference-context$', lambda m, qs: nasa.reference_context()),
    ('GET', r'/api/connectors$', lambda m, qs: connectors.registry()),
]
COMPILED = [(meth, re.compile(p), h) for meth, p, h in ROUTES]


def make_handler(static_dir: Path | None, policy: security.Policy):
    class Handler(BaseHTTPRequestHandler):
        server_version = 'AETHER/1.5'
        sys_version = ''

        def setup(self):
            super().setup()
            self.connection.settimeout(15)

        def log_message(self, fmt, *args):  # quieter console; never log tokens or bodies
            pass

        def _headers(self) -> dict:
            return {k.lower(): v for k, v in self.headers.items()}

        def _send(self, status: int, payload, ctype='application/json', extra=None):
            data = payload if isinstance(payload, bytes) else json.dumps(payload, allow_nan=False).encode()
            self.send_response(status)
            self.send_header('Content-Type', ctype)
            self.send_header('Content-Length', str(len(data)))
            self.send_header('X-Content-Type-Options', 'nosniff')
            self.send_header('Referrer-Policy', 'no-referrer')
            if self.path.startswith('/api/'):
                self.send_header('Cache-Control', 'no-store')
            # 1.4: no wildcard CORS. Only allow-listed origins are echoed.
            for k, v in security.cors_headers(policy, self._headers()).items():
                self.send_header(k, v)
            for k, v in (extra or {}).items():
                self.send_header(k, v)
            self.end_headers()
            if self.command != 'HEAD':
                self.wfile.write(data)

        def _length(self):
            if len(self.headers.get_all('Content-Length', [])) > 1: return -1
            if any(len(self.headers.get_all(k, [])) > 1 for k in ('Host','Authorization','X-AETHER-Token')): return -1
            raw = self.headers.get('Content-Length')
            if raw is None:
                return None
            try:
                return int(raw)
            except ValueError:
                return -1

        def _read_body(self) -> bytes:
            if hasattr(self, '_cached_body'): return self._cached_body
            length = self._length() or 0
            self._cached_body = self.rfile.read(length) if length > 0 else b''
            if len(self._cached_body)!=length: raise ValueError('Content-Length mismatch')
            return self._cached_body

        def do_OPTIONS(self):
            denied = security.check(policy, 'OPTIONS', urlparse(self.path).path, self._headers(), None, secure_transport=isinstance(self.connection,ssl.SSLSocket))
            if denied:
                return self._send(denied[0], {'detail': denied[1]})
            self._send(204, b'', 'text/plain')

        def _dispatch(self, method: str):
            url = urlparse(self.path)
            qs = parse_qs(url.query, keep_blank_values=True)
            denied = security.check(policy, method, url.path, self._headers(), self._length(), secure_transport=isinstance(self.connection,ssl.SSLSocket))
            if denied:
                return self._send(denied[0], {'detail': denied[1]})
            if not url.path.startswith('/api/'):
                return self._static(url.path) if method in ('GET', 'HEAD') else self._send(404, {'detail': 'Not Found'})
            from .api_15 import dispatch, error_response
            try:
                result = dispatch(method,url.path,self._headers(),self._read_body(),qs,self.client_address[0])
            except Exception as exc:
                result = error_response(exc)
            if result is not None:
                return self._send(*result)
            if url.path.startswith('/api/biosignals/'):
                try:
                    from .bio_api import dispatch
                    raw = self._read_body()
                    payload = json.loads(raw) if raw else {}
                    if not isinstance(payload, dict): raise ValueError('Expected JSON object')
                    return self._send(200, dispatch(method, url.path, payload, qs))
                except (ValueError, OSError, KeyError) as exc:
                    return self._send(400, {'detail': str(exc)})
                except Exception as exc:
                    return self._send(500, {'detail': f'Biosignal operation failed: {type(exc).__name__}'})
            for meth, rx, handler in COMPILED:
                m = rx.match(url.path)
                if not m or meth != method:
                    continue
                try:
                    if handler == 'session':
                        return self._send(200, security.session_payload(policy))
                    if isinstance(handler, tuple):
                        model, fn = handler
                        raw = self._read_body() or b'{}'
                        parsed = model.model_validate_json(raw)
                        return self._send(200, fn(m.groupdict(), qs, parsed))
                    return self._send(200, handler(m.groupdict(), qs))
                except ValidationError as exc:
                    return self._send(422, {'detail': json.loads(exc.json(include_url=False))})
                except QueryError as exc:
                    return self._send(422, {'detail': str(exc)})
                except service.NotFound as exc:
                    return self._send(404, {'detail': str(exc)})
                except service.BadRequest as exc:
                    return self._send(400, {'detail': str(exc)})
                except service.Unavailable as exc:
                    return self._send(503, {'detail': str(exc)})
                except ValueError as exc:  # e.g. nasa_research input errors
                    return self._send(400, {'detail': str(exc)})
                except OSError as exc:  # network-backed endpoints while offline
                    return self._send(503, {'detail': f'Service unavailable: {type(exc).__name__}: {exc}'})
                except Exception as exc:  # 1.0: never drop the connection without a response (FastAPI returns 500 too)
                    return self._send(500, {'detail': f'Internal error: {type(exc).__name__}'})
            return self._send(404, {'detail': 'Not Found'})

        def _static(self, path: str):
            if static_dir is None:
                return self._send(404, {'detail': 'Not Found'})
            target = None
            # v0.8: large assets (GLB models) live once in web/frontend/public; a build may omit them.
            for root in (static_dir, static_dir.parent / 'public'):
                base = root.resolve()
                cand = (base / unquote(path).lstrip('/')).resolve()
                # 1.4: is_relative_to instead of a string prefix (".../dist-offline-evil" bypass).
                if cand.is_relative_to(base) and cand.is_file():
                    target = cand
                    break
            if target is None:
                target = static_dir / 'index.html'
            ctype = mimetypes.guess_type(str(target))[0] or 'application/octet-stream'
            if target.suffix == '.glb':
                ctype = 'model/gltf-binary'
            data = target.read_bytes()
            if target.name == 'index.html':
                data = security.inject_token(data.decode('utf-8'), policy).encode('utf-8')
                ctype = 'text/html; charset=utf-8'
                return self._send(200, data, ctype, {'Cache-Control': 'no-store'})
            return self._send(200, data, ctype)

        def do_GET(self):
            self._dispatch('GET')

        def do_HEAD(self):
            self._dispatch('HEAD')

        def do_POST(self):
            self._dispatch('POST')

        def do_PATCH(self):
            self._dispatch('PATCH')

        def do_DELETE(self):
            self._dispatch('DELETE')

    return Handler


class ManagedHTTPServer(ThreadingHTTPServer):
    science_started = False
    def server_close(self):
        try: super().server_close()
        finally:
            if self.science_started:
                from .persistence.science_lifecycle import stop
                self.science_started=False
                stop()


def serve(host='127.0.0.1', port=8000, static: str | None = None, policy: security.Policy | None = None, tls_context: ssl.SSLContext | None = None):
    """Create (not start) the server. ``httpd.policy`` holds the per-launch token."""
    policy = policy or security.Policy()
    if host not in ('127.0.0.1','localhost','::1') and (not policy.remote or tls_context is None):
        raise ValueError('Non-loopback binding requires remote policy and a TLS context')
    if policy.remote and tls_context is None:
        raise ValueError('The stdlib remote server requires TLS')
    db.init_db()
    static_dir = Path(static).resolve() if static else None
    policy = policy or security.Policy()
    httpd = ManagedHTTPServer((host, port), make_handler(static_dir, policy))
    from .persistence.science_lifecycle import start
    try:
        start(); httpd.science_started=True
    except Exception:
        httpd.server_close(); raise
    if tls_context is not None:
        httpd.socket = tls_context.wrap_socket(httpd.socket, server_side=True)
    httpd.daemon_threads = True
    httpd.policy = policy
    return httpd


if __name__ == '__main__':
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--host', default='127.0.0.1')
    ap.add_argument('--port', type=int, default=8000)
    ap.add_argument('--static', default=None, help='Serve a built frontend directory')
    a = ap.parse_args()
    if a.host not in ('127.0.0.1', 'localhost', '::1'):
        ap.error('AETHER binds to loopback only (127.0.0.1); remote exposure is not supported')
    srv = serve(a.host, a.port, a.static)
    print(f'AETHER fallback API on http://{a.host}:{a.port}  (static: {a.static or "off"})')
    srv.serve_forever()
