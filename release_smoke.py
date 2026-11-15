"""Release acceptance against the same desktop server and real SQLite. Synthetic data only.

Reconstructed from the frozen bytecode of AETHER_1_5.exe (the 1.5 source was not in the handoff) and extended for the
BLE personal integration: Bluetooth diagnostics in the frozen runtime, the SIMULATED HRS strap through the real
device manager / HRS decoder / personal SQLite / PHANTOM path, isolation of a second account and logout stopping the
recording. No physical Bluetooth device is touched by this smoke test (hardware_verified stays false).
"""
import http.client
import json
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path


def run(report, data, phase):
    from desktop_native import start_server, MODELS
    server, url = start_server()
    port = server.server_port
    launch = server.policy.token
    checks = []

    def check(name, passed, detail=''):
        checks.append({'check': name, 'passed': bool(passed), 'detail': str(detail)[:300]})

    def call(method, path, body=None, bearer=None, with_launch=True):
        c = http.client.HTTPConnection('127.0.0.1', port, timeout=60)
        headers = {'Content-Type': 'application/json'}
        if with_launch:
            headers['X-AETHER-Token'] = launch
        if bearer:
            headers['Authorization'] = 'Bearer ' + bearer
        c.request(method, path, json.dumps(body).encode() if body is not None else None, headers)
        r = c.getresponse(); raw = r.read(); status = r.status; c.close()
        try:
            value = json.loads(raw)
        except ValueError:
            value = raw
        return status, value

    password = 'Release-Control-Password-2026!'
    try:
        code, html = call('GET', '/')
        check('production React assets and launch token', code == 200 and b'/assets/' in html and launch.encode() in html)
        for model in MODELS:
            code, raw = call('GET', '/models/' + model)
            check('GLB ' + model, code == 200 and raw[:4] == b'glTF')
        check('launch token required', call('GET', '/api/profile', with_launch=False)[0] == 401)
        check('personal Bearer required', call('GET', '/api/profile')[0] == 401)
        # --- 1.5 BLE: frozen runtime imports (proves packaging, not hardware) ---
        for mod in ['bleak'] + (['bleak.backends.winrt.scanner', 'bleak.backends.winrt.client',
                                 'winrt.windows.devices.radios'] if sys.platform == 'win32' else []):
            try:
                __import__(mod)
                check('BLE runtime import ' + mod, True)
            except Exception as exc:
                check('BLE runtime import ' + mod, False, f'{type(exc).__name__}: {exc}')
        check('legacy unauthenticated BLE route stays isolated', call('POST', '/api/biosignals/sensor/scan', {})[0] in (401, 410))
        check('BLE diagnostics require personal Bearer', call('GET', '/api/devices/ble-diagnostics')[0] == 401)
        if phase == 'first':
            login = 'smoke_' + str(time.time_ns())
            code, reg = call('POST', '/api/auth/register', dict(login=login, password=password, display_name='Release control'))
            check('registration and recovery code', code == 201 and len(reg.get('recovery_code', '')) >= 32)
            code, auth = call('POST', '/api/auth/login', dict(login=login, password=password))
            check('login', code == 200)
            token = auth['access_token']; aid = auth['user']['astronaut_id']
            check('own profile', call('GET', '/api/profile', bearer=token)[0] == 200)
            start = (datetime.now(timezone.utc) - timedelta(hours=4)).replace(microsecond=0)
            iso = lambda t: t.isoformat().replace('+00:00', 'Z')
            code, manual = call('POST', '/api/measurements', dict(idempotency_key='manual-control', source='Manual control',
                                signal='heart_rate', value=70, unit='bpm', measured_at=iso(start - timedelta(minutes=5)),
                                origin='manual', quality='unverified'), token)
            check('manual measurement provenance', code == 201 and manual['measurement']['origin'] == 'manual'
                  and manual['measurement']['quality'] == 'unverified', code)
            rows = [dict(idempotency_key=f'control-{i}', source='SYNTHETIC release control', signal='heart_rate',
                         value=64 + (15 if i >= 3300 else 0), unit='bpm', measured_at=iso(start + timedelta(seconds=2 * i)),
                         origin='simulated', quality='screened') for i in range(5400)]
            for i in range(0, len(rows), 500):
                code, value = call('POST', '/api/measurements/batch', {'measurements': rows[i:i + 500]}, token)
                check('persist batch ' + str(i), code == 200, value if code != 200 else '')
            request = {'astronaut_id': aid, 'from': iso(start), 'to': iso(start + timedelta(hours=3)), 'data_classes': ['synthetic']}
            code, result = call('POST', '/api/phantom-analyses', request, token)
            check('PHANTOM flag and SYNTHETIC explanation', code in (200, 201) and result.get('outcome') == 'flag'
                  and result['explain']['data_label'] == 'SYNTHETIC', result if code != 200 else '')
            code, same = call('POST', '/api/phantom-analyses', request, token)
            check('idempotent analysis', code in (200, 201) and same['analysis_id'] == result['analysis_id'])
            code, short = call('POST', '/api/phantom-analyses', {**request, 'to': iso(start + timedelta(minutes=50))}, token)
            check('insufficient baseline', code in (200, 201) and short.get('outcome') == 'insufficient_data')

            # --- 1.5 BLE personal path with the explicit SIMULATED strap (never real_wearable) ---
            code, diag = call('GET', '/api/devices/ble-diagnostics', bearer=token)
            check('BLE diagnostics structured', code == 200 and {'radio_available', 'ble_dependency_available', 'scan_available',
                  'supported_protocol', 'reason_code'} <= set(diag) and diag.get('hardware_verified') is False, diag)
            code, sim = call('POST', '/api/devices/simulated', {}, token)
            check('simulated HRS device registered (SYNTHETIC)', code in (200, 201) and sim.get('data_class') == 'synthetic', sim)
            did = sim.get('device_id')
            code, conn = call('POST', f'/api/devices/{did}/connect', {'astronaut_id': aid}, token)
            check('simulated HRS connect → recording', code == 200 and conn.get('recording') is True, conn)
            status = {}
            for _ in range(40):
                time.sleep(0.5)
                code, status = call('GET', f'/api/devices/{did}/status', bearer=token)
                if status.get('stored_samples', 0) >= 4:
                    break
            check('simulated HRS notifications decoded and stored', status.get('stored_samples', 0) >= 4
                  and status.get('data_class') == 'synthetic' and status.get('simulated') is True, status)
            check('double connect refused', call('POST', f'/api/devices/{did}/connect', {'astronaut_id': aid}, token)[0] == 409)
            code, reg_b = call('POST', '/api/auth/register', dict(login=login + '_b', password=password, display_name='Second control'))
            code, auth_b = call('POST', '/api/auth/login', dict(login=login + '_b', password=password))
            check('second login', code == 200)
            other = auth_b['access_token']
            check('foreign analysis denied', call('GET', '/api/phantom-analyses/' + result['analysis_id'], bearer=other)[0] in (403, 404))
            check('foreign analysis run denied', call('POST', '/api/phantom-analyses', request, other)[0] in (403, 404))
            check('foreign device status denied', call('GET', f'/api/devices/{did}/status', bearer=other)[0] in (403, 404))
            check('foreign device stop denied', call('POST', f'/api/devices/{did}/disconnect', {}, other)[0] in (403, 404))
            code, theirs = call('GET', '/api/measurements', bearer=other)
            check('second account has no measurements', code == 200 and theirs['items'] == [])
            code, stop = call('POST', f'/api/devices/{did}/disconnect', {}, token)
            check('stop & save simulated recording', code == 200 and stop.get('session_status') == 'saved', stop)
            sid = stop.get('session_id')
            code, page = call('GET', f'/api/measurements?session_id={sid}&limit=500', bearer=token)
            items = page.get('items', []) if code == 200 else []
            check('recording rows are SIMULATED provenance in SQLite', items and all(i['origin'] == 'simulated' for i in items)
                  and not any((i.get('metadata') or {}).get('data_class') == 'real_wearable' for i in items), len(items))
            # logout while recording: recording is stopped & saved before the token is revoked
            call('POST', f'/api/devices/{did}/connect', {'astronaut_id': aid}, token)
            time.sleep(1.5)
            check('logout revoked token', call('POST', '/api/auth/logout', {}, token)[0] == 200
                  and call('GET', '/api/profile', bearer=token)[0] == 401)
            code, auth2 = call('POST', '/api/auth/login', dict(login=login, password=password))
            code, st2 = call('GET', f'/api/devices/{did}/status', bearer=auth2['access_token'])
            check('logout stopped the recording', code == 200 and st2.get('lifecycle_state') == 'disconnected', st2)
            Path(data, 'smoke-state.json').write_text(json.dumps({'login': login, 'analysis_id': result['analysis_id'],
                                                                 'digest': result['input']['measurement_digest'],
                                                                 'session_id': sid, 'session_rows': len(items)}), encoding='utf-8')
        else:
            state = json.loads(Path(data, 'smoke-state.json').read_text(encoding='utf-8'))
            code, auth = call('POST', '/api/auth/login', dict(login=state['login'], password=password))
            check('restart login', code == 200)
            code, saved = call('GET', '/api/phantom-analyses/' + state['analysis_id'], bearer=auth['access_token'])
            check('restart same analysis and digest', code == 200 and saved['input']['measurement_digest'] == state['digest']
                  and saved['explain']['data_label'] == 'SYNTHETIC')
            code, page = call('GET', f"/api/measurements?session_id={state['session_id']}&limit=500", bearer=auth['access_token'])
            check('restart: simulated BLE recording persisted', code == 200 and len(page['items']) == state['session_rows'], code)
    except Exception as exc:
        check('acceptance error', False, f'{type(exc).__name__}: {exc}')
    finally:
        server.shutdown(); server.server_close()

    if phase == 'first':
        from desktop_native import resource_root
        cmd = [sys.executable] + ([] if getattr(sys, 'frozen', False) else [str(resource_root() / 'desktop_native.py')])
        out = Path(data, 'restart-report.json')
        r = subprocess.run(cmd + ['--smoke-test', '--smoke-phase', 'restart', '--data-dir', str(data), '--report', str(out)],
                           capture_output=True, timeout=240)
        check('restart process exit', r.returncode == 0, (r.stderr or b'')[-300:])
        try:
            checks += json.loads(out.read_text(encoding='utf-8'))['checks']
        except (OSError, ValueError, KeyError):
            pass
    result = {'status': 'PASS' if all(c['passed'] for c in checks) else 'FAIL', 'frozen': bool(getattr(sys, 'frozen', False)),
              'checks': checks, 'passed': sum(c['passed'] for c in checks), 'failed': sum(not c['passed'] for c in checks),
              'not_tested': ['physical BLE', 'native window rendering', 'clean Windows install']}
    if report:
        Path(report).write_text(json.dumps(result, indent=2), encoding='utf-8')
    if phase == 'first':
        for c in checks:
            print(('PASS ' if c['passed'] else 'FAIL ') + c['check'] + (': ' + c['detail'] if not c['passed'] else ''))
        print(f"{result['passed']} passed, {result['failed']} failed")
    return 0 if result['status'] == 'PASS' else 1
