"""Clock, scheduler and BLE transport abstractions for the Device Manager (AETHER 1.5, Backend №3).

The manager never calls bleak, time.time() or threading.Timer directly, so every lifecycle path (notifications,
link loss, reconnect, staleness, storage outage, crash) is testable deterministically with tests/fakes/ble_mock.py.

BleakTransport is the production transport (Bluetooth SIG HRS over bleak / WinRT on Windows). It is IMPLEMENTED but
NOT hardware-verified and NOT exercised by automated tests (bleak is not installed in the build environment).
"""
from __future__ import annotations

import asyncio
import importlib.util  # noqa: F401  (kept for backwards-compatible imports)
import sys
import threading
import time
from datetime import datetime, timezone
from typing import Callable, Protocol

from .hrs import HRM_CHAR_UUID, HRS_SERVICE_UUID


class Clock(Protocol):
    def now(self) -> datetime: ...          # aware UTC
    def monotonic(self) -> float: ...


class SystemClock:
    def now(self) -> datetime:
        return datetime.now(timezone.utc)

    def monotonic(self) -> float:
        return time.monotonic()


class Scheduler(Protocol):
    def call_later(self, delay_s: float, fn: Callable[[], None]) -> object: ...
    def cancel(self, handle: object) -> None: ...


class ThreadScheduler:
    """Production scheduler: daemon threading.Timer per call (callbacks run off the HTTP threads)."""

    def call_later(self, delay_s, fn):
        t = threading.Timer(max(0.0, delay_s), fn)
        t.daemon = True
        t.start()
        return t

    def cancel(self, handle):
        if handle is not None:
            handle.cancel()


class Transport(Protocol):
    """Synchronous BLE transport used by the manager. Callbacks may arrive on any thread."""
    def availability(self) -> tuple[bool, str | None]: ...
    def scan(self, include_unadvertised: bool, timeout_s: float) -> list[dict]: ...
    def connect(self, hardware_address: str, on_notify: Callable[[bytes], None],
                on_disconnect: Callable[[str], None], timeout_s: float) -> object: ...
    def disconnect(self, handle: object) -> None: ...


class HrsNotSupported(ConnectionError):
    """The device connected but its GATT table has no Heart Rate Service 0x180D / Heart Rate Measurement 0x2A37."""


class BleScanError(RuntimeError):
    """A classified Bluetooth failure. `reason_code` is safe to return to the UI (no addresses, no stack traces)."""

    def __init__(self, reason_code: str, message: str):
        super().__init__(message)
        self.reason_code = reason_code
        self.message = message


SUPPORTED_PROTOCOL = 'Bluetooth SIG Heart Rate Service (GATT 0x180D, Heart Rate Measurement 0x2A37)'

# reason_code → user-facing explanation (also used by the frontend; keep the codes stable)
REASONS = {
    'bluetooth_dependency_missing': 'The Bluetooth runtime (bleak/WinRT) is not available in this AETHER build.',
    'bluetooth_adapter_missing': 'No Bluetooth adapter was found on this computer.',
    'bluetooth_off': 'Bluetooth is turned off. Turn it on in Windows Settings → Bluetooth & devices.',
    'bluetooth_permission_denied': 'Windows denied access to the Bluetooth radio (Settings → Privacy & security → Radios).',
    'ble_scan_timeout': 'The Bluetooth scan did not finish in time.',
    'ble_os_error': 'The operating system reported a Bluetooth error.',
    'platform_unsupported': 'Physical Bluetooth is supported only in the Windows desktop build.',
}


def classify_ble_error(exc: BaseException) -> tuple[str, str]:
    """Map bleak / WinRT / OS exceptions to a stable reason code (message text is matched case-insensitively)."""
    if isinstance(exc, BleScanError):
        return exc.reason_code, exc.message
    text = f'{type(exc).__name__}: {exc}'.lower()
    if isinstance(exc, (ImportError, ModuleNotFoundError)):
        code = 'bluetooth_dependency_missing'
    elif isinstance(exc, (asyncio.TimeoutError, TimeoutError)) or 'timed out' in text or 'timeout' in text:
        code = 'ble_scan_timeout'
    elif 'turned off' in text or 'radio is off' in text or 'powered off' in text or 'poweredoff' in text:
        code = 'bluetooth_off'
    elif 'no bluetooth adapter' in text or 'adapter not found' in text or 'no adapter' in text or 'not available' in text:
        code = 'bluetooth_adapter_missing'
    elif 'access' in text and ('denied' in text or 'unauthori' in text) or 'permission' in text:
        code = 'bluetooth_permission_denied'
    else:
        code = 'ble_os_error'
    return code, REASONS[code] + f' ({type(exc).__name__})'


class BleakTransport:
    """bleak-based HRS transport on a dedicated asyncio loop thread (same approach as ble_sensor 1.4).

    DATA_CLASS is the provenance the server assigns to rows produced from this transport's notifications. It is a
    class attribute of the PRODUCTION radio transport only; nothing in a request can change it."""

    DATA_CLASS = 'real_wearable'
    KIND = 'physical_ble'
    RADIO_CACHE_S = 5.0

    def __init__(self):
        self._loop = None
        self._lock = threading.Lock()
        self._found: dict[str, object] = {}
        self._dep: tuple[bool, str | None, str | None] | None = None
        self._radio: tuple[float, str, str] | None = None

    # ------------------------------------------------------------ dependency / radio diagnostics
    def _dependency(self) -> tuple[bool, str | None, str | None]:
        """(available, bleak_version, error). Checked by a real import (works for PyInstaller frozen modules too)."""
        if self._dep is None:
            try:
                import bleak  # noqa: F401
                try:
                    from importlib.metadata import version
                    ver = version('bleak')
                except Exception:
                    ver = getattr(bleak, '__version__', None)
                if sys.platform == 'win32':
                    import bleak.backends.winrt.scanner  # noqa: F401   (pulls the WinRT projections)
                self._dep = (True, ver, None)
            except Exception as exc:                       # ImportError, OSError from a missing WinRT DLL, …
                return (False, None, f'{type(exc).__name__}: {exc}'[:200])   # not cached: re-checked on the next call
        return self._dep

    def _radio_state(self) -> tuple[str, str]:
        """('on'|'off'|'no_adapter'|'unknown', 'allowed'|'denied'|'unknown'). Windows only; best effort, cached."""
        now = time.monotonic()
        if self._radio and now - self._radio[0] < self.RADIO_CACHE_S:
            return self._radio[1], self._radio[2]
        state, access = 'unknown', 'unknown'
        if sys.platform == 'win32' and self._dependency()[0]:
            async def go():
                from winrt.windows.devices.radios import Radio, RadioAccessStatus, RadioKind, RadioState
                acc = 'unknown'
                try:
                    st = await Radio.request_access_async()
                    acc = 'allowed' if st == RadioAccessStatus.ALLOWED else (
                        'denied' if st in (RadioAccessStatus.DENIED_BY_USER, RadioAccessStatus.DENIED_BY_SYSTEM) else 'unknown')
                except Exception:
                    pass
                radios = await Radio.get_radios_async()
                bt = [r for r in radios if r.kind == RadioKind.BLUETOOTH]
                if not bt:
                    return 'no_adapter', acc
                return ('on' if any(r.state == RadioState.ON for r in bt) else 'off'), acc
            try:
                state, access = self._run(go(), 5)
            except Exception:
                state, access = 'unknown', 'unknown'
        self._radio = (now, state, access)
        return state, access

    def availability(self):
        ok, _ver, err = self._dependency()
        if not ok:
            hint = ('This Windows build was packaged without the Bluetooth runtime; rebuild with BUILD_WINDOWS.bat.'
                    if getattr(sys, 'frozen', False) else 'Install it with: pip install -r requirements-biosignals.txt')
            return False, f"{REASONS['bluetooth_dependency_missing']} {hint}"
        state, access = self._radio_state()
        if state == 'no_adapter':
            return False, REASONS['bluetooth_adapter_missing']
        if state == 'off':
            return False, REASONS['bluetooth_off']
        if access == 'denied':
            return False, REASONS['bluetooth_permission_denied']
        return True, None

    def reason_code(self) -> str | None:
        ok, _v, _e = self._dependency()
        if not ok:
            return 'bluetooth_dependency_missing'
        state, access = self._radio_state()
        return {'no_adapter': 'bluetooth_adapter_missing', 'off': 'bluetooth_off'}.get(state) or (
            'bluetooth_permission_denied' if access == 'denied' else None)

    def diagnostics(self) -> dict:
        ok, ver, err = self._dependency()
        state, access = self._radio_state() if ok else ('unknown', 'unknown')
        available, reason = self.availability()
        return {'platform': 'windows' if sys.platform == 'win32' else sys.platform,
                'frozen_build': bool(getattr(sys, 'frozen', False)),
                'ble_dependency_available': ok, 'bleak_version': ver,
                'ble_dependency_error': None if ok else (err or 'not importable'),
                'radio_available': None if state == 'unknown' else state == 'on',
                'radio_state': state, 'radio_access': access,
                'scan_available': available, 'reason_code': None if available else self.reason_code(),
                'reason': reason, 'supported_protocol': SUPPORTED_PROTOCOL, 'transport': self.KIND,
                'hardware_verified': False}

    def _run(self, coro, timeout):
        with self._lock:
            if self._loop is None:
                self._loop = asyncio.new_event_loop()
                threading.Thread(target=self._loop.run_forever, daemon=True, name='aether-ble-dm').start()
        return asyncio.run_coroutine_threadsafe(coro, self._loop).result(timeout=timeout + 5)

    def scan(self, include_unadvertised, timeout_s):
        try:
            from bleak import BleakScanner
        except Exception as exc:
            raise BleScanError('bluetooth_dependency_missing', REASONS['bluetooth_dependency_missing']) from exc

        async def go():
            return await BleakScanner.discover(timeout=timeout_s, return_adv=True)
        try:
            found = self._run(go(), timeout_s)
        except Exception as exc:
            code, message = classify_ble_error(exc)
            self._radio = None                      # re-probe the radio on the next call
            raise BleScanError(code, message) from exc
        out = []
        for address, (dev, adv) in found.items():
            uuids = [str(u).lower() for u in (getattr(adv, 'service_uuids', None) or [])]
            advertised = HRS_SERVICE_UUID in uuids
            name = str(getattr(dev, 'name', None) or getattr(adv, 'local_name', None) or '').strip()
            if advertised or (include_unadvertised and name):
                self._found[address] = dev
                rssi = getattr(adv, 'rssi', None)
                out.append({'hardware_address': address, 'name': name or 'Unnamed HRS monitor', 'advertised_hrs': advertised,
                            'rssi': rssi if isinstance(rssi, int) else None,
                            'compatibility': 'hrs_advertised' if advertised else 'unverified_gatt_check_on_connect'})
        out.sort(key=lambda d: (not d['advertised_hrs'], -(d['rssi'] if d['rssi'] is not None else -999)))
        return out[:80]

    def connect(self, hardware_address, on_notify, on_disconnect, timeout_s):
        try:
            from bleak import BleakClient
        except Exception as exc:
            raise BleScanError('bluetooth_dependency_missing', REASONS['bluetooth_dependency_missing']) from exc
        target = self._found.get(hardware_address, hardware_address)

        async def go():
            client = BleakClient(target, disconnected_callback=lambda _c: on_disconnect('link_lost'))
            await asyncio.wait_for(client.connect(), timeout=timeout_s)
            try:
                services = getattr(client, 'services', None)
                service = services.get_service(HRS_SERVICE_UUID) if services is not None and hasattr(services, 'get_service') else None
                char = services.get_characteristic(HRM_CHAR_UUID) if services is not None else None
                if char is None or (hasattr(services, 'get_service') and service is None):
                    raise HrsNotSupported('The device does not expose the standard Heart Rate Service 0x180D / '
                                          'Heart Rate Measurement 0x2A37')
                props = [str(p).lower() for p in (getattr(char, 'properties', None) or [])]
                if props and 'notify' not in props:
                    raise HrsNotSupported('Heart Rate Measurement 0x2A37 does not support notifications on this device')
                await client.start_notify(HRM_CHAR_UUID, lambda _h, data: on_notify(bytes(data)))
            except BaseException:
                try:
                    await client.disconnect()
                except Exception:
                    pass
                raise
            return client
        return self._run(go(), timeout_s)

    def disconnect(self, handle):
        async def go():
            try:
                await handle.stop_notify(HRM_CHAR_UUID)
            except Exception:
                pass
            await handle.disconnect()
        try:
            self._run(go(), 10)
        except Exception:
            pass
