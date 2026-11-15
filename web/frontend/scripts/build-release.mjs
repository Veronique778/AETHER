/**
 * AETHER 1.5 production build → dist/ (the layout the Windows desktop serves: index.html + content-hashed assets/).
 *
 * Primary build is `npm run build` (tsc + Vite) when node_modules are installed. This script produces the SAME
 * shape (index.html referencing /assets/index-<hash>.js and /assets/index-<hash>.css, public/ copied verbatim) with
 * esbuild + the Tailwind v4 compile API, for offline / air-gapped release machines where Vite cannot be installed.
 * It never edits an existing bundle: dist/ is deleted and rebuilt from src/ + public/ every time.
 *
 *   node scripts/build-release.mjs [--out dist] [--mode live]
 * Extra module lookup paths: AETHER_NODE_PATHS (colon-separated), e.g. a global node_modules.
 */
import { cpSync, existsSync, mkdirSync, readFileSync, readdirSync, rmSync, statSync, writeFileSync } from 'node:fs';
import { createHash } from 'node:crypto';
import { createRequire } from 'node:module';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

const root = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const args = Object.fromEntries(process.argv.slice(2).reduce((acc, a, i, all) => (a.startsWith('--') ? [...acc, [a.slice(2), all[i + 1]]] : acc), []));
const extra = (process.env.AETHER_NODE_PATHS ?? '').split(':').filter(Boolean);
const resolveFrom = (id) => {
  for (const base of [root, ...extra]) {
    try { return createRequire(join(base, 'noop.js')).resolve(id); } catch { /* next */ }
  }
  throw new Error(`Cannot resolve ${id}; install devDependencies or set AETHER_NODE_PATHS`);
};
const esMod = await import(pathToFileURL(resolveFrom('esbuild')).href);
const esbuild = esMod.build ? esMod : esMod.default;
const twMod = await import(pathToFileURL(resolveFrom('tailwindcss')).href);
const tw = twMod.compile ? twMod : twMod.default;
const twDir = dirname(resolveFrom('tailwindcss/package.json'));
const reactVersion = JSON.parse(readFileSync(resolveFrom('react/package.json'), 'utf8')).version;

const out = resolve(root, args.out ?? 'dist');
const mode = args.mode ?? 'live';
const sha = (buf) => createHash('sha256').update(buf).digest('hex');
const short = (buf) => createHash('sha256').update(buf).digest('base64url').slice(0, 8);
const listFiles = (dir, base = dir) => readdirSync(dir).flatMap((f) => {
  const p = join(dir, f);
  return statSync(p).isDirectory() ? listFiles(p, base) : [p.slice(base.length + 1).split('\\').join('/')];
}).sort();

const result = await esbuild.build({
  entryPoints: [join(root, 'src/main.tsx')],
  bundle: true, write: false, format: 'esm', minify: true, target: 'es2020', jsx: 'automatic',
  nodePaths: extra, legalComments: 'none', charset: 'utf8',
  define: {
    'import.meta.env.VITE_DATA_MODE': JSON.stringify(mode),
    'import.meta.env.VITE_API_URL': JSON.stringify(args.api ?? ''),
    'import.meta.env.VITE_MOBILE_APP': '"0"',
    'process.env.NODE_ENV': '"production"',
  },
  loader: { '.css': 'empty' },
  logLevel: 'warning',
});
const js = result.outputFiles[0].text;

const candidates = new Set();
const walk = (d) => readdirSync(d).forEach((f) => {
  const p = join(d, f);
  if (statSync(p).isDirectory()) walk(p);
  else if (/\.(tsx?|html)$/.test(f)) for (const m of readFileSync(p, 'utf8').matchAll(/[^\s"'`{}<>;]+/g)) candidates.add(m[0]);
});
walk(join(root, 'src'));
const compiler = await tw.compile(readFileSync(join(root, 'src/styles/index.css'), 'utf8'), {
  base: root,
  loadStylesheet: async (id, base) => {
    const file = id === 'tailwindcss' ? join(twDir, 'index.css') : resolve(base, id);
    return { content: readFileSync(file, 'utf8'), base: dirname(file), path: file };
  },
});
const css = compiler.build([...candidates]);

rmSync(out, { recursive: true, force: true });
mkdirSync(join(out, 'assets'), { recursive: true });
const pub = join(root, 'public');
if (existsSync(pub)) cpSync(pub, out, { recursive: true });
const jsName = `assets/index-${short(js)}.js`;
const cssName = `assets/index-${short(css)}.css`;
writeFileSync(join(out, jsName), js);
writeFileSync(join(out, cssName), css);
const html = readFileSync(join(root, 'index.html'), 'utf8')
  .replace(/\s*<script type="module" src="\/src\/main\.tsx"><\/script>/, '')
  .replace("  </head>", `    <script type="module" crossorigin src="/${jsName}"></script>\n    <link rel="stylesheet" crossorigin href="/${cssName}">\n  </head>`);
writeFileSync(join(out, 'index.html'), html);

// release markers (fail closed if a feature is missing from the bundle)
const markers = {
  [jsName]: ['MISSION SIMULATION · SYNTHETIC CREW A01–A04', 'Your measurements on the 3D human model', 'Personal 3D digital twin with stored measurements', 'Scan HRS monitors',
    'Scan nearby; verify HRS', 'Connected, waiting for measurements', 'Test with simulated HRS', '/api/devices/ble-diagnostics',
    '/api/devices/simulated', 'Run personal PHANTOM', 'Store & analyse SYNTHETIC control', 'Save manual measurement',
    'Surface toggles dim approximate body regions', 'X-ray toggles control inner layers', 'Stop, save & disconnect'],
  'index.html': [`/${jsName}`, `/${cssName}`],
};
const missing = [];
for (const [file, list] of Object.entries(markers)) {
  const text = readFileSync(join(out, file), 'utf8');
  for (const m of list) if (!text.includes(m)) missing.push(`${file}: "${m}"`);
}
for (const m of ['anatom.glb', 'carablik.glb', 'cosmo11.glb', 'cosmo11_lite.glb', 'meza.glb', 'skeleton.glb']) {
  const p = join(out, 'models', m);
  if (!existsSync(p) || readFileSync(p).subarray(0, 4).toString('latin1') !== 'glTF') missing.push(`asset models/${m}`);
}
if (/\/api\/biosignals\/sensor\//.test(readFileSync(join(out, 'index.html'), 'utf8'))) missing.push('index.html must not load the legacy sensor bridge');
if (missing.length) {
  console.error('BUILD FAILED release verification:\n  ' + missing.join('\n  '));
  process.exit(4);
}
const srcHash = createHash('sha256');
for (const f of listFiles(join(root, 'src'))) srcHash.update(f).update(readFileSync(join(root, 'src', f)));
for (const f of ['index.html', 'package.json']) srcHash.update(f).update(readFileSync(join(root, f)));
const outputs = Object.fromEntries(listFiles(out).filter((f) => !f.endsWith('.glb')).map((f) => [f, sha(readFileSync(join(out, f)))]));
writeFileSync(join(out, 'BUILD_INFO.json'), JSON.stringify({ release: '1.5.0-ble-personal', mode, built_utc: new Date().toISOString(),
  builder: 'scripts/build-release.mjs (esbuild ' + (esbuild.version ?? '?') + ' + tailwindcss compile API)', react: reactVersion,
  source_sha256: srcHash.digest('hex'), entry: { js: jsName, css: cssName }, outputs,
  note: 'Do not edit files in this directory; edit src/ or public/ and rebuild.' }, null, 2));
console.log(`built ${out} · ${jsName} (${(js.length / 1024).toFixed(0)} KB) · ${cssName} (${(css.length / 1024).toFixed(0)} KB) · react ${reactVersion}`);
