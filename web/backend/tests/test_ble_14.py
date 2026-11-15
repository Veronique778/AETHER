"""AETHER 1.4 BLE acquisition (mock harness), DEMO MODE recording and connector registry."""
import sys
from pathlib import Path

import pytest

from app import biosignals as bio, connectors, db
from app.ble_sensor import decode

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'validation'))
import mock_hrs_harness as harness  # noqa: E402


@pytest.fixture(autouse=True)
def local_db(tmp_path, monkeypatch):
    monkeypatch.setattr(db, 'DB_PATH', tmp_path / 'ble.sqlite3')
    db.init_db(); bio.init()


def test_mock_harness_all_checks_pass():
    result = harness.run()
    failed = [c for c in result['checks'] if not c['pass']]
    assert not failed, failed
    assert result['physical_hardware_verified'] is False and result['passed'] >= 15


@pytest.mark.parametrize('hr,rr,contact,uint16', [(64, [], True, False), (182, [500.0, 512.0], None, False),
                                                  (301, [], False, True), (45, [1333.0], True, True)])
def test_encoder_decoder_round_trip(hr, rr, contact, uint16):
    p = decode(harness.hrs_packet(hr, rr, contact, uint16))
    assert p['heart_rate'] == hr and p['contact'] == (contact if contact is not None else None)
    assert [round(x) for x in p['rr_ms']] == [round(x) for x in rr]


def test_demo_recording_requires_explicit_confirmation():
    with pytest.raises(ValueError, match='explicit confirmation'):
        bio.demo_recording(False)
    with pytest.raises(ValueError):
        bio.demo_recording('yes')
    assert bio.sessions() == []


def test_demo_recording_is_labelled_deterministic_and_analysable():
    a = bio.demo_recording(True)
    b = bio.demo_recording(True)
    assert a['source_type'] == 'simulated_demo' and a['participant'].startswith('DEMO')
    assert a['metadata']['data_class'] == 'synthetic'
    hr = {c['signal']: c for c in a['channels']}['heart_rate']
    assert hr['missing'] == 90  # 3-minute dropout at 0.5 Hz stored as missing rows
    assert hr == {c['signal']: c for c in b['channels']}['heart_rate']  # same seed -> same data
    r = bio.analyze(a['id'])
    assert r['simulated'] is True and r['data_class'] == 'synthetic'
    assert r['baseline_hr_bpm'] == pytest.approx(62, abs=1.0)
    assert r['outcome'] == 'flag'
    dropout = [w for w in r['windows'] if w['valid'] < w['samples']]
    assert dropout and all(w['outcome'] == 'insufficient_data' for w in dropout)
    assert any('SIMULATED' in x for x in r['limitations'])


def test_connector_registry_is_honest():
    reg = {c['id']: c for c in connectors.registry()['connectors']}
    assert reg['ble_hrs']['status'] == 'automated_tested' and reg['ble_hrs']['physically_verified'] is False
    for vendor in ('apple_watch', 'samsung_galaxy_watch', 'garmin_cloud'):
        assert reg[vendor]['status'] == 'unsupported' and reg[vendor]['implemented'] is False
        assert reg[vendor]['access']
    assert not any(c['physically_verified'] for c in reg.values())
    assert reg['demo_recording']['data_class'] == 'synthetic'
