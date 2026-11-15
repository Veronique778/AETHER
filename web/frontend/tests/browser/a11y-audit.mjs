import { createRequire } from 'node:module';
const require = createRequire('/home/claude/.npm-global/lib/node_modules/noop.js');
const { chromium } = require('playwright');
const routes = ['/', '/body', '/body?tab=history', '/body?tab=compare', '/body?tab=entry', '/body?tab=sensors', '/phantom', '/phantom?tab=series', '/phantom?tab=relationships', '/phantom?tab=history',
  '/symbiosis', '/symbiosis?tab=history', '/symbiosis?tab=scenarios', '/co-orbit', '/co-orbit?tab=schedule', '/co-orbit?tab=rest', '/co-orbit?tab=tasks', '/recovery', '/recovery?tab=lab',
  '/recovery/zero-g-garden', '/mission-lab', '/mission-lab?tab=experiments', '/mission-lab?tab=radiation', '/science', '/settings', '/about'];
const browser = await chromium.launch();
const issues = {};
const add = (k, v) => { (issues[k] ??= new Set()).add(v); };
for (const [label, width, theme] of [['1440 dark', 1440, 'dark'], ['720 (=200% zoom) light', 720, 'light'], ['360 (=400% of 1440) dark', 360, 'dark']]) {
  const page = await browser.newPage({ viewport: { width, height: 900 } });
  await page.goto(process.argv[2]); await page.evaluate((t) => localStorage.setItem('aether.theme', t), theme); await page.reload(); await page.waitForTimeout(700);
  for (const r of routes) {
    await page.evaluate((r) => { location.hash = '#' + r; }, r); await page.waitForTimeout(650);
    const res = await page.evaluate(() => {
      const out = [];
      const vis = (e) => { const b = e.getBoundingClientRect(); const s = getComputedStyle(e); return b.width > 0 && b.height > 0 && s.visibility !== 'hidden' && s.display !== 'none'; };
      const name = (e) => (e.getAttribute('aria-label') || e.getAttribute('title') || e.textContent || '').trim() || (e.getAttribute('aria-labelledby') ? 'x' : '');
      for (const e of document.querySelectorAll('button, a[href], [role=tab], [role=radio]')) if (vis(e) && !name(e)) out.push('unnamed control: ' + e.outerHTML.slice(0, 90));
      for (const e of document.querySelectorAll('input, select, textarea')) {
        if (!vis(e)) continue;
        const ok = e.getAttribute('aria-label') || e.getAttribute('aria-labelledby') || e.closest('label') || (e.id && document.querySelector(`label[for="${CSS.escape(e.id)}"]`));
        if (!ok) out.push('unlabelled field: ' + e.outerHTML.slice(0, 90));
      }
      for (const e of document.querySelectorAll('button, a[href], select, input:not([type=range]):not([type=checkbox]):not([type=radio])')) {
        if (!vis(e)) continue; const b = e.getBoundingClientRect();
        if ((b.width < 24 || b.height < 24) && !e.closest('p, li > span')) out.push(`small target ${Math.round(b.width)}x${Math.round(b.height)}: ` + (name(e) || e.outerHTML).slice(0, 50));
      }
      const ids = {}; for (const e of document.querySelectorAll('[id]')) ids[e.id] = (ids[e.id] || 0) + 1;
      for (const [k, v] of Object.entries(ids)) if (v > 1) out.push('duplicate id: ' + k);
      for (const e of document.querySelectorAll('img, svg[role=img], canvas')) if (vis(e) && !e.getAttribute('aria-label') && !e.getAttribute('alt') && !e.querySelector('title') && e.getAttribute('aria-hidden') == null) out.push('graphic without name: ' + e.tagName);
      if (document.querySelectorAll('h1').length !== 1) out.push('h1 count = ' + document.querySelectorAll('h1').length);
      const ov = document.documentElement.scrollWidth - document.documentElement.clientWidth; if (ov > 1) out.push('horizontal overflow ' + ov + 'px');
      return out;
    });
    for (const x of res) add(x, `${r} @ ${label}`);
  }
  await page.close();
}
const keys = Object.keys(issues);
console.log(keys.length ? keys.map((k) => `${k}\n    → ${[...issues[k]].slice(0, 4).join(' | ')}${issues[k].size > 4 ? ` (+${issues[k].size - 4})` : ''}`).join('\n') : 'no issues found');
await browser.close();
