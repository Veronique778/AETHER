/** Prints demo-adapter outputs for fixed inputs as JSON; compared against Python by web/backend/tests/test_parity.py. */
import { analyze, correlations, historyScores } from '../src/mocks/phantomMock';
import { calendar, project, runScenario, schedules, seedRow, SEED_SHIFTS, shipState, zoneHistory } from '../src/mocks/missionSystemsMock';

const hist = Object.fromEntries(SEED_SHIFTS.map(([p, s]) => [p, Array.from({ length: 67 }, (_, i) => seedRow(p, s, i + 1))]));
const latest = Object.fromEntries(SEED_SHIFTS.map(([p]) => [p, hist[p][66]]));
const status = Object.fromEntries(SEED_SHIFTS.map(([p]) => [p, analyze(hist[p], 67).status]));
const out = {
  seed: hist,
  analyze: Object.fromEntries(SEED_SHIFTS.flatMap(([p]) => [[`${p}-67`, analyze(hist[p], 67)], [`${p}-50`, analyze(hist[p], 50)]])),
  history: historyScores(hist.A01, 41, 67),
  correlations: correlations(hist.A01, 67, 30),
  ship: shipState(67, 10, latest, status),
  ship_night: shipState(60, 2.5, latest, status),
  calendar: calendar(67, latest),
  zone_history: zoneHistory(50, 67, 'exercise'),
  schedule_default: schedules({ optimise: false }),
  schedule_opt: schedules({ capacity: { A01: 2 }, unavailable: ['A03'] }),
  scenario: runScenario(hist.A01, { day: 67, sleep_delta: 1, workload: 30, co2_ppm: 900, temperature_c: 22, crew_available: 3 }),
  projection: project(hist.A01, { start_day: 67, horizon_days: 12, sleep_delta: -1.8, workload: 85, co2_ppm: 1450, temperature_c: 25, crew_available: 4, runs: 60, seed: 3 }),
};
process.stdout.write(JSON.stringify(out));
