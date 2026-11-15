import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { test } from 'node:test';
import { findConflicts } from '../src/features/co-orbit/CoOrbitPage';
import { autoThemeAt } from '../src/state/AppState';
import { createDemoApi } from '../src/mocks/demoApi';

declare const __AETHER_ROOT__: string;
const css = readFileSync(join(__AETHER_ROOT__, 'src/styles/index.css'), 'utf8');

function tokens(block: string): Record<string, string> {
  const out: Record<string, string> = {};
  for (const m of block.matchAll(/--color-([a-z0-9-]+):\s*(#[0-9a-fA-F]{6})/g)) out[m[1]] = m[2];
  return out;
}
const dark = tokens(css.slice(css.indexOf('@theme static'), css.indexOf('@layer base')));
const light = { ...dark, ...tokens(css.slice(css.indexOf('.theme-light {'), css.indexOf('.theme-light .theme-recovery'))) };

const lum = (h: string) => {
  const c = [1, 3, 5].map((i) => parseInt(h.slice(i, i + 2), 16) / 255).map((v) => (v <= 0.03928 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4));
  return 0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2];
};
const ratio = (a: string, b: string) => (Math.max(lum(a), lum(b)) + 0.05) / (Math.min(lum(a), lum(b)) + 0.05);

for (const [name, t] of [['dark', dark], ['light', light]] as const) {
  test(`design tokens meet WCAG contrast (${name} mode)`, () => {
    const surfaces = ['canvas', 'surface', 'raised'];
    // Text tokens: 4.5:1 (SC 1.4.3) on every surface.
    for (const text of ['ink', 'ink-2', 'ink-3', 'teal-300', 'good', 'attention', 'high', 'analysis', 'missing', 'sage']) {
      for (const s of surfaces) assert.ok(ratio(t[text], t[s]) >= 4.5, `${name}: ${text} on ${s} = ${ratio(t[text], t[s]).toFixed(2)}`);
    }
    // Control boundaries and focus ring: 3:1 (SC 1.4.11).
    for (const s of surfaces) {
      assert.ok(ratio(t['line-strong'], t[s]) >= 3, `${name}: line-strong on ${s} = ${ratio(t['line-strong'], t[s]).toFixed(2)}`);
      assert.ok(ratio(t['teal-300'], t[s]) >= 3, `${name}: focus on ${s}`);
    }
    // Chart series are graphical objects: 3:1 against the card surface.
    for (const k of ['series-1', 'series-2', 'series-3', 'series-4', 'series-5']) assert.ok(ratio(t[k], t.surface) >= 3, `${name}: ${k} = ${ratio(t[k], t.surface).toFixed(2)}`);
    // Primary button: canvas-coloured text on the accent fill.
    assert.ok(ratio(t.canvas, t['teal-300']) >= 4.5, `${name}: primary button text`);
  });
}

test('auto display mode follows mission time', () => {
  assert.equal(autoThemeAt(10), 'light');
  assert.equal(autoThemeAt(6.5), 'dark');
  assert.equal(autoThemeAt(20), 'dark');
});

test('manual-plan conflict detection', () => {
  const crew = [
    { id: 'A01', name: 'Alex', skills: ['command', 'science'] as const, capacity: 6, home_zone: 'command' as const },
    { id: 'A03', name: 'Sam', skills: ['medical'] as const, capacity: 6, home_zone: 'medical' as const },
  ].map((c) => ({ ...c, skills: [...c.skills] }));
  const t = (id: string, skill: 'command' | 'medical' | 'science', hours: number, who: string | null) => ({ id, title: id, skill, hours, priority: 1 as const, astronaut_id: who });
  assert.deepEqual(findConflicts([t('T1', 'command', 2, 'A01'), t('T2', 'medical', 2, 'A03')], crew, { A01: 6, A03: 6 }, []), []);
  const c = findConflicts([t('T1', 'medical', 5, 'A01'), t('T2', 'science', 3, 'A01'), t('T3', 'medical', 1, null), t('T4', 'medical', 1, 'A03')], crew, { A01: 6, A03: 0 }, ['A01']);
  assert.ok(c.some((x) => x.includes('lacks the medical skill')));
  assert.ok(c.some((x) => x.includes('over capacity')));
  assert.ok(c.some((x) => x.includes('no owner')));
  assert.ok(c.some((x) => x.includes('unavailable')));
  assert.ok(c.some((x) => x.includes('reduced load')));
});

test('demo mock serves pending contracts with a synthetic label', async () => {
  const api = createDemoApi({ latencyMs: 0, persist: false });
  const a = await api.environmentAssociation(67, 'habitat');
  assert.equal(a.source, 'simulated');
  assert.equal(a.rows.length, 4);
  const f = await api.biofeedback('A01');
  assert.equal(f.source, 'simulated');
  assert.ok(f.coherence_0_1! >= 0 && f.coherence_0_1! <= 1);
});
