"""Explicit SIMULATED Heart Rate Service transport (AETHER 1.5 BLE personal integration).

Purpose: let a signed-in user rehearse the complete Live Sensors workflow (connect → notifications → personal SQLite →
PHANTOM → history) on a computer without a chest strap. It is NOT a fallback for the radio and it is never chosen
automatically: it is used only for a device the server registered through POST /api/devices/simulated, whose
hardware address carries the reserved prefix SIM_ADDRESS_PREFIX.

Provenance is fixed by the server: DATA_CLASS = 'synthetic' → Backend №2 origin 'simulated', session source_type
'simulated_demo', source label 'AETHER simulated HRS · SYNTHETIC'. No request field can turn these rows into
'real_wearable'. Packets are produced with app.devices.hrs.encode (the exact 0x2A37 byte layout) and therefore pass
through the same decoder, quality, gap and storage code as a physical strap.
"""
from __future__ import annotations

import math
import random
import threading

from . import hrs

SIM_ADDRESS_PREFIX = 'AETHER-SIM-HRS-'
SIM_DEVICE_NAME = 'AETHER simulated HRS · SYNTHETIC'
SIM_SOURCE = 'AETHER simulated HRS · SYNTHETIC'


def is_simulated_address(address: str | None) -> bool:
    return isinstance(address, str) and address.upper().startswith(SIM_ADDRESS_PREFIX)


class _SimLink:
    def __init__(self, on_notify, on_disconnect, interval_s: float, seed: int):
        self.on_notify, self.on_disconnect = on_notify, on_disconnect
        self.interval_s = interval_s
        self.stop = threading.Event()
        self.rng = random.Random(seed)
        self.thread = threading.Thread(target=self._run, daemon=True, name='aether-sim-hrs')

    def _run(self):
        i = 0
        while not self.stop.wait(self.interval_s):
            i += 1
            hr = 66 + 4 * math.sin(i / 30) + self.rng.uniform(-1.5, 1.5)
            hr_i = int(round(hr))
            rr_ms = 60000.0 / max(hr, 30)
            rr_raw = int(round(rr_ms * 1024 / 1000))
            try:
                self.on_notify(hrs.encode(hr_i, [rr_raw], contact=True))
            except Exception:
                pass


class SimulatedHrsTransport:
    DATA_CLASS = 'synthetic'
    KIND = 'simulated_hrs'

    def __init__(self, interval_s: float = 1.0):
        self.interval_s = interval_s
        self._links: set[_SimLink] = set()
        self._lock = threading.Lock()

    def availability(self):
        return True, None

    def scan(self, include_unadvertised, timeout_s):
        return []                     # the simulated strap is never "discovered" among real radio results

    def connect(self, hardware_address, on_notify, on_disconnect, timeout_s):
        if not is_simulated_address(hardware_address):
            raise ConnectionError('Not a simulated HRS address')
        link = _SimLink(on_notify, on_disconnect, self.interval_s, seed=hash(hardware_address) & 0xFFFF)
        with self._lock:
            self._links.add(link)
        link.thread.start()
        return link

    def disconnect(self, handle):
        if isinstance(handle, _SimLink):
            handle.stop.set()
            with self._lock:
                self._links.discard(handle)

    def diagnostics(self) -> dict:
        return {'transport': self.KIND, 'data_class': self.DATA_CLASS, 'available': True, 'hardware_verified': False}
