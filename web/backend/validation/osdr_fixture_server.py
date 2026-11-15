"""Local OSDR-shaped fixture server for offline tests and browser E2E (AETHER 1.4).

Serves the OSDR search / file-catalog / download URL shapes from
tests/fixtures. Start AETHER with AETHER_OSDR_TEST_MIRROR=http://127.0.0.1:<port>
to point the NASA client here; every record is then labelled
"TEST FIXTURE MIRROR — NOT NASA DATA" by app.nasa_research.

    python validation/osdr_fixture_server.py --port 18790
"""
from __future__ import annotations

import argparse
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

FIX = Path(__file__).resolve().parents[1] / 'tests' / 'fixtures'
CSV_NAME = 'LSDS-8_Comprehensive_Metabolic_Panel_CMP_TRANSFORMED.csv'
NON_UTF8_NAME = 'LSDS-8_Multiplex_serum_cardiovascular_EvePanel_TRANSFORMED.csv'
REDIRECT_NAME = 'LSDS-8_Multiplex_serum.cardiovascular.EvePanel_SUBMITTED.csv'


def make(port_holder: dict):
    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def _send(self, status, body: bytes, ctype='application/json', extra=None):
            self.send_response(status)
            self.send_header('Content-Type', ctype)
            self.send_header('Content-Length', str(len(body)))
            for k, v in (extra or {}).items():
                self.send_header(k, v)
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            u = urlparse(self.path)
            q = parse_qs(u.query)
            if u.path == '/osdr/data/search':
                hits = json.loads((FIX / 'osdr_search_hits.json').read_text())
                term = q.get('term', [''])[0].lower()
                if term.startswith('osd-'):
                    hits['hits']['hits'] = [h for h in hits['hits']['hits'] if h['_source']['Accession'].lower() == term]
                return self._send(200, json.dumps(hits).encode())
            if u.path == '/osdr/data/osd/files/575':
                listing = json.loads((FIX / 'osdr_osd575_files.json').read_text())
                for f in listing['studies']['OSD-575']['study_files']:
                    if f['file_name'] == CSV_NAME:
                        f['file_size'] = (FIX / 'synthetic_cmp_structure_fixture.csv').stat().st_size
                return self._send(200, json.dumps(listing).encode())
            if u.path == '/geode-py/ws/studies/OSD-575/download':
                name = q.get('file', [''])[0]
                if name == CSV_NAME:
                    return self._send(200, (FIX / 'synthetic_cmp_structure_fixture.csv').read_bytes(), 'text/csv')
                if name == NON_UTF8_NAME:
                    return self._send(200, b'\xff\xfe\x00bad,bytes\n', 'text/csv')
                if name == REDIRECT_NAME:
                    return self._send(302, b'', 'text/plain', {'Location': 'http://169.254.169.254/latest/meta-data'})
            return self._send(404, b'{"error":"not in fixture"}')
    return H


def start(port: int = 0):
    holder: dict = {}
    srv = ThreadingHTTPServer(('127.0.0.1', port), make(holder))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('--port', type=int, default=18790)
    s = start(ap.parse_args().port)
    print(f'OSDR fixture mirror (NOT NASA) on http://127.0.0.1:{s.server_port}', flush=True)
    threading.Event().wait()
