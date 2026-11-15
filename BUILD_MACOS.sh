#!/usr/bin/env bash
# AETHER native macOS release; must run on a macOS machine, NOT Linux or Windows.
set -Eeuo pipefail
[[ "$(uname -s)" == Darwin ]] || { echo 'Build this on macOS.'; exit 2; }
cd "$(dirname "$0")"
command -v python3 >/dev/null && command -v npm >/dev/null || { echo 'Install Python 3.13 and Node 20+ first.'; exit 2; }
pushd web/frontend >/dev/null
npm ci
npm run typecheck
npm test
npm run build
popd >/dev/null
python3 -m venv .build-venv-macos
source .build-venv-macos/bin/activate
python -m pip install -r requirements-desktop-macos.txt
python -m pip install -r web/backend/requirements.txt
python - <<'PY_CHECK'
import webview, bleak, argon2, objc
print('Required macOS desktop imports OK')
PY_CHECK
(cd web/backend && python -m pytest -q -p no:cacheprovider tests)
python -m PyInstaller --noconfirm --clean --onedir --windowed \
  --name AETHER --paths web/backend \
  --collect-submodules app --collect-submodules mission_systems \
  --collect-submodules bleak --collect-data webview \
  --hidden-import release_smoke \
  --add-data 'web/frontend/dist:web/frontend/dist' \
  --add-data 'web/backend/app/migrations:app/migrations' desktop_native.py
if [[ -x dist/AETHER.app/Contents/MacOS/AETHER ]]; then
  dist/AETHER.app/Contents/MacOS/AETHER --smoke-test --report macos-smoke.json
  ditto -c -k --sequesterRsrc --keepParent dist/AETHER.app AETHER_1_5_UNIFIED_MACOS.zip
elif [[ -x dist/AETHER/AETHER ]]; then
  ./dist/AETHER/AETHER --smoke-test --report macos-smoke.json
  ditto -c -k --sequesterRsrc --keepParent dist/AETHER AETHER_1_5_UNIFIED_MACOS.zip
else
  echo 'No runnable frozen app found after PyInstaller build'; exit 3
fi
shasum -a 256 AETHER_1_5_UNIFIED_MACOS.zip
echo 'macOS build created. Signing/notarization and BLE hardware tests still required.'
