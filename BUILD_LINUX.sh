#!/usr/bin/env bash
# AETHER native Linux release; requires running this on Linux x86_64.
set -Eeuo pipefail
cd "$(dirname "$0")"
command -v python3 >/dev/null || { echo "Python3 missing"; exit 2; }
command -v npm >/dev/null || { echo "Node/npm missing"; exit 2; }
if ! pkg-config --exists gtk+-3.0 2>/dev/null; then
  echo "Install build dependencies first: sudo apt install python3-venv python3-dev python3-gi build-essential pkg-config libcairo2-dev libgirepository1.0-dev gir1.2-gtk-3.0 gir1.2-webkit2-4.1 libwebkit2gtk-4.1-0"
  exit 2
fi
pushd web/frontend >/dev/null
npm ci
npm run typecheck
npm test
npm run build
popd >/dev/null
python3 -m venv --system-site-packages .build-venv-linux
source .build-venv-linux/bin/activate
python -m pip install -r requirements-desktop-linux.txt
python -m pip install -r web/backend/requirements.txt
python - <<'PY_CHECK'
import webview, bleak, argon2, gi
print('Required Linux desktop imports OK')
PY_CHECK
# Intentionally run tests against real dependencies; no test auth shims.
(cd web/backend && python -m pytest -q -p no:cacheprovider tests)
python -m PyInstaller --noconfirm --clean --onedir --windowed \
  --name AETHER --paths web/backend \
  --collect-submodules app --collect-submodules mission_systems \
  --collect-submodules bleak --collect-submodules gi --collect-data webview \
  --hidden-import release_smoke \
  --add-data 'web/frontend/dist:web/frontend/dist' \
  --add-data 'web/backend/app/migrations:app/migrations' desktop_native.py
./dist/AETHER/AETHER --smoke-test --report linux-smoke.json
python - <<'PY_PACK'
import tarfile, pathlib, hashlib
src=pathlib.Path('dist/AETHER'); target=pathlib.Path('AETHER_1_5_UNIFIED_LINUX_x86_64.tar.gz')
with tarfile.open(target,'w:gz') as t: t.add(src,arcname='AETHER')
print(target, 'sha256',hashlib.sha256(target.read_bytes()).hexdigest())
PY_PACK
echo 'Linux build created. Manual GUI + BLE hardware tests still required.'
