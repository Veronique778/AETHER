/** Unit tests: bundle tests/*.test.ts with esbuild and run them with Node's test runner. */
import { mkdtempSync, readdirSync } from 'node:fs';
import { createRequire } from 'node:module';
import { tmpdir } from 'node:os';
import { dirname, join, resolve } from 'node:path';
import { spawnSync } from 'node:child_process';
import { fileURLToPath, pathToFileURL } from 'node:url';
const root = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const extra = (process.env.AETHER_NODE_PATHS ?? '').split(':').filter(Boolean);
const resolveFrom = (id) => { for (const b of [root, ...extra]) { try { return createRequire(join(b, 'noop.js')).resolve(id); } catch { /* next */ } } throw new Error('Cannot resolve ' + id); };
const es = await import(pathToFileURL(resolveFrom('esbuild')).href); const esbuild = es.build ? es : es.default;
const out = mkdtempSync(join(tmpdir(), 'aether-site-tests-'));
const entries = readdirSync(join(root, 'tests')).filter((f) => f.endsWith('.test.ts')).map((f) => join(root, 'tests', f));
await esbuild.build({ entryPoints: entries, bundle: true, platform: 'node', format: 'esm', outdir: out, outExtension: { '.js': '.mjs' }, nodePaths: extra, logLevel: 'warning' });
const r = spawnSync(process.execPath, ['--test', ...readdirSync(out).map((f) => join(out, f))], { stdio: 'inherit' });
process.exit(r.status ?? 1);
