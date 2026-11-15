/**
 * Offline build: esbuild (bundle) + Tailwind v4 compile API → a single self-contained
 * dist-offline/index.html that runs from file:// or any static host.
 * Used where Vite is unavailable (e.g. air-gapped machines). `npm run build` (Vite) is primary.
 *
 *   node scripts/build-offline.mjs [--mode live|demo] [--api ''(same origin, default)] [--out dist-offline] [--force true]
 *
 * 1.4: default mode is live (desktop). The build verifies feature-manifest.json markers in the output,
 * refuses to overwrite hand-edited output, and writes BUILD_INFO.json (source hash + output hashes).
 *
 * Extra module lookup paths can be given via AETHER_NODE_PATHS (colon-separated).
 */
import { cpSync, existsSync, readFileSync, writeFileSync, mkdirSync, readdirSync, statSync } from 'node:fs';
import { createHash } from 'node:crypto';
import { createRequire } from 'node:module';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

const root = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const args = Object.fromEntries(process.argv.slice(2).reduce((acc, a, i, all) => (a.startsWith('--') ? [...acc, [a.slice(2), all[i + 1]]] : acc), []));
const extra = (process.env.AETHER_NODE_PATHS ?? '').split(':').filter(Boolean);
const req = createRequire(join(root, 'package.json'));
const resolveFrom = (id) => {
  for (const base of [root, ...extra]) {
    try { return createRequire(join(base, 'noop.js')).resolve(id); } catch { /* next */ }
  }
  return req.resolve(id);
};

const esMod = await import(pathToFileURL(resolveFrom('esbuild')).href);
const esbuild = esMod.build ? esMod : esMod.default;
const twMod = await import(pathToFileURL(resolveFrom('tailwindcss')).href);
const tw = twMod.compile ? twMod : twMod.default;
const twDir = dirname(resolveFrom('tailwindcss/package.json'));

const mode = args.mode ?? 'live';
const out = resolve(root, args.out ?? 'dist-offline');
const sha = (buf) => createHash('sha256').update(buf).digest('hex');
const manifest = JSON.parse(readFileSync(join(root, 'feature-manifest.json'), 'utf8'));
const listFiles = (dir, base = dir) => readdirSync(dir).flatMap((f) => {
  const p = join(dir, f);
  return statSync(p).isDirectory() ? listFiles(p, base) : [p.slice(base.length + 1).split('\\').join('/')];
}).sort();

// 1.4 downgrade guard: public/ + src/ are the ONLY sources of truth. If a file in the
// existing output was edited by hand after the last build, stop instead of overwriting it.
const infoPath = join(out, 'BUILD_INFO.json');
if (existsSync(out) && args.force !== 'true') {
  const info = existsSync(infoPath) ? JSON.parse(readFileSync(infoPath, 'utf8')) : null;
  if (info?.outputs) {
    const edited = Object.entries(info.outputs).filter(([f, h]) => existsSync(join(out, f)) && sha(readFileSync(join(out, f))) !== h).map(([f]) => f);
    if (edited.length) {
      console.error(`ABORT: ${edited.join(', ')} in ${out} changed after the last build. Move the change into public/ or src/ (canonical), or rebuild with --force true.`);
      process.exit(3);
    }
  } else {
    const ver = (file) => { try { return Number((readFileSync(file, 'utf8').match(/NASA Data Lab (\d+\.\d+)/) ?? [])[1] ?? 0); } catch { return 0; } };
    const built = ver(join(out, 'aether-nasa-data-lab.js')); const source = ver(join(root, 'public', 'aether-nasa-data-lab.js'));
    if (built > source) {
      console.error(`ABORT: ${out} contains NASA Data Lab ${built} but public/ has ${source}. Merge the newer code into public/ first (or --force true).`);
      process.exit(3);
    }
  }
}

const result = await esbuild.build({
  entryPoints: [join(root, 'src/main.tsx')],
  bundle: true, write: false, format: 'iife', minify: true, target: 'es2020', jsx: 'automatic', charset: 'utf8',
  nodePaths: extra,
  define: {
    'import.meta.env.VITE_DATA_MODE': JSON.stringify(mode),
    // 1.4: same-origin by default. 1.3 baked in http://127.0.0.1:8000, which broke the portable
    // desktop build (its server listens on a random free port).
    'import.meta.env.VITE_API_URL': JSON.stringify(args.api ?? ''),
    // v0.8 fix: V8 added mobile checks; without this define `import.meta.env` is undefined in the IIFE bundle.
    'import.meta.env.VITE_MOBILE_APP': JSON.stringify(args.mobile === '1' ? '1' : '0'),
    'process.env.NODE_ENV': '"production"',
  },
  loader: { '.css': 'empty' },
  logLevel: 'warning',
});
const js = result.outputFiles[0].text;

// Tailwind: collect class candidates from sources, compile the stylesheet.
const candidates = new Set();
const walk = (d) => readdirSync(d).forEach((f) => {
  const p = join(d, f);
  if (statSync(p).isDirectory()) walk(p);
  else if (/\.(tsx?|html)$/.test(f)) for (const m of readFileSync(p, 'utf8').matchAll(/[^\s"'`{}<>;]+/g)) candidates.add(m[0]);
});
walk(join(root, 'src'));
const css = readFileSync(join(root, 'src/styles/index.css'), 'utf8');
const compiler = await tw.compile(css, {
  base: root,
  loadStylesheet: async (id, base) => {
    const file = id === 'tailwindcss' ? join(twDir, 'index.css') : resolve(base, id);
    return { content: readFileSync(file, 'utf8'), base: dirname(file), path: file };
  },
});
const builtCss = compiler.build([...candidates]);

mkdirSync(out, { recursive: true });
const html = readFileSync(join(root, 'index.html'), 'utf8')
  .replace('<script type="module" src="/src/main.tsx"></script>', '')
  .replace('</head>', () => `<style>${builtCss}</style>\n</head>`)
  .replace('</body>', () => `<script>${js.replace(/<\/script/g, '<\\/script')}</script>\n</body>`);
writeFileSync(join(out, 'index.html'), html);
// Static assets (GLB models, icons) – same convention as Vite's public/ directory.
const pub = join(root, 'public');
if (existsSync(pub) && args['no-assets'] !== 'true') cpSync(pub, out, { recursive: true });

// 1.4: verify release feature markers and assets in the OUTPUT, then stamp provenance.
const missing = [];
for (const [file, markers] of Object.entries(manifest.files)) {
  const p = join(out, file);
  const text = existsSync(p) ? readFileSync(p, 'utf8') : '';
  for (const m of markers) if (!text.includes(m)) missing.push(`${file}: "${m}"`);
}
if (args['no-assets'] !== 'true') for (const a of manifest.required_assets) {
  const p = join(out, a);
  if (!existsSync(p) || readFileSync(p).subarray(0, 4).toString('latin1') !== 'glTF') missing.push(`asset ${a}`);
}
if (missing.length) {
  console.error('BUILD FAILED feature/asset verification:\n  ' + missing.join('\n  '));
  process.exit(4);
}
const srcHash = createHash('sha256');
for (const f of listFiles(join(root, 'src'))) srcHash.update(f).update(readFileSync(join(root, 'src', f)));
for (const f of ['index.html', 'feature-manifest.json']) srcHash.update(f).update(readFileSync(join(root, f)));
for (const f of listFiles(pub).filter((f) => !f.endsWith('.glb'))) srcHash.update(f).update(readFileSync(join(pub, f)));
const outputs = Object.fromEntries(listFiles(out).filter((f) => f !== 'BUILD_INFO.json' && !f.endsWith('.glb')).map((f) => [f, sha(readFileSync(join(out, f)))]));
writeFileSync(infoPath, JSON.stringify({ release: manifest.release, mode, built_utc: new Date().toISOString(),
  source_sha256: srcHash.digest('hex'), outputs, feature_markers_verified: true,
  note: 'Generated by scripts/build-offline.mjs. Do not edit files in this directory; edit src/ or public/ and rebuild.' }, null, 2));
console.log(`built ${out}/index.html · mode=${mode} · js ${(js.length / 1024).toFixed(0)} KB · css ${(builtCss.length / 1024).toFixed(0)} KB`);
