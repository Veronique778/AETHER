"""Deterministic mock Bluetooth HRS device harness (AETHER 1.4).

Drives the REAL app.ble_sensor.Sensor acquisition code through a scripted fake
BLE transport: discovery, connection, notifications (HR, RR, contact flags,
corrupt packets), link loss, automatic reconnection and user disconnect.
No radio is used. This verifies software behaviour only; PHYSICAL HARDWARE
VERIFICATION REMAINS PENDING.

    python validation/mock_hrs_harness.py --report mock_hrs_report.json
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
import time
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

HRS = '0000180d-0000-1000-8000-00805f9b34fb'


def hrs_packet(hr: int, rr_ms: list[float] = (), contact: bool | None = True, uint16: bool = False) -> bytes:
    """Encode a Heart Rate Measurement (0x2A37) notification per the Bluetooth SIG spec."""
    flags = 0
    if uint16:
        flags |= 0x01
    if contact is not None:
        flags |= 0x04 | (0x02 if contact else 0)
    if rr_ms:
        flags |= 0x10
    body = bytes([flags]) + (hr.to_bytes(2, 'little') if uint16 else bytes([hr]))
    for rr in rr_ms:
        body += round(rr * 1024 / 1000).to_bytes(2, 'little')
    return body


class MockLink:
    """Scripted transport shared by every client the factory creates."""

    def __init__(self, fail_reconnects: int = 0, hang_connect: bool = False):
        self.fail_reconnects = fail_reconnects
        self.hang_connect = hang_connect
        self.connects = 0
        self.clients: list[MockClient] = []

    def factory(self, device, disconnected_callback):
        client = MockClient(self, disconnected_callback)
        self.clients.append(client)
        return client

    @property
    def current(self) -> 'MockClient':
        return self.clients[-1]


class MockClient:
    def __init__(self, link: MockLink, callback):
        self.link, self.callback, self.is_connected, self.notify = link, callback, False, None
        self.services = SimpleNamespace(get_service=lambda u: object(), get_characteristic=lambda u: object())

    async def connect(self):
        import asyncio
        if self.link.hang_connect:
            await asyncio.sleep(3600)
        self.link.connects += 1
        if self.link.connects > 1 and self.link.fail_reconnects > 0:
            self.link.fail_reconnects -= 1
            raise OSError('mock: device out of range')
        self.is_connected = True

    async def start_notify(self, characteristic, notify):
        self.notify = notify

    async def disconnect(self):
        was = self.is_connected
        self.is_connected = False
        if was:
            self.callback(self)

    def push(self, packet: bytes):
        self.notify(None, packet)

    def drop_link(self):
        """Simulate an unexpected radio link loss (bleak disconnected_callback)."""
        self.is_connected = False
        self.callback(self)


async def _scan():
    return {'MOCK:HRS:01': (SimpleNamespace(name='MOCK HRS strap (simulated transport)'),
                            SimpleNamespace(service_uuids=[HRS]))}


def wait_for(predicate, timeout=6.0):
    end = time.time() + timeout
    while time.time() < end:
        if predicate():
            return True
        time.sleep(0.02)
    return False


def run(report_path: str | None = None) -> dict:
    tmp = tempfile.mkdtemp(prefix='aether-mock-hrs-')
    os.environ['AETHER_DB_PATH'] = str(Path(tmp) / 'mock.sqlite3')
    from app import db, biosignals as bio
    from app.ble_sensor import Sensor
    db.DB_PATH = Path(tmp) / 'mock.sqlite3'
    db.init_db(); bio.init()
    checks = []

    def check(name, ok, detail=''):
        checks.append({'check': name, 'pass': bool(ok), 'detail': detail})

    link = MockLink(fail_reconnects=1)
    sensor = Sensor(link.factory, _scan, reconnect_delays=(0.05, 0.05, 0.05))
    try:
        found = sensor.call(sensor.scan())
        check('discovery lists advertised HRS device', found and found[0]['advertised_hrs'], json.dumps(found))
        st = sensor.call(sensor.connect('MOCK:HRS:01'))
        sid = st['session_id']
        check('connection opens a live_sensor session', st['connection'] == 'connected' and sid)
        link.current.push(hrs_packet(64, [937.5, 950.0]))
        s = sensor.status()
        check('HR decoded (uint8) with RR', s['heart_rate'] == 64 and s['rr_available'], json.dumps(s))
        link.current.push(hrs_packet(300, uint16=True))
        check('implausible HR 300 bpm rejected, not displayed', sensor.status()['heart_rate'] is None and sensor.status()['quality'] == 'rejected')
        link.current.push(hrs_packet(70, contact=False))
        check('no skin contact flagged', sensor.status()['quality'] == 'no_contact')
        link.current.push(b'\x10\x40\x01')
        check('corrupt packet counted, no value shown', sensor.status()['quality'] == 'corrupt' and sensor.status()['corrupt_packets'] == 1)
        link.current.drop_link()
        check('link loss -> reconnecting, value cleared', sensor.status()['connection'] == 'reconnecting' and sensor.status()['heart_rate'] is None)
        ok = wait_for(lambda: sensor.status()['connection'] == 'connected')
        check('reconnects after one failed attempt into SAME session', ok and sensor.state['session_id'] == sid
              and sensor.status()['reconnects'] == 1, json.dumps(sensor.status()))
        link.current.push(hrs_packet(66, [909.0]))
        check('measurements resume after reconnect', sensor.status()['heart_rate'] == 66)
        with db.connect() as c:
            gap = c.execute("SELECT COUNT(*) FROM bio_measurements WHERE session_id=? AND missing=1 AND quality='connection_lost'", (sid,)).fetchone()[0]
            total = c.execute('SELECT COUNT(*) FROM bio_measurements WHERE session_id=?', (sid,)).fetchone()[0]
        check('dropout stored as explicit missing row', gap == 1, f'gap rows={gap}, total rows={total}')
        sensor.call(sensor.disconnect())
        check('user disconnect: no reconnect, session saved', sensor.status()['connection'] == 'disconnected'
              and bio.session(sid)['status'] == 'saved')
        stale_token = sensor.token
        with db.connect() as c:
            before = c.execute('SELECT COUNT(*) FROM bio_measurements WHERE session_id=?', (sid,)).fetchone()[0]
        sensor.notification(hrs_packet(99), stale_token)
        with db.connect() as c:
            after = c.execute('SELECT COUNT(*) FROM bio_measurements WHERE session_id=?', (sid,)).fetchone()[0]
        check('no measurements fabricated after disconnect', after == before, f'{before}->{after}')
        analysis = bio.analyze(sid)
        check('analysis runs on recorded session (short -> insufficient_data)', analysis['outcome'] == 'insufficient_data')
    finally:
        try:
            sensor.call(sensor.disconnect())
        except Exception:
            pass
        sensor.loop.call_soon_threadsafe(sensor.loop.stop)

    # Failure path: every reconnect fails -> session finalised, never filled in.
    link2 = MockLink(fail_reconnects=99)
    s2 = Sensor(link2.factory, _scan, reconnect_delays=(0.02, 0.02))
    try:
        s2.call(s2.scan()); sid2 = s2.call(s2.connect('MOCK:HRS:01'))['session_id']
        link2.current.push(hrs_packet(61)); link2.current.drop_link()
        ok = wait_for(lambda: s2.status()['connection'] == 'disconnected')
        check('failed reconnection finalises session as saved_after_connection_loss',
              ok and bio.session(sid2)['status'] == 'saved_after_connection_loss', s2.status().get('error') or '')
    finally:
        s2.loop.call_soon_threadsafe(s2.loop.stop)

    # Timeout path.
    link3 = MockLink(hang_connect=True)
    s3 = Sensor(link3.factory, _scan, connect_timeout=0.2)
    try:
        s3.call(s3.scan()); st3 = s3.call(s3.connect('MOCK:HRS:01'))
        check('connection timeout reported, no session left recording', st3['connection'] == 'disconnected'
              and 'timed out' in (st3['error'] or ''), st3['error'] or '')
    finally:
        s3.loop.call_soon_threadsafe(s3.loop.stop)

    result = {'harness': 'aether-mock-hrs-1.4', 'transport': 'simulated (no radio)',
              'physical_hardware_verified': False, 'passed': sum(c['pass'] for c in checks),
              'failed': sum(not c['pass'] for c in checks), 'checks': checks}
    if report_path:
        Path(report_path).write_text(json.dumps(result, indent=2), encoding='utf-8')
    return result


if __name__ == '__main__':
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--report')
    out = run(ap.parse_args().report)
    for c in out['checks']:
        print(('PASS ' if c['pass'] else 'FAIL ') + c['check'])
    print(f"{out['passed']} passed, {out['failed']} failed · physical hardware verified: NO")
    sys.exit(1 if out['failed'] else 0)
