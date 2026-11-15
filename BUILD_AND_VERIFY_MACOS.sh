#!/usr/bin/env bash
set -Eeuo pipefail
cd "$(dirname "$0")"
[[ $(uname) == Darwin ]] || { echo 'Must run on macOS'; exit 2; }
[[ -f web/frontend/src/features/personal/PersonalTwin.tsx ]] || { echo 'Missing latest PersonalTwin'; exit 2; }
rm -f AETHER_1_5_UNIFIED_MACOS.zip
bash BUILD_MACOS.sh
python3 tools/final_release_gate.py --platform macos --archive AETHER_1_5_UNIFIED_MACOS.zip --smoke macos-smoke.json
echo 'macOS release candidate ONLY; still test app GUI + Gatekeeper/signing + real BLE on native macOS.'
