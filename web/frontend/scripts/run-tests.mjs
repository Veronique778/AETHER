/**
 * Runs tests/*.test.ts with Node's built-in test runner after bundling them with esbuild.
 *   node scripts/run-tests.mjs            – unit tests
 *   node scripts/run-tests.mjs --parity   – print parity JSON (used by backend/tests/test_parity.py)
 * Extra module lookup paths: AETHER_NODE_PATHS (colon-separated).
 */
import { mkdtempSync, readdirSync, writeFileSync } from 'node:fs';
import { createRequire } from 'node:module';
import { tmpdir } from 'node:os';
import { dirname, join, resolve } from 'node:path';
import { spawnSync } from 'node:child_process';
import { fileURLToPath, pathToFileURL } from 'node:url';

const root = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const extra = (process.env.AETHER_NODE_PATHS ?? '').split(':').filter(Boolean);
const resolveFrom = (id) => {
  for (const base of [root, ...extra]) { try { return createRequire(join(base, 'noop.js')).resolve(id); } catch { /* next */ } }
  throw new Error(`Cannot resolve ${id}`);
};
const esMod = await import(pathToFileURL(resolveFrom('esbuild')).href);
const esbuild = esMod.build ? esMod : esMod.default;
const out = mkdtempSync(join(tmpdir(), 'aether-tests-'));
const parity = process.argv.includes('--parity');
const entries = parity ? [join(root, 'tests/parity-export.ts')] : readdirSync(join(root, 'tests')).filter((f) => f.endsWith('.test.ts')).map((f) => join(root, 'tests', f));
await esbuild.build({ entryPoints: entries, bundle: true, platform: 'node', format: 'esm', outdir: out, outExtension: { '.js': '.mjs' }, nodePaths: extra, logLevel: 'warning', define: { 'import.meta.env.VITE_API_URL': 'undefined', 'import.meta.env.VITE_DATA_MODE': 'undefined', 'import.meta.env.VITE_MOBILE_APP': '"0"', __AETHER_ROOT__: JSON.stringify(root) } });
const files = readdirSync(out).map((f) => join(out, f));
const r = spawnSync(process.execPath, parity ? files : ['--test', ...files], { stdio: 'inherit' });
process.exit(r.status ?? 1);
