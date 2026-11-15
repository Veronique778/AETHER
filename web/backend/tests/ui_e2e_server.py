"""TEST-ONLY server for the browser E2E (tests never run against a user's real data).

    python tests/ui_e2e_server.py --static ../frontend/dist --db /tmp/x.sqlite3 [--fake-bleak SCENARIO.json] [--port N]

Same code path as the desktop: app.devserver.serve() → release env (AETHER_RELEASE=1, legacy demo off) → the
production lifecycle Device Manager. Options that exist ONLY here, for the sandbox:
  --fake-bleak  puts tests/fakes/fake_bleak first on sys.path (test double of the bleak LIBRARY; see its README).
  argon2 shim   registered when argon2-cffi is not installed (cryptography-backed Argon2id, tests/be3_argon2_env.py).
"""
import argparse
import json
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ap = argparse.ArgumentParser()
ap.add_argument('--static', required=True)
ap.add_argument('--db', required=True)
ap.add_argument('--port', type=int, default=0)
ap.add_argument('--fake-bleak')
a = ap.parse_args()
os.environ.update(AETHER_DB_PATH=a.db, AETHER_RELEASE='1', AETHER_LEGACY_DEMO='0')
os.environ.pop('AETHER_SESSION_TOKEN', None)
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE))
import be3_argon2_env  # noqa: E402,F401  (no-op when argon2-cffi is installed)
if a.fake_bleak:
    sys.path.insert(0, str(HERE / 'fakes' / 'fake_bleak'))
    os.environ['AETHER_FAKE_BLEAK_SCENARIO'] = Path(a.fake_bleak).read_text(encoding='utf-8')
from app.devserver import serve  # noqa: E402

srv = serve(port=a.port, static=a.static)
print(json.dumps({'port': srv.server_port}), flush=True)
try:
    srv.serve_forever()
finally:
    srv.server_close()
