"""AETHER 1.4 build consistency: one source of truth for the frontend, no silent downgrades.

* committed dist-offline must be byte-identical to public/ for the static scripts,
* BUILD_INFO.json must match the current src/ + public/ hash (stale bundle detection),
* every release feature marker must be present in the committed bundle,
* a clean rebuild must reproduce the markers, and the build must refuse to overwrite
  hand-edited output or a newer Data Lab than public/ contains.
"""
import hashlib
import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

FRONT = Path(__file__).resolve().parents[2] / 'frontend'
DIST = FRONT / 'dist-offline'
MANIFEST = json.loads((FRONT / 'feature-manifest.json').read_text(encoding='utf-8'))
NODE_PATHS = os.environ.get('AETHER_NODE_PATHS', '/opt/npm-tools/node_modules')


def _files(base: Path):
    return sorted(p.relative_to(base).as_posix() for p in base.rglob('*') if p.is_file())


def source_hash() -> str:
    h = hashlib.sha256()
    for f in _files(FRONT / 'src'):
        h.update(f.encode()); h.update((FRONT / 'src' / f).read_bytes())
    for f in ('index.html', 'feature-manifest.json'):
        h.update(f.encode()); h.update((FRONT / f).read_bytes())
    for f in [x for x in _files(FRONT / 'public') if not x.endswith('.glb')]:
        h.update(f.encode()); h.update((FRONT / 'public' / f).read_bytes())
    return h.hexdigest()


def test_static_scripts_have_one_source_of_truth():
    for name in ('aether-nasa-data-lab.js', 'aether-sensor-bridge.js'):
        assert (FRONT / 'public' / name).read_bytes() == (DIST / name).read_bytes(), name


def test_committed_bundle_is_not_stale():
    info = json.loads((DIST / 'BUILD_INFO.json').read_text(encoding='utf-8'))
    assert info['feature_markers_verified'] is True and info['release'] == MANIFEST['release']
    assert info['source_sha256'] == source_hash(), 'dist-offline is stale: rebuild with scripts/build-offline.mjs'
    for f, digest in info['outputs'].items():
        assert hashlib.sha256((DIST / f).read_bytes()).hexdigest() == digest, f'{f} edited after build'


def test_committed_bundle_contains_every_release_feature():
    for file, markers in MANIFEST['files'].items():
        text = (DIST / file).read_text(encoding='utf-8')
        missing = [m for m in markers if m not in text]
        assert not missing, (file, missing)
    for asset in MANIFEST['required_assets']:
        assert (DIST / asset).read_bytes()[:4] == b'glTF', asset


def test_bundle_uses_same_origin_api_base():
    """1.3 regression: a hard-coded :8000 API base broke the random-port desktop build."""
    html = (DIST / 'index.html').read_text(encoding='utf-8')
    assert 'apiBase??"http://127.0.0.1:8000"' not in html
    # 1.5 (BLE personal rebuild): the base is resolved by state/runtimeConfig.resolveApiBase (no literal `apiBase??""`
    # any more): the page's own origin (browserOrigin) wins; :8000 is only the dev fallback for an opaque file:// origin.
    assert 'e.browserOrigin&&e.browserOrigin!=="null"?e.browserOrigin' in html.replace(' ', '')


def _node_ready():
    return shutil.which('node') and (Path(NODE_PATHS) / 'esbuild').exists() and (Path(NODE_PATHS) / 'tailwindcss').exists()


def _build(out: Path, *extra):
    return subprocess.run(['node', str(FRONT / 'scripts' / 'build-offline.mjs'), '--out', str(out), *extra],
                          cwd=FRONT, env={**os.environ, 'AETHER_NODE_PATHS': NODE_PATHS},
                          capture_output=True, text=True, timeout=300)


@pytest.mark.skipif(not _node_ready(), reason='node/esbuild/tailwindcss not available')
def test_clean_build_reproduces_features_and_guards_against_downgrade(tmp_path):
    out = tmp_path / 'clean'
    r = _build(out)
    assert r.returncode == 0, r.stderr
    for file, markers in MANIFEST['files'].items():
        text = (out / file).read_text(encoding='utf-8')
        assert all(m in text for m in markers), file
    info = json.loads((out / 'BUILD_INFO.json').read_text())
    assert info['source_sha256'] == source_hash()
    # Hand edit of the output -> the next build refuses to overwrite it.
    (out / 'aether-nasa-data-lab.js').write_text('/* AETHER NASA Data Lab 1.4 hotfix in dist */', encoding='utf-8')
    r = _build(out)
    assert r.returncode == 3 and 'changed after the last build' in r.stderr
    # Legacy output (no BUILD_INFO) with a NEWER Data Lab than public/ -> refuse (the 1.3 bug).
    legacy = tmp_path / 'legacy'
    legacy.mkdir()
    (legacy / 'aether-nasa-data-lab.js').write_text('/* AETHER NASA Data Lab 9.9 */', encoding='utf-8')
    r = _build(legacy)
    assert r.returncode == 3 and 'Merge the newer code into public/' in r.stderr
