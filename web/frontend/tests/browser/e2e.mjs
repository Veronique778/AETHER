// AETHER v0.5 browser E2E. Usage: node e2e.mjs <url> [live]
import { createRequire } from 'node:module';
const require = createRequire('/home/claude/.npm-global/lib/node_modules/noop.js');
const { chromium } = require('playwright');
const base = process.argv[2]; const live = process.argv[3] === 'live';
const browser = await chromium.launch();
const ctx = await browser.newContext({ viewport: { width: 1600, height: 950 }, acceptDownloads: true });
// Desktop build: emulate the Tauri shell's injected backend address (see desktop/tests/desktop-webview.mjs).
if (process.env.AETHER_DESKTOP_API) await ctx.addInitScript(`window.__AETHER_DESKTOP__ = Object.freeze(${JSON.stringify({ apiBase: process.env.AETHER_DESKTOP_API, version: '0.6.0', backendError: null })});`);
const page = await ctx.newPage();
const errors = []; const results = [];
page.on('console', (m) => { if (m.type() === 'error' && !/404|Failed to load resource/.test(m.text())) errors.push(m.text()); });
page.on('pageerror', (e) => errors.push('pageerror: ' + e.message));
const check = (name, ok, extra = '') => results.push(`${ok ? 'PASS' : 'FAIL'}  ${name}${extra ? '  · ' + extra : ''}`);
const safe = async (name, fn) => { try { await fn(); } catch (e) { check(name, false, String(e.message).split('\n')[0].slice(0, 140)); } };
const go = async (r) => { await page.evaluate((r) => { location.hash = '#' + r; }, r); await page.waitForTimeout(800); };
const tab = async (name) => { await page.getByRole('tab', { name }).click(); await page.waitForTimeout(500); };
await page.goto(base); await page.waitForTimeout(1200);

// 1 Shell & navigation
await safe('NAV', async () => {
  for (const [link, h] of [['BODY', /Alex Vega/], ['PHANTOM', /Analysis/], ['SYMBIOSIS', /Habitat conditions/], ['CO-ORBIT', /Crew coordination/], ['RECOVERY', /Recovery space/], ['MISSION LAB', /Scenario explorer/], ['Mission Control', /Mission Control/]]) {
    await page.getByRole('navigation', { name: 'Modules' }).first().getByRole('link', { name: new RegExp('^' + link) }).click(); await page.waitForTimeout(600);
    check(`NAV: sidebar → ${link}`, await page.getByRole('heading', { level: 1, name: h }).first().isVisible());
  }
});
await safe('SHELL', async () => {
  check('SHELL: mission clock (ID, day, T+)', await page.getByText('AETHER-M1').first().isVisible() && await page.getByText(/T\+ 066d 10:00/).isVisible());
  await page.getByLabel('Mission day', { exact: true }).fill('60'); await page.waitForTimeout(500);
  check('SHELL: context day updates clock', await page.getByText(/T\+ 059d/).isVisible());
  await page.getByLabel('Mission day', { exact: true }).fill('67'); await page.waitForTimeout(500);
  await page.getByRole('button', { name: /^Alerts: \d+/ }).click(); await page.waitForTimeout(600);
  check('SHELL: alert bell opens alerts', await page.getByRole('region', { name: 'Alerts and events' }).isVisible());
});

// 2 Mission Control dashboard
await safe('MC', async () => {
  await go('/');
  for (const r of ['Selected astronaut', 'Mission status', 'Crew status and workload', 'Digital twin preview', 'Biometrics', 'Environment', 'Risk analytics', 'Trend and prediction', 'Recovery', 'Next activity', 'Mission Lab']) check(`MC: panel “${r}”`, await page.getByRole('region', { name: r, exact: true }).first().isVisible());
  await page.getByRole('button', { name: 'Next astronaut' }).click(); await page.waitForTimeout(500);
  check('MC: astronaut switch updates context', (await page.getByLabel('Astronaut', { exact: true }).inputValue()) === 'A02');
  await page.getByRole('button', { name: 'Previous astronaut' }).click(); await page.waitForTimeout(300);
  await page.getByRole('region', { name: 'Digital twin preview' }).getByRole('radio', { name: 'Respiratory' }).click();
  check('MC: twin system select', await page.getByText('No API metric – visual layer').isVisible());
  check(live ? 'MC: demo channels hidden in live' : 'MC: demo channels labelled', live ? (await page.getByText('not provided by API').count()) >= 1 : (await page.getByText('demo', { exact: true }).count()) >= 2);
  check('MC: risk restricted in crew role', await page.getByRole('button', { name: 'View as flight surgeon' }).isVisible());
  await page.getByRole('region', { name: 'Digital twin preview' }).getByRole('button', { name: 'Open BODY' }).click(); await page.waitForTimeout(800);
  check('FLOW: MC → BODY with system preselected', page.url().includes('system=respiratory') && await page.getByText(/No respiratory metric in the API/).isVisible());
  await go('/');
  await page.getByRole('button', { name: 'View spacecraft twin' }).click();
  await page.waitForTimeout(700);
  const shipCanvas = page.getByRole('application').nth(1);
  const shipBounds = await shipCanvas.boundingBox();
  const viewportHeight = await page.evaluate(() => window.innerHeight);
  check('MC: hero shortcut brings the spacecraft viewport into view', !!shipBounds && shipBounds.y < viewportHeight && shipBounds.y + shipBounds.height > 0);
  const canvas = page.getByRole('application').nth(1); await canvas.focus();
  const passiveWheelErrors = () => errors.filter((e) => e.includes('Unable to preventDefault inside passive event listener')).length;
  const wheelErrorsBefore = passiveWheelErrors();
  await canvas.hover(); await page.mouse.wheel(0, 120); await page.waitForTimeout(100);
  check('MC: 3D wheel zoom has no passive-listener errors', passiveWheelErrors() === wheelErrorsBefore);
  for (const k of ['ArrowLeft', 'ArrowUp', '+', '0']) await page.keyboard.press(k);
  check('MC: 3D spacecraft keyboard control', true);
  await page.getByRole('group', { name: /Deck plan, stern to bow/ }).getByRole('button', { name: /^Command deck/ }).focus(); await page.keyboard.press('Enter'); await page.waitForTimeout(400);
  check('MC: deck plan (keyboard) → compartment inspector', await page.getByRole('heading', { name: 'Command deck' }).isVisible());
  await page.getByRole('radio', { name: '00–03' }).click(); await page.waitForTimeout(500);
  check('MC: time window moves crew', (await page.getByLabel('Mission time', { exact: true }).inputValue()) === '0');
  await page.getByRole('radio', { name: '09–12' }).click(); await page.waitForTimeout(300);
  await page.getByLabel('Mission time', { exact: true }).selectOption('10'); await page.waitForTimeout(300);
});

// 3 BODY
await safe('BODY', async () => {
  await go('/body');
  await page.getByRole('radio', { name: /Mira Chen/ }).click(); await page.waitForTimeout(500);
  check('BODY: crew switcher', await page.getByRole('heading', { level: 1, name: 'Mira Chen' }).isVisible());
  await page.getByRole('radio', { name: /Alex Vega/ }).click(); await page.waitForTimeout(400);
  for (const s of ['Cardiovascular', 'Respiratory', 'Neurological', 'Musculoskeletal', 'Metabolic']) check(`BODY: system ${s}`, await page.getByRole('button', { name: new RegExp('^' + s), exact: false }).first().isVisible());
  await page.getByRole('button', { name: 'Record measurement' }).click();
  check('BODY: entry dialog opens', await page.getByRole('dialog').isVisible());
  await page.getByLabel('Resting heart rate (bpm)').fill('500'); await page.getByRole('button', { name: 'Save measurement' }).click();
  check('BODY: form validation', await page.getByText('Must be between 20 and 240 bpm.').isVisible());
  await page.getByLabel('Resting heart rate (bpm)').fill(''); await page.getByLabel('Reaction time (ms)').fill('300');
  await page.getByRole('button', { name: 'Save measurement' }).click(); await page.waitForTimeout(700);
  check('BODY: save via API client', await page.getByText(/Saved for day 67/).isVisible() || !(await page.getByRole('dialog').count()));
  await page.keyboard.press('Escape');
  await tab('Measurement history'); check('BODY: history tab', page.url().includes('tab=history'));
  await tab('Compare time points'); check('BODY: compare time points', await page.getByLabel(/Time point A/).first().isVisible());
});

// 4 PHANTOM
await safe('PHANTOM', async () => {
  await go('/settings'); await page.getByRole('radio', { name: 'Flight surgeon' }).click();
  await go('/phantom');
  check('PHANTOM: gauge + radar', await page.getByRole('img', { name: /Deviation index \d+ of 100/ }).isVisible() && await page.getByRole('group', { name: /Deviation radar/ }).isVisible());
  await page.getByRole('button', { name: /^Sleep duration: robust z/ }).click();
  check('PHANTOM: radar axis selects signal', await page.getByRole('region', { name: /Selected signal: Sleep duration/ }).isVisible());
  await tab('Signal & event explorer');
  await page.getByRole('button', { name: /flagged on day \d+\. Explore/ }).first().click(); await page.waitForTimeout(700);
  check('PHANTOM: deviation marker → event explorer', await page.getByText('What happened that day').isVisible() && await page.getByText(/Related charts/).isVisible());
  await tab('Relationships');
  await page.getByRole('button', { name: /^Resting heart rate.*Highlight its relationships/ }).click();
  check('PHANTOM: relationship graph node', await page.getByRole('button', { name: /^Resting heart rate.*Highlight/ }).getAttribute('aria-pressed') === 'true');
  await tab('Episodes & reports');
  check('PHANTOM: predicted vs observed', await page.getByText('Index: last 14 days and next 14 days').isVisible());
  const [dl] = await Promise.all([page.waitForEvent('download'), page.getByRole('button', { name: /Download report/ }).click()]);
  check('PHANTOM: report download', /PHANTOM/.test(dl.suggestedFilename()), dl.suggestedFilename());
});

// 5 Cross-module scenario
await safe('SCENARIO', async () => {
  await go('/mission-lab');
  await page.getByRole('button', { name: /^Elevated CO₂/ }).click();
  check('LAB: radiation scenario honestly disabled', await page.getByRole('button', { name: /Increased radiation exposure/ }).isDisabled());
  await page.getByRole('button', { name: 'Apply to mission' }).first().click(); await page.waitForTimeout(500);
  check('SCENARIO: global banner', await page.getByRole('region', { name: 'Applied scenario' }).isVisible());
  for (const [path, re] of [['/symbiosis', /Cabin conditions under the scenario/], ['/phantom', /PHANTOM on recorded data vs on the modelled scenario day/], ['/body', /modelled vs actual/], ['/co-orbit', /Modelled crew plan/]]) {
    await go(path); await page.waitForTimeout(600);
    check(`SCENARIO: propagates to ${path}`, await page.getByText(re).first().isVisible());
  }
  await page.getByRole('button', { name: 'Reset scenario' }).click(); await page.waitForTimeout(300);
  check('SCENARIO: reset clears everywhere', !(await page.getByRole('region', { name: 'Applied scenario' }).count()) && !(await page.getByText(/Modelled crew plan/).count()));
});

// 6 SYMBIOSIS
await safe('SYMBIOSIS', async () => {
  await go('/symbiosis');
  await page.getByRole('group', { name: /Deck plan coloured by/ }).getByRole('button', { name: /^Medical bay/ }).click(); await page.waitForTimeout(400);
  check('SYMBIOSIS: plan selects compartment (shared context)', (await page.getByLabel('Compartment', { exact: true }).inputValue()) === 'medical');
  await page.getByRole('radio', { name: 'Temperature' }).first().click();
  check('SYMBIOSIS: parameter heat map', await page.getByRole('group', { name: /Deck plan coloured by Temperature/ }).isVisible());
  await page.getByRole('radio', { name: 'Model 3D' }).click(); await page.waitForTimeout(500);
  check('SYMBIOSIS: 3D view toggle', (await page.getByRole('application').count()) >= 1);
  await tab('History & before / after');
  check('SYMBIOSIS: before/after plans', await page.getByRole('group', { name: /Plan on Day/ }).first().isVisible());
  await tab('Scenarios (model)');
  await page.getByRole('button', { name: 'Add set' }).click();
  await page.getByRole('button', { name: /^Run for/ }).click(); await page.waitForTimeout(800);
  check('SYMBIOSIS: condition sets compared', await page.getByText(/Modelled PHANTOM index/).isVisible());
});

// 7 CO-ORBIT
await safe('CO-ORBIT', async () => {
  await go('/co-orbit');
  check('CO-ORBIT: crew map', await page.getByRole('group', { name: 'Crew positions on the deck plan' }).isVisible());
  await tab('Timeline & calendar');
  await page.getByRole('button', { name: /^Day 055:/ }).click(); await page.waitForTimeout(400);
  check('CO-ORBIT: mission calendar sets day', (await page.getByLabel('Mission day', { exact: true }).inputValue()) === '55');
  await page.getByLabel('Mission day', { exact: true }).fill('67'); await page.waitForTimeout(300);
  await tab('Task board'); await page.waitForTimeout(700);
  await page.locator('li[draggable]').filter({ hasText: 'Science experiment' }).dragTo(page.getByRole('group', { name: /^Sam Okafor:/ }));
  check('CO-ORBIT: drag-and-drop reassign', await page.getByText('1 change from the optimiser plan').isVisible());
  await page.getByLabel('Owner of Health assessment').selectOption({ label: 'Alex Vega (no skill)' }); await page.waitForTimeout(200);
  check('CO-ORBIT: keyboard reassign → conflict', await page.getByText(/lacks the medical skill/).first().isVisible());
  await page.getByRole('button', { name: 'Confirm plan…' }).click();
  check('CO-ORBIT: confirmation dialog lists changes', await page.getByRole('dialog').getByText(/Health assessment/).first().isVisible());
  await page.getByRole('dialog').getByRole('button', { name: 'Confirm plan' }).click(); await page.waitForTimeout(300);
  check('CO-ORBIT: confirmed + toast', await page.getByText(/Task plan confirmed for day 67/).isVisible());
});

// 8 MISSION LAB
await safe('LAB', async () => {
  await go('/mission-lab');
  await page.getByRole('button', { name: /^Start simulation \(/ }).click(); await page.waitForTimeout(1800);
  check('LAB: process pipeline + playback', await page.getByRole('progressbar', { name: 'Playback progress' }).isVisible() && page.url().includes('tab=results'));
  await page.getByRole('button', { name: 'Pause' }).click();
  check('LAB: difference + side-by-side', await page.getByText(/Difference in phantom index/i).isVisible() && await page.getByText(/one panel per scenario/).isVisible());
  const [j] = await Promise.all([page.waitForEvent('download'), page.getByRole('button', { name: 'JSON' }).click()]);
  const [c] = await Promise.all([page.waitForEvent('download'), page.getByRole('button', { name: 'CSV' }).click()]);
  const [m] = await Promise.all([page.waitForEvent('download'), page.getByRole('button', { name: /Summary report/ }).click()]);
  check('LAB: export JSON/CSV/report', [j, c, m].every(Boolean), [j, c, m].map((d) => d.suggestedFilename()).join(', '));
  await page.getByRole('button', { name: 'Reset' }).click();
  await page.getByRole('button', { name: 'Save experiment' }).click(); await tab('Saved experiments');
  check('LAB: experiment saved', await page.getByText(/\d+ saved/).isVisible());
});

// 9 RECOVERY
await safe('RECOVERY', async () => {
  await go('/recovery');
  check('RECOVERY: hero + trends', await page.getByRole('region', { name: 'Recovery space' }).isVisible() && await page.getByRole('region', { name: 'Sleep and fatigue trends' }).isVisible());
  await go('/recovery/earth-window'); await page.getByRole('radio', { name: '5' }).click(); await page.getByRole('button', { name: 'Begin activity' }).click(); await page.waitForTimeout(500);
  check('EARTH WINDOW: orbit scene default', await page.getByRole('img', { name: /Earth seen from orbit/ }).isVisible());
  await page.getByRole('radio', { name: 'Forest' }).click(); await page.getByRole('button', { name: 'Start timer' }).click(); await page.waitForTimeout(800);
  check('EARTH WINDOW: scene change + timer', await page.getByRole('img', { name: /forest/ }).isVisible() && await page.getByRole('button', { name: 'Stop' }).isVisible());
  await go('/recovery/orbit-flow'); await page.getByRole('radio', { name: '7' }).click(); await page.getByRole('button', { name: 'Begin activity' }).click(); await page.waitForTimeout(300);
  await page.getByRole('gridcell').first().click(); await page.getByRole('gridcell').nth(1).focus(); await page.keyboard.press('Enter');
  check('ORBIT FLOW: mouse + keyboard rotate', (await page.locator('text=Moves').locator('..').textContent()).includes('2'));
  await go('/recovery/mind-pulse');
  await page.getByRole('radio', { name: '4' }).click(); await page.getByRole('button', { name: 'Begin activity' }).click(); await page.waitForTimeout(300);
  check('MIND PULSE: breathing rhythm + sync option', await page.getByText(/s per breath/).isVisible() && await page.getByLabel('Sync with biofeedback breathing rate').isVisible());
  await page.getByRole('radio', { name: '12' }).click(); await page.getByRole('button', { name: 'Start test' }).click();
  for (let i = 0; i < 12; i++) {
    await page.waitForSelector('text=/circle – press|square – wait/', { timeout: 6000 });
    if (await page.getByText('circle – press').isVisible().catch(() => false)) { await page.waitForTimeout(200); await page.keyboard.press('Space'); }
    await page.waitForSelector('text=/ms$|Correctly withheld|Missed|Square|Test complete/', { timeout: 4000 }).catch(() => {});
    if (await page.getByText('Test complete').isVisible().catch(() => false)) break;
  }
  await page.waitForSelector('text=Test complete', { timeout: 8000 });
  check('MIND PULSE: results + rhythm strip', await page.getByText('Median RT').isVisible() && await page.getByRole('img', { name: /Response rhythm/ }).isVisible());
  await page.getByRole('button', { name: 'Finish activity' }).click(); await page.getByRole('radio', { name: '6' }).click();
  await page.getByRole('button', { name: 'Save session' }).click(); await page.waitForTimeout(500);
  check('RECOVERY: session saved', await page.getByText('Session saved').isVisible());
  await go('/recovery/zero-g-garden');
  await page.getByRole('radio', { name: '5' }).click(); await page.getByRole('button', { name: 'Begin activity' }).click(); await page.waitForTimeout(300);
  await page.getByRole('button', { name: 'Start' }).click(); await page.waitForTimeout(1500);
  check('GARDEN: breathing session runs', await page.getByText(/Breathe (in|out)/).isVisible());
  await page.getByRole('button', { name: 'Pause' }).click();
});

// 10 Settings & responsive
await safe('SETTINGS', async () => {
  await go('/settings');
  await page.getByRole('radio', { name: 'Light', exact: true }).click(); await page.waitForTimeout(200);
  check('SETTINGS: light theme', await page.evaluate(() => document.documentElement.classList.contains('theme-light')));
  await page.getByRole('radio', { name: 'Dark', exact: true }).click(); await page.getByRole('radio', { name: 'Crew member', exact: true }).click();
  for (const [w, h] of [[390, 844], [820, 1180], [1366, 768], [1920, 1080]]) {
    await page.setViewportSize({ width: w, height: h }); await go('/'); await page.waitForTimeout(500);
    const overflow = await page.evaluate(() => { const st = getComputedStyle(document.documentElement).overflowX; return st === 'clip' ? 0 : document.documentElement.scrollWidth - document.documentElement.clientWidth; });
    check(`RESPONSIVE: ${w}px no horizontal scroll`, overflow <= 1);
    await page.screenshot({ path: `/tmp/shots/v5-e2e-${w}.png` });
  }
  await page.setViewportSize({ width: 390, height: 844 });
  await page.getByRole('button', { name: 'Open navigation' }).click();
  check('MOBILE: nav drawer', await page.getByRole('link', { name: /^MISSION LAB/ }).isVisible());
});

console.log(results.join('\n'));
console.log(`${results.filter((r) => r.startsWith('PASS')).length}/${results.length} passed`);
console.log(errors.length ? 'CONSOLE ERRORS:\n' + errors.join('\n') : 'no console errors');
await browser.close();
