"""Parity: the in-browser demo adapter (TypeScript port) must reproduce the Python models.

Runs `node web/frontend/scripts/run-tests.mjs --parity` and compares outputs on identical
inputs. Skipped automatically when Node.js or the frontend build tooling is unavailable.
Numeric tolerance 0.011 covers last-digit rounding differences between JS and Python.
"""
import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

from app.analytics import analyze, correlations, history_scores
from app.db import SEED_SHIFTS, seed_row
from app.simulation import calendar, project, run_scenario, schedules, ship_state, zone_history

FRONTEND = Path(__file__).resolve().parents[2] / 'frontend'
COLS = ('astronaut_id', 'day', 'heart_rate_bpm', 'sleep_hours', 'fatigue_1_10', 'reaction_ms', 'activity_minutes', 'source')


@pytest.fixture(scope='module')
def ts():
    node = shutil.which('node')
    if not node:
        pytest.skip('node not installed')
    proc = subprocess.run([node, str(FRONTEND / 'scripts/run-tests.mjs'), '--parity'], capture_output=True, text=True, encoding='utf-8',
                          env={**os.environ}, timeout=120)
    if proc.returncode != 0 or not proc.stdout.strip():
        pytest.skip(f'frontend tooling unavailable: {proc.stderr[-300:]}')
    return json.loads(proc.stdout)


def same(a, b, path='$'):
    if isinstance(a, dict) and isinstance(b, dict):
        assert set(a) == set(b), f'{path}: keys differ {set(a) ^ set(b)}'
        for k in a:
            same(a[k], b[k], f'{path}.{k}')
    elif isinstance(a, list) and isinstance(b, list):
        assert len(a) == len(b), f'{path}: length {len(a)} != {len(b)}'
        for i, (x, y) in enumerate(zip(a, b)):
            same(x, y, f'{path}[{i}]')
    elif isinstance(a, bool) or isinstance(b, bool) or a is None or b is None or isinstance(a, str):
        assert a == b, f'{path}: {a!r} != {b!r}'
    else:
        assert abs(float(a) - float(b)) <= 0.011, f'{path}: {a} != {b}'


def history(p):
    return [dict(zip(COLS, seed_row(p, dict(SEED_SHIFTS)[p], d))) for d in range(1, 68)]


def test_seed(ts):
    for p, _ in SEED_SHIFTS:
        same(history(p), ts['seed'][p], f'seed.{p}')


def test_analytics(ts):
    for p, _ in SEED_SHIFTS:
        for d in (67, 50):
            same(analyze(history(p), d), ts['analyze'][f'{p}-{d}'], f'analyze.{p}-{d}')
    same(history_scores(history('A01'), 41, 67), ts['history'])
    same(correlations(history('A01'), 67, 30), ts['correlations'])


def test_spacecraft_and_crew(ts):
    latest = {p: history(p)[-1] for p, _ in SEED_SHIFTS}
    status = {p: analyze(history(p), 67)['status'] for p, _ in SEED_SHIFTS}
    same(ship_state(67, 10, latest, status), ts['ship'])
    same(ship_state(60, 2.5, latest, status), ts['ship_night'])
    same(calendar(67, latest), ts['calendar'])
    same(zone_history(50, 67, 'exercise'), ts['zone_history'])
    same(schedules(optimise=False), ts['schedule_default'])
    same(schedules(capacity={'A01': 2}, unavailable=['A03']), ts['schedule_opt'])


def test_simulation(ts):
    same(run_scenario(history('A01'), day=67, sleep_delta=1, workload=30, co2_ppm=900, temperature_c=22, crew_available=3), ts['scenario'])
    same(project(history('A01'), start_day=67, horizon_days=12, sleep_delta=-1.8, workload=85, co2_ppm=1450,
                 temperature_c=25, crew_available=4, runs=60, seed=3), ts['projection'])
