"""AETHER 1.5 — accelerated endurance / failure scenarios for the BLE Device Manager (Backend №3).

    cd web/backend && python -I tests/ble_endurance_03.py [--full]      # --full adds the 24-hour run

ACCELERATED SIMULATION: time is driven by a manual clock; a "24-hour" run feeds 86 400 mock notifications as fast as the
CPU allows. It measures the software path (buffering, persistence, counters, memory), NOT radio behaviour, battery or
real-time timing. Every value is labelled `simulated`. Storage = tests/fakes/storage_fake.FakeStorage (in memory).
"""
from __future__ import annotations

import json
import random
import sys
import time
import tracemalloc
from pathlib import Path

sys.path[:0] = [str(Path(__file__).resolve().parent), str(Path(__file__).resolve().parents[1])]

from app.devices import manager as dm  # noqa: E402
from app.signals import parse_utc  # noqa: E402
from fakes.ble_mock import ManualClock, ManualScheduler, MockTransport  # noqa: E402
from fakes.storage_fake import FakeContext, FakeStorage  # noqa: E402
from helpers_be3_signals_15 import P1, P2, P3, P4  # noqa: E402

PIDS = [P1, P2, P3, P4]

CTXS = [FakeContext(user_id=f'{i}' * 32, astronaut_ids=frozenset({PIDS[i - 1]})) for i in range(1, 5)]


def run(hours=1.0, devices=1, every_s=1.0, rr_per_beat=1, outage=None, flaky=0.0, no_contact=0.0, silence=None,
        max_pending=None, seed=1):
    """outage=(start_h, end_h) storage down; flaky=share of failing writes; silence=(start_h, minutes) sensor silent."""
    rng = random.Random(seed)
    from app.devices import hw_lock
    hw_lock._reset_for_tests()
    st, tr, clock = FakeStorage(), MockTransport(), ManualClock()
    sched = ManualScheduler(clock)
    m = dm.DeviceManager(st, tr, clock=clock, scheduler=sched)
    if max_pending:
        dm.MAX_PENDING_ROWS, saved_cap = max_pending, dm.MAX_PENDING_ROWS
    real_save = st.save_measurements
    delays, state = [], {'down': False}

    def save(ctx, items):
        if state['down'] or (flaky and rng.random() < flaky):
            raise ConnectionError('storage down (simulated)')
        out = real_save(ctx, items)
        now = clock.now()
        oldest = min(parse_utc(r['provenance']['received_host_utc']) for r in items if r['provenance'].get('received_host_utc'))
        delays.append((now - oldest).total_seconds())
        return out
    st.save_measurements = save
    slots = []
    for i in range(devices):
        addr = f'AA:00:00:00:00:{i:02d}'
        tr.add(addr)
        dev = m.register(CTXS[i], {'hardware_address': addr, 'name': f'mock {i}', 'astronaut_id': PIDS[i]})
        out = m.connect(CTXS[i], dev['device_id'], {'astronaut_id': PIDS[i]})
        slots.append((dev['device_id'], out['session_id'], tr.link(addr), CTXS[i]))
    n = int(hours * 3600 / every_s)
    sent = sent_rows = 0
    peak_pending = 0
    tracemalloc.start()
    t0 = time.perf_counter()
    for k in range(n):
        h = k * every_s / 3600
        if outage:
            state['down'] = outage[0] <= h < outage[1]
        sched.advance(every_s)
        silent = silence and silence[0] <= h < silence[0] + silence[1] / 60
        if silent:
            continue
        for did, sid, link, ctx in slots:
            contact = not (no_contact and rng.random() < no_contact)
            rr = tuple(int(1024 * 60 / 62) for _ in range(rr_per_beat))
            link.hr(62 + rng.randint(-2, 2), rr, contact)
            sent += 1; sent_rows += 1 + rr_per_beat
        peak_pending = max(peak_pending, max(len(m._slots[d].pending) for d, *_ in slots))
    state['down'] = False
    for did, sid, link, ctx in slots:
        m.disconnect(ctx, did)
    dur = time.perf_counter() - t0
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    if max_pending:
        dm.MAX_PENDING_ROWS = saved_cap
    rows = list(st.db['measurements'].values())
    per = {}
    for did, sid, link, ctx in slots:
        mine = [r for r in rows if r['session_id'] == sid]
        c = m._slots[did].counters
        per[sid[:8]] = {'astronaut': mine[0]['astronaut_id'] if mine else None,
                        'foreign_rows': sum(r['astronaut_id'] != PIDS[slots.index((did, sid, link, ctx))] for r in mine),
                        'stored_rows': len(mine), 'value_rows': sum(r['value'] is not None for r in mine),
                        'missing_markers': sum(r['value'] is None for r in mine), 'dropped_rows': c['dropped_rows'],
                        'duplicate_rows_reported': c['duplicate_rows'], 'storage_failures': c['storage_failures'],
                        'no_contact_rows': sum(r['quality'] == 'no_contact' for r in mine),
                        'session_status': st.db['sessions'][sid]['status']}
    ids = [r['client_measurement_id'] for r in rows]
    return {'scenario': {'hours_simulated': hours, 'devices': devices, 'every_s': every_s, 'rr_per_beat': rr_per_beat,
                         'outage_h': outage, 'flaky_write_share': flaky, 'no_contact_share': no_contact, 'silence': silence,
                         'max_pending_rows': max_pending or dm.MAX_PENDING_ROWS},
            'accepted_notifications': sent, 'accepted_value_rows': sent_rows, 'stored_rows_total': len(rows),
            'duplicate_ids_in_storage': len(ids) - len(set(ids)),
            'value_rows_stored': sum(r['value'] is not None for r in rows),
            'lost_value_rows': sent_rows - sum(r['value'] is not None for r in rows),
            'peak_pending_rows': peak_pending, 'max_commit_delay_s_simulated': round(max(delays), 3) if delays else None,
            'median_commit_delay_s_simulated': round(sorted(delays)[len(delays) // 2], 3) if delays else None,
            'wall_time_s': round(dur, 2), 'peak_traced_memory_mb': round(peak / 2**20, 1), 'per_session': per,
            'timing': 'simulated (manual clock), not real time'}


SCENARIOS = {
    '1h_nominal': dict(hours=1),
    '8h_nominal': dict(hours=8),
    '3_parallel_sessions_1h': dict(hours=1, devices=3, rr_per_beat=2),
    'storage_outage_10min': dict(hours=1, outage=(0.25, 0.25 + 10 / 60)),
    'storage_flaky_30pct': dict(hours=1, flaky=0.3),
    'queue_overflow_cap_2000': dict(hours=1, outage=(0.2, 0.7), max_pending=2000),
    'partial_loss_10pct_no_contact_and_5min_silence': dict(hours=1, no_contact=0.1, silence=(0.5, 5)),
}

if __name__ == '__main__':
    todo = dict(SCENARIOS)
    if '--full' in sys.argv:
        todo['24h_nominal'] = dict(hours=24)
    print(json.dumps({k: run(**v) for k, v in todo.items()}, indent=1))
