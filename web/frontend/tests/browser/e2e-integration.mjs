// AETHER v0.8 integration E2E (GLB digital twin, Mission Systems engine, cross-module flow, former pending contracts).
// Usage: node e2e-integration.mjs <url> [screenshot-dir]      (needs a Live backend serving the built UI)
import { mkdirSync } from 'node:fs';
import { createRequire } from 'node:module';
const require = createRequire(process.env.AETHER_PLAYWRIGHT_FROM ?? '/home/claude/.npm-global/lib/node_modules/noop.js');
const { chromium } = require('playwright');
const base = process.argv[2] ?? 'http://127.0.0.1:8000/';
const shots = process.argv[3] ?? null;
if (shots) mkdirSync(shots, { recursive: true });
const browser = await chromium.launch({ args: ['--use-gl=angle', '--use-angle=swiftshader', '--enable-unsafe-swiftshader'] });
const ctx = await browser.newContext({ viewport: { width: 1600, height: 1000 }, acceptDownloads: true });
const page = await ctx.newPage();
const errors = []; const results = [];
page.on('console', (m) => { if (m.type() === 'error' && !/404|Failed to load resource/.test(m.text())) errors.push(m.text()); });
page.on('pageerror', (e) => errors.push('pageerror: ' + e.message));
const check = (name, ok, extra = '') => results.push(`${ok ? 'PASS' : 'FAIL'}  ${name}${extra ? '  · ' + extra : ''}`);
const safe = async (name, fn) => { try { await fn(); } catch (e) { check(name, false, String(e.message).split('\n')[0].slice(0, 160)); } };
const go = async (r) => { await page.evaluate((r) => { location.hash = '#' + r; }, r); await page.waitForTimeout(900); };
const shot = async (name) => { if (shots) await page.screenshot({ path: `${shots}/${name}.png` }); };
const api = (path, init) => page.evaluate(async ([p, i]) => { const r = await fetch(p, i); return { status: r.status, body: await r.json() }; }, [path, init]);

await page.goto(base + '?mode=live'); await page.waitForTimeout(1500);

// ---------------------------------------------------------------- BODY: GLB assets
await safe('BODY GLB', async () => {
  await go('/body');
  const select = page.getByLabel('3D model');
  check('BODY: model selector lists 5 assets', (await select.locator('option').count()) === 5);
  for (const [id, wait] of [['anatom', 8000], ['meza', 8000], ['cosmo11', 60000]]) {
    await select.selectOption(id);
    await page.getByText(/Loading .*\.glb/).waitFor({ state: 'detached', timeout: wait }).catch(() => undefined);
    await page.waitForTimeout(1200);
    const err = await page.getByRole('alert').filter({ hasText: 'Showing the schematic' }).count();
    const gl = await page.getByText('WebGL', { exact: true }).first().isVisible();
    check(`BODY: ${id}.glb loads in WebGL`, err === 0 && gl);
    await shot(`body-${id}-xray`);
    if (id === 'cosmo11') {
      await page.getByRole('radio', { name: 'Surface' }).or(page.getByRole('button', { name: 'Surface' })).first().click();
      await page.waitForTimeout(1200); await shot('body-cosmo11-surface');
      await page.getByRole('radio', { name: 'X-ray layers' }).or(page.getByRole('button', { name: 'X-ray layers' })).first().click();
      await page.waitForTimeout(600);
    }
  }
  // picking on the GLB: click the head region → Neurological system selected
  await select.selectOption('anatom'); await page.waitForTimeout(2500);
  await page.getByRole('radio', { name: 'Surface' }).or(page.getByRole('button', { name: 'Surface' })).first().click(); await page.waitForTimeout(800);
  const canvas = page.getByRole('application', { name: /3D human digital twin/ });
  await canvas.scrollIntoViewIfNeeded(); await page.waitForTimeout(400);
  const box = await canvas.boundingBox();
  await page.mouse.click(box.x + box.width / 2, box.y + box.height * 0.29); await page.waitForTimeout(700);
  const pressed = await page.locator('button[aria-pressed="true"]').filter({ hasText: /Neuro|Nervous|Cognitive/i }).count();
  check('BODY: click on GLB head selects the nervous system', pressed > 0);
  await shot('body-anatom-surface-pick');
  await select.selectOption('skeleton'); await page.waitForTimeout(2500);
  check('BODY: Draco skeleton reported honestly + fallback', await page.getByRole('alert').filter({ hasText: /Compressed geometry/ }).isVisible());
  await select.selectOption('anatom'); await page.waitForTimeout(1500);
  await page.getByRole('radio', { name: 'X-ray layers' }).or(page.getByRole('button', { name: 'X-ray layers' })).first().click();
});

// ---------------------------------------------------------------- MISSION LAB: engine
await safe('ENGINE', async () => {
  await go('/mission-lab?tab=engine');
  check('LAB: engine tab lists 11 templates', (await page.getByRole('list', { name: 'Engine scenario templates' }).getByRole('button').count()) === 11);
  await page.getByRole('button', { name: /Multifactor/ }).click();
  await page.getByRole('button', { name: 'Run engine' }).click();
  await page.getByText('AETHER PHANTOM (median / MAD)').waitFor({ timeout: 30000 });
  check('LAB: engine run → PHANTOM vs threshold evaluation', true);
  check('LAB: MILP schedule rendered', await page.getByRole('list', { name: /Schedule \(balanced\)/ }).first().isVisible());
  await page.getByRole('group', { name: 'Engine time controls' }).getByRole('button', { name: 'Start' }).click();
  await page.waitForTimeout(2600);
  const t = await page.getByRole('slider', { name: 'Engine time cursor (minutes)' }).inputValue();
  check('LAB: engine playback advances the model clock', Number(t) > 0, `minute ${t}`);
  await page.getByRole('group', { name: 'Engine time controls' }).getByRole('button', { name: 'Pause' }).click();
  await shot('lab-engine');
  await page.getByRole('button', { name: 'Apply to mission' }).first().click(); await page.waitForTimeout(800);
  check('LAB: engine run applied → global scenario banner', await page.getByRole('region', { name: 'Applied scenario' }).getByText(/Engine ·/).isVisible());
  // second run + comparison
  await page.getByRole('button', { name: /Nominal day/ }).click();
  await page.getByRole('button', { name: 'Run engine' }).click(); await page.waitForTimeout(4000);
  await page.getByRole('button', { name: 'Compare', exact: true }).click(); await page.waitForTimeout(2500);
  check('LAB: controlled comparison of two runs', await page.getByText(/Same seed – differences come from the parameters/).isVisible());
  // re-apply the multifactor run for the module checks
  await page.getByRole('button', { name: /Multifactor/ }).click();
  await page.getByRole('button', { name: 'Run engine' }).click(); await page.waitForTimeout(4000);
  await page.getByRole('button', { name: 'Apply to mission' }).first().click(); await page.waitForTimeout(600);
});

// ---------------------------------------------------------------- propagation to every module
await safe('FLOW', async () => {
  await go('/body');
  check('FLOW: BODY shows modelled scenario + engine crew series', await page.getByText('Engine crew time series (synthetic)').isVisible() && await page.getByText(/modelled vs actual/).isVisible());
  await go('/phantom');
  check('FLOW: PHANTOM shows research evaluation of the engine run', await page.getByText('PHANTOM on labelled synthetic events').isVisible());
  await shot('phantom-engine');
  await go('/symbiosis');
  check('FLOW: SYMBIOSIS shows modelled cabin series', await page.getByText('Modelled cabin conditions during the engine run').isVisible());
  await go('/symbiosis?tab=links');
  check('SYMBIOSIS: crew association no longer pending', (await page.getByText('Waiting for backend integration').count()) === 0);
  await go('/co-orbit');
  check('FLOW: CO-ORBIT shows MILP schedule of the engine run', await page.getByText('Optimised task schedule for the engine scenario').isVisible());
  await shot('coorbit-engine');
  await go('/recovery');
  check('FLOW: RECOVERY suggests activities from PHANTOM + scenario', await page.getByRole('region', { name: 'Suggested recovery activities' }).getByRole('button', { name: 'Begin' }).first().isVisible());
  await shot('recovery-suggestions');
  await page.getByRole('region', { name: 'Suggested recovery activities' }).getByRole('button', { name: 'Begin' }).first().click(); await page.waitForTimeout(700);
  check('FLOW: suggestion opens the activity', /#\/recovery\/[a-z-]+/.test(page.url()));
});

// ---------------------------------------------------------------- former pending contracts & persistence
await safe('BACKEND', async () => {
  const bio = await api('/api/recovery/biofeedback?astronaut_id=A01');
  check('API: biofeedback (simulated, labelled)', bio.status === 200 && bio.body.source === 'simulated');
  const exp = { id: 'e2e', name: 'E2E', created_at: '2026-11-13 20:00', astronaut_id: 'A01', start_day: 67, horizon_days: 7, runs: 50, seed: 1,
    scenarios: [{ key: 'A', title: 'x', params: { sleep_delta: 0, workload: 50, co2_ppm: 850, temperature_c: 22, crew_available: 4 }, end: { score_p50: 1, score_p10: 0, score_p90: 2, attention_share: 0, fatigue_p50: 3 } }] };
  const saved = await api('/api/mission-lab/experiments', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(exp) });
  const list = await api('/api/mission-lab/experiments');
  check('API: experiments stored server-side', saved.status === 200 && list.body.some((e) => e.id === 'e2e'));
  await go('/mission-lab?tab=experiments');
  check('LAB: experiments tab reads the server store', await page.getByText('Stored in the local AETHER database').isVisible() && await page.getByText('E2E', { exact: true }).isVisible());
  await page.reload(); await page.waitForTimeout(2500);
  await go('/co-orbit');
  check('PERSIST: last engine run restored after reload', await page.getByText('Optimised task schedule for the engine scenario').isVisible());
});

await safe('DEMO', async () => {
  await page.goto(base + '#/mission-lab?tab=engine&mode=demo'); await page.waitForTimeout(1500);
  check('DEMO: engine tab explains it needs the backend', await page.getByText('Not available in Demo Mode').isVisible());
  await page.goto(base + '#/?mode=live'); await page.waitForTimeout(800);
});

await browser.close();
console.log(results.join('\n'));
console.log(`${results.filter((r) => r.startsWith('PASS')).length}/${results.length} passed`);
console.log(errors.length ? 'console errors:\n' + errors.join('\n') : 'no console errors');
process.exit(results.some((r) => r.startsWith('FAIL')) || errors.length ? 1 : 0);
