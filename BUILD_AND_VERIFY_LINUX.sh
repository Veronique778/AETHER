#!/usr/bin/env bash
set -Eeuo pipefail
cd "$(dirname "$0")"
[[ $(uname) == Linux ]] || { echo 'Must run on Linux'; exit 2; }
[[ -f web/frontend/src/features/personal/PersonalTwin.tsx ]] || { echo 'Missing latest PersonalTwin'; exit 2; }
rm -f AETHER_1_5_UNIFIED_LINUX_x86_64.tar.gz
bash BUILD_LINUX.sh
python3 tools/final_release_gate.py --platform linux --archive AETHER_1_5_UNIFIED_LINUX_x86_64.tar.gz --smoke linux-smoke.json
echo 'Linux release candidate ONLY; still test native GUI/GTK/WebKit + real BLE on Linux.'
