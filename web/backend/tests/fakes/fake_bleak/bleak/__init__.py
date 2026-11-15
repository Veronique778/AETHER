"""TEST DOUBLE of the `bleak` package (see ../README.md). Implements only what app.devices.runtime uses."""
from __future__ import annotations

import asyncio
import json
import os
import threading

__version__ = '0.0.0-aether-test-double'
HRS = '0000180d-0000-1000-8000-00805f9b34fb'
HRM = '00002a37-0000-1000-8000-00805f9b34fb'
BATTERY = '0000180f-0000-1000-8000-00805f9b34fb'


class BleakError(Exception):
    pass


_LOCK = threading.Lock()
_DEVICES: dict[str, dict] = {}
_CLIENTS: dict[str, 'BleakClient'] = {}
STATE = {'radio': 'on', 'scan_error': None, 'scans': 0, 'connects': 0}


def configure(devices: list[dict], radio: str = 'on', scan_error: str | None = None) -> None:
    """devices: [{address, name, advertise_hrs, has_hrs, rssi, interval_s, hr, uint16, contact, rr}]"""
    with _LOCK:
        _DEVICES.clear()
        for d in devices:
            _DEVICES[d['address']] = {'name': d.get('name', 'Test strap'), 'advertise_hrs': d.get('advertise_hrs', True),
                                      'has_hrs': d.get('has_hrs', True), 'rssi': d.get('rssi', -60),
                                      'interval_s': d.get('interval_s', 0.25), 'hr': d.get('hr', 72), 'uint16': d.get('uint16', False),
                                      'contact': d.get('contact', True), 'rr': d.get('rr', [853]), 'corrupt_every': d.get('corrupt_every', 0),
                                      'silent': d.get('silent', False)}
        STATE.update(radio=radio, scan_error=scan_error)


def device(address: str) -> dict:
    return _DEVICES[address]


def drop_link(address: str) -> bool:
    """Simulate a radio link loss: the client stops and its disconnected_callback fires."""
    c = _CLIENTS.get(address)
    if c is None:
        return False
    c._drop()
    return True


if os.environ.get('AETHER_FAKE_BLEAK_SCENARIO'):
    configure(json.loads(os.environ['AETHER_FAKE_BLEAK_SCENARIO']))


class BLEDevice:
    def __init__(self, address, name):
        self.address, self.name = address, name


class AdvertisementData:
    def __init__(self, service_uuids, local_name, rssi):
        self.service_uuids, self.local_name, self.rssi = service_uuids, local_name, rssi


class BleakScanner:
    @staticmethod
    async def discover(timeout=5.0, return_adv=False, **_kw):
        STATE['scans'] += 1
        await asyncio.sleep(min(float(timeout), 0.3))
        if STATE['radio'] == 'off':
            raise BleakError('Bluetooth device is turned off.')
        if STATE['radio'] == 'no_adapter':
            raise BleakError('No Bluetooth adapters found.')
        if STATE['scan_error']:
            raise BleakError(STATE['scan_error'])
        with _LOCK:
            items = list(_DEVICES.items())
        out = {}
        for addr, d in items:
            uuids = [HRS, BATTERY] if d['advertise_hrs'] else [BATTERY]
            out[addr] = (BLEDevice(addr, d['name']), AdvertisementData(uuids, d['name'], d['rssi']))
        return out if return_adv else [v[0] for v in out.values()]


class _Char:
    def __init__(self, uuid):
        self.uuid, self.properties = uuid, ['notify']


class _Services:
    def __init__(self, has_hrs):
        self.has_hrs = has_hrs

    def get_service(self, uuid):
        return object() if self.has_hrs and str(uuid).lower() == HRS else None

    def get_characteristic(self, uuid):
        return _Char(HRM) if self.has_hrs and str(uuid).lower() == HRM else None


def _encode(hr, rr, contact, uint16):
    flags = (0x01 if uint16 else 0) | (0x10 if rr else 0)
    if contact is not None:
        flags |= 0x04 | (0x02 if contact else 0)
    out = bytes([flags]) + int(hr).to_bytes(2 if uint16 else 1, 'little')
    for r in rr:
        out += int(r).to_bytes(2, 'little')
    return out


class BleakClient:
    def __init__(self, address_or_device, disconnected_callback=None, **_kw):
        self.address = getattr(address_or_device, 'address', address_or_device)
        self._cb = disconnected_callback
        self._task = None
        self.is_connected = False
        self.services = None

    async def connect(self, **_kw):
        STATE['connects'] += 1
        await asyncio.sleep(0.05)
        d = _DEVICES.get(self.address)
        if d is None or STATE['radio'] != 'on':
            raise BleakError(f'Device with address {self.address} was not found.')
        self.services = _Services(d['has_hrs'])
        self.is_connected = True
        _CLIENTS[self.address] = self
        return True

    async def start_notify(self, uuid, callback):
        d = _DEVICES[self.address]

        async def pump():
            i = 0
            while self.is_connected:
                await asyncio.sleep(d['interval_s'])
                if not self.is_connected:
                    break
                if d.get('silent'):
                    continue
                i += 1
                if d['corrupt_every'] and i % d['corrupt_every'] == 0:
                    data = bytes([0x10, 70, 1])                     # RR flag with an odd RR byte count → corrupt
                else:
                    data = _encode(d['hr'], d['rr'], d['contact'], d['uint16'])
                callback(None, bytearray(data))
        self._task = asyncio.ensure_future(pump())

    async def stop_notify(self, uuid):
        if self._task:
            self._task.cancel()

    async def disconnect(self):
        self.is_connected = False
        if self._task:
            self._task.cancel()
        _CLIENTS.pop(self.address, None)
        return True

    def _drop(self):
        self.is_connected = False
        _CLIENTS.pop(self.address, None)
        if self._cb:
            self._cb(self)
