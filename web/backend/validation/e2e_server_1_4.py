"""Browser-E2E server for AETHER 1.4 (development/test ONLY — never shipped as runtime).

* real app.devserver + dist-offline bundle + per-launch token (enforced)
* BLE: the REAL app.ble_sensor.Sensor driven by the deterministic mock transport from
  mock_hrs_harness (streams HR/RR once connected; drops the link once after 6 packets)
* NASA: optional local OSDR fixture mirror (--mirror) -> every record labelled NOT NASA

    python validation/e2e_server_1_4.py --port 18761 --static ../frontend/dist-offline [--mirror]
"""
import argparse
import os
import sys
import threading
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent)); sys.path.insert(0, str(HERE))

ap = argparse.ArgumentParser()
ap.add_argument('--port', type=int, required=True)
ap.add_argument('--static', required=True)
ap.add_argument('--mirror', action='store_true')
args = ap.parse_args()

if args.mirror:
    import osdr_fixture_server
    mirror = osdr_fixture_server.start(0)
    os.environ['AETHER_OSDR_TEST_MIRROR'] = f'http://127.0.0.1:{mirror.server_port}'
    print(f'mirror http://127.0.0.1:{mirror.server_port}', flush=True)

import mock_hrs_harness as mh  # noqa: E402
from app import bio_api  # noqa: E402
from app.ble_sensor import Sensor  # noqa: E402
from app.devserver import serve  # noqa: E402

link = mh.MockLink()
sensor = Sensor(link.factory, mh._scan, reconnect_delays=(0.5, 0.5, 0.5))
bio_api.sensor = sensor
import app.biosignals  # noqa: E402,F401


def stream():
    sent, dropped = 0, False
    while True:
        time.sleep(0.5)
        if sensor.state['connection'] != 'connected' or not link.clients or not link.current.is_connected or not link.current.notify:
            continue
        sent += 1
        link.current.push(mh.hrs_packet(60 + sent % 5, [1000.0 - sent % 5 * 10]))
        if sent == 6 and not dropped:
            dropped = True
            link.current.drop_link()


threading.Thread(target=stream, daemon=True).start()
srv = serve(port=args.port, static=args.static)
print(f'ready http://127.0.0.1:{args.port}', flush=True)
srv.serve_forever()
