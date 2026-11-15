"""SensorAdapter — extension point for wearable sources (AETHER 1.5, Backend №3).

Only the standard Bluetooth Heart Rate Service is implemented. Platform integrations (Apple HealthKit, Android Health
Connect) and Garmin are NOT universal BLE services: they need native code (Frontend / cross-platform developer), platform
permissions and, for Garmin, partner access. Their descriptors below state requirements and an honest status; their
data methods raise DeviceUnavailable — they are not presented as working connectors.

Status vocabulary (rules 1.5 §6): implemented · automated_tested · hardware_verified · integration_pending ·
experimental · unsupported.
"""
from __future__ import annotations

from abc import ABC, abstractmethod

from ..science_errors import DeviceUnavailable


class SensorAdapter(ABC):
    id: str
    name: str
    kind: str                       # 'ble' | 'platform_api' | 'cloud_api'
    status: str
    signals: tuple[str, ...]
    verified_capabilities: tuple[str, ...] = ()
    requirements: tuple[str, ...] = ()
    permissions: tuple[str, ...] = ()
    limitations: str = ''

    @abstractmethod
    def availability(self) -> tuple[bool, str | None]: ...

    def supported_signals(self) -> list[str]:
        return list(self.signals)

    def request_permissions(self) -> dict:
        return {'required': list(self.permissions), 'granted': None,
                'note': 'Permissions are granted in the operating system / companion app, not by the backend.'}

    @abstractmethod
    def start(self, *args, **kwargs): ...

    @abstractmethod
    def stop(self, *args, **kwargs): ...

    def normalise(self, raw) -> list[dict]:
        raise DeviceUnavailable(f'{self.name}: normalisation not implemented')

    def quality_report(self) -> dict:
        return {'status': self.status, 'verified_capabilities': list(self.verified_capabilities)}

    def describe(self) -> dict:
        ok, why = self.availability()
        return {'id': self.id, 'name': self.name, 'kind': self.kind, 'status': self.status, 'signals': list(self.signals),
                'verified_capabilities': list(self.verified_capabilities), 'hardware_verified': self.status == 'hardware_verified',
                'available_here': ok, 'unavailable_reason': why, 'requirements': list(self.requirements),
                'permissions': list(self.permissions), 'limitations': self.limitations}


class BleHrsAdapter(SensorAdapter):
    """Wraps the Device Manager (manager.py) — the only adapter with real data flow."""
    id, name, kind, status = 'ble_hrs', 'Bluetooth SIG Heart Rate Service', 'ble', 'automated_tested'
    signals = ('heart_rate', 'rr_interval')
    verified_capabilities = ('hrs_decode_uint8_uint16_rr_contact_energy (unit tests)',
                             'device_manager_lifecycle_reconnect_recovery (mock transport)')
    requirements = ('Bluetooth LE radio', 'optional Python package bleak (WinRT backend on Windows 10/11)',
                    'device exposing GATT service 0x180D / characteristic 0x2A37')
    permissions = ('Windows: Bluetooth enabled in Settings; no pairing needed for HRS notifications on most straps',)
    limitations = ('No SpO2, temperature or sleep over HRS. RR optional per device. Timestamps = host receipt. '
                   'Not hardware-verified: no physical device was tested by the AETHER team.')

    def __init__(self, manager=None, transport=None):
        self.manager, self.transport = manager, transport

    def availability(self):
        if self.transport is None:
            return False, 'No BLE transport configured'
        return self.transport.availability()

    def start(self, ctx, device_id, body):
        return self.manager.connect(ctx, device_id, body)

    def stop(self, ctx, device_id):
        return self.manager.disconnect(ctx, device_id)


class _NotIntegrated(SensorAdapter):
    def availability(self):
        return False, f'{self.name} is not integrated in AETHER 1.5 ({self.status})'

    def start(self, *a, **k):
        raise DeviceUnavailable(f'{self.name} is not integrated ({self.status}); see WEARABLE_COMPATIBILITY_MATRIX.md')

    stop = start


class AppleHealthKitAdapter(_NotIntegrated):
    id, name, kind, status = 'apple_healthkit', 'Apple HealthKit (Apple Watch)', 'platform_api', 'integration_pending'
    signals = ()
    requirements = ('native iOS app (Capacitor plugin) with the HealthKit entitlement', 'user authorisation per data type',
                    'iPhone paired with the watch; data arrive via HealthKit queries, not BLE')
    permissions = ('HealthKit read: heart rate, heart rate variability SDNN', 'Info.plist NSHealthShareUsageDescription')
    limitations = 'Apple Watch does not expose the standard BLE HRS to third-party desktop apps.'


class HealthConnectAdapter(_NotIntegrated):
    id, name, kind, status = 'android_health_connect', 'Android Health Connect (e.g. Galaxy Watch)', 'platform_api', 'integration_pending'
    signals = ()
    requirements = ('native Android app with the Health Connect SDK', 'per-record-type user permission')
    permissions = ('android.permission.health.READ_HEART_RATE',)
    limitations = 'Samples arrive with the watch vendor\'s processing; sampling rate and RR availability vary.'


class GarminAdapter(_NotIntegrated):
    id, name, kind, status = 'garmin', 'Garmin (Health API / Connect IQ)', 'cloud_api', 'unsupported'
    signals = ()
    requirements = ('Garmin Health API partner access or a Connect IQ app', 'alternatively: watch "Broadcast heart rate" '
                    'mode, which exposes standard HRS and is then handled by ble_hrs (not verified)')
    limitations = 'Full Garmin metrics require partner agreements outside the project.'


def registry(ble_adapter: SensorAdapter | None = None) -> list[dict]:
    return [a.describe() for a in (ble_adapter or BleHrsAdapter(), AppleHealthKitAdapter(), HealthConnectAdapter(), GarminAdapter())]
