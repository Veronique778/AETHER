"""Shared builders for the AETHER 1.5 Backend №3 tests (renamed from helpers_15.py in 03A: Backend №2 owns that name).
All series are SYNTHETIC test fixtures. P1…P4 are personal astronaut UUIDs (canonical lowercase, version 4) used for
real-data paths; 'A01'–'A04' remain legacy demo ids for synthetic data only."""
import math
import random
from datetime import datetime, timedelta, timezone

from app.signals import iso_utc

T0 = datetime(2026, 11, 20, 8, 0, tzinfo=timezone.utc)
P1 = '11111111-1111-4111-8111-111111111111'
P2 = '22222222-2222-4222-8222-222222222222'
P3 = '33333333-3333-4333-8333-333333333333'
P4 = '44444444-4444-4444-8444-444444444444'


def hr_series(minutes=90, every_s=2, base=62.0, step_at_min=60, step_to=74.0, noise=1.2, seed=7, gaps=(), rr=True,
              contact=True, astronaut=P1, session_id=None, device_id=None, data_class='real_wearable', start=T0,
              quality='screened', constant=False):
    """HR (+ RR) rows ready for storage.save_measurements. gaps = [(start_min, end_min)] produce NO rows."""
    rng = random.Random(seed)
    out = []
    for s in range(0, minutes * 60, every_s):
        m = s / 60
        if any(a <= m < b for a, b in gaps):
            continue
        level = base if (step_at_min is None or m < step_at_min) else step_to
        hr = level if constant else round(level + 1.5 * math.sin(s / 300) + rng.gauss(0, noise), 1)
        t = iso_utc(start + timedelta(seconds=s))
        prov = {'profile': 'HRS', 'contact': contact, 'clock': 'host_receipt'}
        common = dict(astronaut_id=astronaut, session_id=session_id, device_id=device_id, data_class=data_class,
                      source='test fixture HRS stream', recorded_at=t, provenance=prov)
        out.append({**common, 'signal': 'heart_rate', 'value': hr, 'unit': 'bpm', 'quality': quality,
                    'client_measurement_id': f'{astronaut}-{data_class}-{int(start.timestamp())}-{s}-hr'})
        if rr:
            out.append({**common, 'signal': 'rr_interval', 'value': round(60000 / hr, 1), 'unit': 'ms', 'quality': quality,
                        'client_measurement_id': f'{astronaut}-{data_class}-{int(start.timestamp())}-{s}-rr'})
    return out


def store(storage, ctx, rows):
    for i in range(0, len(rows), 500):
        storage.save_measurements(ctx, rows[i:i + 500])


def span(minutes, start=T0):
    return iso_utc(start), iso_utc(start + timedelta(minutes=minutes))
