/**
 * Production build without Vite (offline / air-gapped machines). Primary build: `npm run build` (tsc + Vite).
 * Same output shape as Vite with base './': dist/index.html + dist/assets/index-<hash>.js|css + lazy chunks,
 * public/ copied verbatim. Requires esbuild, tailwindcss, react, react-dom (AETHER_NODE_PATHS may point to them).
 *
 *   node scripts/build-offline.mjs [--out dist]
 */
import { cpSync, existsSync, mkdirSync, readFileSync, readdirSync, renameSync, rmSync, statSync, writeFileSync } from 'node:fs';
import { createHash } from 'node:crypto';
import { createRequire } from 'node:module';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

const root = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const args = Object.fromEntries(process.argv.slice(2).reduce((acc, a, i, all) => (a.startsWith('--') ? [...acc, [a.slice(2), all[i + 1]]] : acc), []));
const extra = (process.env.AETHER_NODE_PATHS ?? '').split(':').filter(Boolean);
const resolveFrom = (id) => { for (const b of [root, ...extra]) { try { return createRequire(join(b, 'noop.js')).resolve(id); } catch { /* next */ } } throw new Error(`Cannot resolve ${id}`); };
const es = await import(pathToFileURL(resolveFrom('esbuild')).href); const esbuild = es.build ? es : es.default;
const twm = await import(pathToFileURL(resolveFrom('tailwindcss')).href); const tw = twm.compile ? twm : twm.default;
const twDir = dirname(resolveFrom('tailwindcss/package.json'));
const out = resolve(root, args.out ?? 'dist');
const short = (b) => createHash('sha256').update(b).digest('base64url').replace(/[-_]/g, 'x').slice(0, 8);
const listFiles = (dir, base = dir) => readdirSync(dir).flatMap((f) => { const p = join(dir, f); return statSync(p).isDirectory() ? listFiles(p, base) : [p.slice(base.length + 1).split('\\').join('/')]; }).sort();

rmSync(out, { recursive: true, force: true });
mkdirSync(join(out, 'assets'), { recursive: true });
const res = await esbuild.build({
  entryPoints: { index: join(root, 'src/main.tsx') }, bundle: true, splitting: true, format: 'esm', minify: true, target: 'es2020',
  jsx: 'automatic', charset: 'utf8', legalComments: 'none', outdir: join(out, 'assets'), entryNames: '[name]-[hash]', chunkNames: 'chunk-[hash]',
  nodePaths: extra, metafile: true, define: { 'process.env.NODE_ENV': '"production"' }, loader: { '.css': 'empty' }, logLevel: 'warning',
});
const entryJs = Object.entries(res.metafile.outputs).find(([, o]) => o.entryPoint?.endsWith('src/main.tsx'))[0].split('/').pop();

const candidates = new Set();
const walk = (d) => readdirSync(d).forEach((f) => { const p = join(d, f); if (statSync(p).isDirectory()) walk(p); else if (/\.(tsx?|html)$/.test(f)) for (const m of readFileSync(p, 'utf8').matchAll(/[^\s"'`{}<>;]+/g)) candidates.add(m[0]); });
walk(join(root, 'src')); candidates.add('sr-only');
const compiler = await tw.compile(readFileSync(join(root, 'src/styles/index.css'), 'utf8'), {
  base: root,
  loadStylesheet: async (id, base) => { const file = id === 'tailwindcss' ? join(twDir, 'index.css') : resolve(base, id); return { content: readFileSync(file, 'utf8'), base: dirname(file), path: file }; },
});
const css = compiler.build([...candidates]);
const cssName = `index-${short(css)}.css`;
writeFileSync(join(out, 'assets', cssName), css);
if (existsSync(join(root, 'public'))) cpSync(join(root, 'public'), out, { recursive: true });
const html = readFileSync(join(root, 'index.html'), 'utf8').replace('<script type="module" src="/src/main.tsx"></script>',
  `<script type="module" crossorigin src="./assets/${entryJs}"></script>\n    <link rel="stylesheet" crossorigin href="./assets/${cssName}">`);
writeFileSync(join(out, 'index.html'), html);

// release checks: no backend calls, no absolute asset paths, size limits of Cloudflare Pages (25 MiB per file)
const problems = [];
for (const f of listFiles(out)) {
  const size = statSync(join(out, f)).size;
  if (size > 25 * 1024 * 1024) problems.push(`${f} exceeds 25 MiB (${size})`);
  if (/\.(js|html)$/.test(f)) {
    const t = readFileSync(join(out, f), 'utf8');
    if (/\/api\/|127\.0\.0\.1|localhost:\d/.test(t)) problems.push(`${f} references a backend/API URL`);
  }
}
if (/(src|href)="\/(?!\/)/.test(html)) problems.push('index.html uses absolute asset paths');
if (problems.length) { console.error('BUILD FAILED:\n  ' + problems.join('\n  ')); process.exit(4); }
const outputs = Object.fromEntries(listFiles(out).filter((f) => !f.endsWith('.glb')).map((f) => [f, createHash('sha256').update(readFileSync(join(out, f))).digest('hex')]));
writeFileSync(join(out, 'BUILD_INFO.json'), JSON.stringify({ site: 'aether-website', built_utc: new Date().toISOString(), builder: 'scripts/build-offline.mjs (esbuild + tailwindcss compile API)', entry: entryJs, css: cssName, outputs }, null, 2));
const jsKb = listFiles(join(out, 'assets')).filter((f) => f.endsWith('.js')).map((f) => `${f} ${(statSync(join(out, 'assets', f)).size / 1024).toFixed(0)} KB`);
console.log(`built ${out}\n  ${jsKb.join('\n  ')}\n  ${cssName} ${(css.length / 1024).toFixed(0)} KB`);
