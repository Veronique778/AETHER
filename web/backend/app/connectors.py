"""Data-source connector registry (AETHER 1.4).

Each connector states, separately, whether it is implemented, covered by
automated tests, and verified on physical hardware. 'Unsupported' entries
document the real access route so nobody assumes a device works over BLE.
New providers register by adding a ``Connector`` here and an acquisition
module that writes through ``app.biosignals`` (which keeps provenance).
"""
from __future__ import annotations

import importlib.util
from dataclasses import asdict, dataclass, field


@dataclass(frozen=True)
class Connector:
    id: str
    name: str
    kind: str                 # live_sensor | research_import | nasa_research | demo
    data_class: str           # real_wearable | nasa_research | terrestrial_research | synthetic
    implemented: bool
    automated_tests: bool
    physically_verified: bool
    signals: tuple[str, ...]
    access: str
    limitations: str
    devices: tuple[str, ...] = field(default_factory=tuple)

    @property
    def status(self) -> str:
        if not self.implemented:
            return 'unsupported'
        if self.physically_verified:
            return 'physically_verified'
        return 'automated_tested' if self.automated_tests else 'implemented'


CONNECTORS = (
    Connector('ble_hrs', 'Bluetooth Heart Rate Service (0x180D / 0x2A37)', 'live_sensor', 'real_wearable',
              True, True, False, ('heart_rate', 'rr_interval'),
              'Direct BLE via bleak (WinRT backend on Windows 10/11). Requires Bluetooth LE radio and the optional bleak package.',
              'Only devices exposing the standard GATT Heart Rate Service. No SpO2, temperature or sleep over HRS. '
              'Tested with a deterministic mock transport; no physical device has been verified by the AETHER team.',
              ('Chest straps that implement standard HRS (e.g. Polar H10, Wahoo TICKR, Garmin HRM-Dual — per vendor documentation)',
               'Watches with an HR broadcast mode that exposes HRS (e.g. some Garmin models, “Broadcast Heart Rate”)')),
    Connector('mmash', 'MMASH 1.0.0 research recordings (PhysioNet)', 'research_import', 'terrestrial_research',
              True, True, False, ('rr_interval', 'heart_rate', 'activity', 'sleep'),
              'Local import of the published MMASH ZIP/folder (Rossi et al. 2020, doi:10.13026/cerq-fc86).',
              'Terrestrial healthy-adult recordings; relative clock only; not astronaut data.'),
    Connector('nasa_osdr', 'NASA Open Science Data Repository', 'nasa_research', 'nasa_research',
              True, True, False, ('study-specific numeric columns',),
              'HTTPS to osdr.nasa.gov (search, file catalog, file download). Offline: user-supplied CSV labelled unverified.',
              'CSV/TSV only. Organism and data layer from OSDR metadata. Mostly non-human or molecular studies; '
              'only human in vivo clinical data is offered to PHANTOM as reference context.'),
    Connector('demo_recording', 'DEMO MODE deterministic simulated recording', 'demo', 'synthetic',
              True, True, False, ('heart_rate', 'rr_interval'),
              'Generated locally only after explicit confirmation.',
              'Synthetic. Labelled SIMULATED everywhere; never mixed with real sessions.'),
    Connector('garmin_cloud', 'Garmin (full health metrics)', 'live_sensor', 'real_wearable',
              False, False, False, ('heart_rate', 'hrv', 'sleep', 'spo2', 'stress'),
              'Garmin Health API / Connect IQ require a Garmin developer agreement and OAuth; not implemented. '
              'Some Garmin devices can broadcast HR over standard BLE HRS — those work through ble_hrs.',
              'Only broadcast heart rate is reachable without a partnership.'),
    Connector('samsung_galaxy_watch', 'Samsung Galaxy Watch', 'live_sensor', 'real_wearable',
              False, False, False, ('heart_rate',),
              'Samsung Health Sensor/Data SDK or Android Health Connect on a paired phone; not implemented. '
              'Wear OS watches do not expose standard HRS by default; a third-party broadcast app would be required.',
              'No Windows-native route.'),
    Connector('apple_watch', 'Apple Watch', 'live_sensor', 'real_wearable',
              False, False, False, ('heart_rate',),
              'Apple HealthKit on a paired iPhone (iOS app + user authorisation); not implemented. '
              'Apple Watch does not broadcast standard BLE HRS natively.',
              'No Windows-native route; would need an iOS companion app exporting data.'),
)


def registry() -> dict:
    bleak = importlib.util.find_spec('bleak') is not None
    items = []
    for c in CONNECTORS:
        item = {**asdict(c), 'status': c.status}
        if c.id == 'ble_hrs':
            item['runtime_ready'] = bleak
            item['runtime_note'] = 'bleak installed' if bleak else 'bleak not installed — run ENABLE_BLE.bat (source) or use the portable build'
        items.append(item)
    return {'connectors': items,
            'legend': {'unsupported': 'Not implemented; access route documented',
                       'implemented': 'Code present, no automated test',
                       'automated_tested': 'Covered by automated tests (mock/fixture); physical hardware not verified',
                       'physically_verified': 'Verified with real hardware by the team'}}
