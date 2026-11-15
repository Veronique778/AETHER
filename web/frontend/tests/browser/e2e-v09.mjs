// AETHER 0.9 E2E (CO-ORBIT block updated to API 1.0 semantics): PHANTOM 2.0, PHANTOM → CO-ORBIT with approval, plan profiles, scientific core, radiation, SYMBIOSIS analytics.
// Usage: node e2e-v09.mjs <url> [screenshot-dir]
import { mkdirSync } from 'node:fs';
import { createRequire } from 'node:module';
const require = createRequire(process.env.AETHER_PLAYWRIGHT_FROM ?? '/home/claude/.npm-global/lib/node_modules/noop.js');
const { chromium } = require('playwright');
const base = process.argv[2] ?? 'http://127.0.0.1:8000/';
const shots = process.argv[3] ?? null;
const only = (process.env.E2E_ONLY ?? '').split(',').filter(Boolean);
if (shots) mkdirSync(shots, { recursive: true });
const browser = await chromium.launch({ args: ['--use-gl=angle', '--use-angle=swiftshader', '--enable-unsafe-swiftshader'] });
const page = await (await browser.newContext({ viewport: { width: 1600, height: 1000 } })).newPage();
const errors = []; const results = [];
page.on('console', (m) => { if (m.type() === 'error' && !/Failed to load resource/.test(m.text())) errors.push(m.text()); });
page.on('pageerror', (e) => errors.push('pageerror: ' + e.message));
const check = (name, ok, extra = '') => results.push(`${ok ? 'PASS' : 'FAIL'}  ${name}${extra ? '  · ' + extra : ''}`);
const safe = async (name, fn) => { if (only.length && !only.includes(name)) return; try { await fn(); } catch (e) { check(name, false, String(e.message).split('\n')[0].slice(0, 180)); } };
const go = async (r) => { await page.evaluate((r) => { location.hash = '#' + r; }, r); await page.waitForTimeout(1000); };
const shot = async (n) => { if (shots) await page.screenshot({ path: `${shots}/${n}.png`, fullPage: false }); };
const api = (path, init) => page.evaluate(async ([p, i]) => { const r = await fetch(p, i); return { status: r.status, body: await r.json() }; }, [path, init]);

await page.goto(base + '?mode=live'); await page.waitForTimeout(1500);

await safe('PHANTOM2', async () => {
  await go('/phantom');
  const card = page.getByText('Beyond single-signal z-scores');
  await card.waitFor({ timeout: 15000 });
  check('PHANTOM 2.0 card renders with detector decisions', await page.getByRole('list', { name: /Detector decisions for day/ }).isVisible());
  check('PHANTOM 2.0: CUSUM change-start estimate shown for A01', await page.getByText(/CUSUM estimates a sustained change starting on/).isVisible());
  check('PHANTOM 2.0: bootstrap uncertainty shown', await page.getByText(/Bootstrap \(\d+×\): flag probability/).isVisible());
  check('PHANTOM 2.0: attribution listed', await page.getByText('Attribution – share of the distance').isVisible());
  await card.scrollIntoViewIfNeeded(); await shot('phantom2-card');
});

await safe('COORBIT', async () => {
  await go('/mission-lab?tab=engine');
  await page.getByRole('button', { name: /Sleep loss/ }).click();
  await page.getByLabel('Crew plan (CO-ORBIT)').selectOption('high_workload');
  await page.getByRole('button', { name: 'Run engine' }).click();
  await page.getByText('PHANTOM 1.0 vs 2.0 – physiology only, hidden synthetic labels').waitFor({ timeout: 90000 });
  check('LAB: detector comparison table on engine run', true);
  check('LAB: comparator note replaces “PHANTOM ahead”', (await page.getByText('PHANTOM ahead on this run').count()) === 0);
  await page.getByRole('button', { name: 'Apply to mission' }).first().click(); await page.waitForTimeout(500);
  await go('/co-orbit');
  const panel = page.getByRole('region', { name: 'PHANTOM-derived planning constraints' });
  await panel.getByRole('list', { name: 'Recommendations' }).waitFor({ timeout: 30000 });
  const boxes = panel.getByRole('checkbox');
  const n = await boxes.count();
  check('CO-ORBIT: PHANTOM recommendations listed', n > 0, `${n}`);
  const applyBtn = panel.getByRole('button', { name: /Approve \d+ → compute proposal/ });
  await boxes.first().check();
  check('CO-ORBIT: cannot apply without a named approver', await applyBtn.isDisabled());
  await panel.getByLabel('Approved by').fill('Dr. Demo (flight surgeon)');
  for (let i = 1; i < n; i++) await boxes.nth(i).check();
  await applyBtn.click();
  const dec = panel.getByTestId('coorbit-decision');
  await dec.waitFor({ timeout: 90000 });
  const status = await dec.getAttribute('data-decision-status');
  // API 1.0: either a valid proposal (current vs proposed) or an explained rejection with the current schedule kept.
  if (status === 'proposal_ready') check('CO-ORBIT: proposal with current/proposed schedules', await panel.getByRole('list', { name: 'Proposed schedule' }).isVisible() && await panel.getByRole('list', { name: 'Current schedule' }).isVisible());
  else check('CO-ORBIT: rejection keeps the schedule in force', await panel.getByRole('list', { name: 'Schedule in force – unchanged' }).isVisible() && (await panel.getByRole('list', { name: 'Proposed schedule' }).count()) === 0, status);
  check('CO-ORBIT: decision is never "applied"', await dec.getByText('not applied automatically').isVisible());
  await panel.scrollIntoViewIfNeeded(); await shot('coorbit-phantom');
  const rp = page.getByRole('region', { name: 'Re-plan after a change' });
  await rp.getByRole('button', { name: 'Re-plan' }).click();
  const rr = rp.getByTestId('replan-result');
  await rr.waitFor({ timeout: 90000 });
  const rs = await rr.getAttribute('data-decision-status');
  check('CO-ORBIT: replan result shown with explicit status', ['proposal_ready', 'rejected_no_feasible_schedule'].includes(rs ?? ''), rs);
  await rp.scrollIntoViewIfNeeded(); await shot('coorbit-replan');
});

await safe('SCIENCE', async () => {
  await go('/science');
  await page.getByRole('heading', { name: /Scientific core/ }).waitFor({ timeout: 15000 });
  check('SCIENCE: five hazards listed', (await page.getByRole('list', { name: 'NASA five hazards' }).getByRole('listitem').count()) === 5);
  check('SCIENCE: evidence library has sourced entries', (await page.getByRole('table', { name: 'Evidence library' }).locator('tbody tr').count()) >= 8);
  const before = await page.getByRole('img', { name: /Hazard interaction graph/ }).getAttribute('aria-label');
  await page.getByLabel('Mission duration').fill('900'); await page.getByLabel('Mission duration').press('Enter'); await page.waitForTimeout(1200);
  const after = await page.getByRole('img', { name: /Hazard interaction graph/ }).getAttribute('aria-label');
  check('SCIENCE: hazard graph reacts to the scenario', before !== after, `${before} → ${after}`);
  await shot('science');
  await go('/mission-lab?tab=radiation');
  await page.getByRole('button', { name: 'Run radiation model' }).click();
  await page.getByText(/Cumulative effective dose/).first().waitFor({ timeout: 20000 });
  check('LAB: radiation dose history with uncertainty', await page.getByRole('table', { name: 'Radiation scenario comparison' }).isVisible());
  await go('/phantom');
  check('PHANTOM: radiation exposure context received from MISSION LAB', await page.getByText('Radiation exposure context').isVisible());
  await go('/body');
  await page.getByText(/scientific basis/).first().click();
  check('BODY: scientific basis of the selected metric', await page.getByText(/NASA HRP risk:/).first().isVisible());
  await shot('radiation');
});

await safe('SYMBIOSIS', async () => {
  await go('/symbiosis');
  const card = page.getByText('Mission Systems analytics');
  await card.waitFor({ timeout: 20000 });
  check('SYMBIOSIS: relationship / compare periods / compare conditions shown', await page.getByText(/Lagged association/).isVisible() && await page.getByText(/Period comparison/).isVisible() && await page.getByText(/Condition comparison/).isVisible());
  check('SYMBIOSIS: correlation labelled as not causal', await page.getByText(/not evidence of causation/i).first().isVisible());
  await card.scrollIntoViewIfNeeded(); await shot('symbiosis-analytics');
});

await safe('API', async () => {
  const h = await api('/api/health');
  check('API: 0.9 capabilities advertised', ['phantom2', 'coorbit-phantom', 'science-core'].every((c) => h.body.capabilities.includes(c)));
  const ev = await api('/api/science/evidence');
  check('API: evidence entries have URL + verification date', ev.body.entries.every((e) => e.url && e.verified_on));
});

await browser.close();
console.log(results.join('\n'));
console.log(`${results.filter((r) => r.startsWith('PASS')).length}/${results.length} passed`);
console.log(errors.length ? 'console errors:\n' + errors.join('\n') : 'no console errors');
process.exit(results.some((r) => r.startsWith('FAIL')) || errors.length ? 1 : 0);
